import asyncio
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import encode_basic_auth, web
from aiohttp.test_utils import TestClient, TestServer

from integrations import Remote, VPN, valid_url
from service import Helper, hash_password

ORIGIN = 'https://helper.example.org'
PASSWORD = 'synthetic independent passphrase'
FRAGMENT = re.compile(r'#request=([A-Za-z0-9_-]{43})')


class IntegratedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        socket = Path(directory.name) / 'broker.sock'
        self.calls = []
        self.peers = {
            7: {'id': 7, 'name': 'Travel laptop', 'enabled': True, 'privateKey': 'fixture-private-wireguard-key'}
        }

        async def broker(reader, writer):
            try:
                data = json.loads(await reader.readline())
                self.calls.append(data['op'])
                assert data['token'] == 'fixture-broker'
                result = {
                    'hosts': [{'id': 1, 'name': 'Staging'}],
                    'status': {'name': 'Staging', 'checked': time.time(), 'metrics': {'cpu': 8}},
                    'grant': {'url': 'https://remote.example.org/#g=fixture', 'password': 'fixture-remote-password',
                              'id': 'abcdefghijklmnop'},
                    'revoke': {'revoked': True},
                }[data['op']]
                writer.write((json.dumps({'ok': True, 'result': result}) + '\n').encode())
                await writer.drain()
            finally:
                writer.close()

        try:
            listener = await asyncio.start_unix_server(broker, path=socket)
        except PermissionError:
            # Managed test sandboxes may block AF_UNIX entirely. Exercise
            # the same wire protocol over a disposable loopback fixture.
            listener = await asyncio.start_server(broker, host='127.0.0.1', port=0)
            port = listener.sockets[0].getsockname()[1]

            async def test_connection(_path, **kwargs):
                return await asyncio.open_connection('127.0.0.1', port, **kwargs)

            self.enterContext(patch('integrations.asyncio.open_unix_connection', test_connection))
        self.addAsyncCleanup(self.close_listener, listener)

        async def wg(request):
            self.assertEqual(request.headers['Authorization'], encode_basic_auth('fixture-user', 'fixture-password'))
            peer = request.match_info.get('peer')
            action = request.match_info.get('action')
            if not peer:
                if request.method == 'POST':
                    body = await request.json()
                    self.assertEqual(body, {'name': 'Test device', 'expiresAt': None})
                    self.peers[8] = {'id': 8, 'name': body['name'], 'enabled': True}
                    return web.json_response({'success': True, 'clientId': 8})
                return web.json_response(list(self.peers.values()))
            peer = int(peer)
            if action == 'configuration':
                return web.Response(body=b'[Interface]\nPrivateKey = fixture-private-wireguard-key\n[Peer]\n')
            if action in ('enable', 'disable'):
                self.peers[peer]['enabled'] = action == 'enable'
                return web.json_response({'success': True})
            return web.json_response(self.peers[peer])

        app = web.Application()
        app.router.add_route('*', '/api/client', wg)
        app.router.add_route('*', '/api/client/{peer}', wg)
        app.router.add_route('*', '/api/client/{peer}/{action}', wg)
        upstream = TestServer(app)
        await upstream.start_server()
        self.addAsyncCleanup(upstream.close)
        salt = 'a1' * 16
        self.helper = Helper({'origin': ORIGIN, 'operator': 41, 'telegram_token': 'fixture',
                              'salt': salt, 'verifier': hash_password(PASSWORD, salt)},
                             Remote(socket, 'fixture-broker'),
                             VPN({'url': str(upstream.make_url('/')), 'username': 'fixture-user', 'password': 'fixture-password'}))
        self.portal = TestClient(TestServer(self.helper.application()))
        await self.portal.start_server()
        self.addAsyncCleanup(self.portal.close)

    async def close_listener(self, listener):
        listener.close()
        await listener.wait_closed()

    async def approve(self, ident, password=PASSWORD, origin=ORIGIN):
        return await self.portal.post('/approve', data={'id': ident, 'password': password}, headers={'Origin': origin})

    async def test_ssh_grant_requires_correct_origin_passphrase_and_single_use(self):
        self.assertIn('Staging', await self.helper.command('/hosts'))
        reply = await self.helper.command('/connect 1')
        self.assertNotIn('fixture-remote-password', reply)
        self.assertNotIn('remote.example.org/#g=', reply)
        ident = FRAGMENT.search(reply)[1]
        response = await self.portal.post('/preview', json={'id': ident}, headers={'Origin': ORIGIN})
        self.assertEqual((await response.json())['summary'], 'Open SSH workspace for Staging')
        self.assertEqual((await self.approve(ident, origin='https://untrusted.example')).status, 403)
        self.assertEqual((await self.approve(ident, password='bad')).status, 401)
        self.assertNotIn('grant', self.calls)
        first, second = await asyncio.gather(self.approve(ident), self.approve(ident))
        self.assertIn(200, (first.status, second.status))
        self.assertEqual(self.calls.count('grant'), 1)
        successful = first if first.status == 200 else second
        self.assertIn('fixture-remote-password', await successful.text())
        self.assertEqual(successful.headers['Cache-Control'], 'no-store')
        self.assertEqual((await self.approve(ident)).status, 404)
        revoke = FRAGMENT.search(await self.helper.command('/revoke abcdefghijklmnop'))[1]
        self.assertIn('Workspace revoked', await (await self.approve(revoke)).text())

    async def test_wg_easy_profile_create_download_disable_and_enable(self):
        listing = await self.helper.command('/vpn')
        self.assertIn('Travel laptop', listing)
        self.assertNotIn('fixture-private-wireguard-key', listing)
        create = FRAGMENT.search(await self.helper.command('/vpn-new Test device'))[1]
        self.assertNotIn(8, self.peers)
        self.assertIn('Profile <code>8</code>', await (await self.approve(create)).text())
        link = await self.helper.command('/vpn-config 7')
        self.assertNotIn('fixture-private-wireguard-key', link)
        download = await self.approve(FRAGMENT.search(link)[1])
        self.assertIn('attachment', download.headers['Content-Disposition'])
        self.assertIn(b'fixture-private-wireguard-key', await download.read())
        for operation, enabled in [('disable', False), ('enable', True)]:
            token = FRAGMENT.search(await self.helper.command(f'/vpn-{operation} 7'))[1]
            self.assertEqual((await self.approve(token)).status, 200)
            self.assertEqual(self.peers[7]['enabled'], enabled)

    async def test_sender_age_and_form_errors(self):
        allowed = {'chat': {'type': 'private', 'id': 41}, 'from': {'id': 41}, 'date': int(time.time()), 'text': '/hosts'}
        self.assertEqual(self.helper.allowed_message({'message': allowed}), '/hosts')
        self.assertIsNone(self.helper.allowed_message({'message': {**allowed, 'from': {'id': 42}}}))
        self.assertIsNone(self.helper.allowed_message({'message': {**allowed, 'chat': {'type': 'group', 'id': 41}}}))
        self.assertIsNone(self.helper.allowed_message({'message': {**allowed, 'date': int(time.time()) - 121}}))
        response = await self.portal.post('/preview', json=['invalid'], headers={'Origin': ORIGIN})
        self.assertEqual(response.status, 400)
        with self.assertRaises(ValueError):
            valid_url('http://untrusted.example', allow_local_http=True)
        with self.assertRaises(ValueError):
            valid_url('https://user:password@helper.example.org')
