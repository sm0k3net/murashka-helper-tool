"""Telegram commands and one-use browser approval."""
import asyncio
import hashlib
import hmac
import html
import re
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from integrations import label, valid_url

HELP = (
    '/hosts — list allowed Remote SSH hosts\n'
    '/status HOST_ID — latest sampled resource usage\n'
    '/connect HOST_ID — approve a temporary SSH workspace in the browser\n'
    '/revoke GRANT_ID — approve revocation of a Helper-issued workspace\n'
    '/vpn — list wg-easy profiles\n'
    '/vpn-new NAME — approve a new profile\n'
    '/vpn-config ID — download a profile after browser approval\n'
    '/vpn-disable ID · /vpn-enable ID — approve an access change'
)


def hash_password(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024**2).hex()


class Helper:
    def __init__(self, config, remote=None, vpn=None):
        self.origin = valid_url(config['origin'])
        self.operator = config['operator']
        self.token = config['telegram_token']
        self.salt, self.verifier = config['salt'], config['verifier']
        self.remote, self.vpn = remote, vpn
        self.requests = {}
        self.failures = deque()
        self.verify_lock = asyncio.Lock()
        self.offset = 0
        self.started = int(time.time())

    def intent(self, action, value, summary):
        now = time.monotonic()
        self.requests = {ident: item for ident, item in self.requests.items() if item['expires'] > now}
        if len(self.requests) >= 32:
            raise ValueError('Too many pending approvals. Wait for a request to expire.')
        ident = secrets.token_urlsafe(32)
        self.requests[ident] = {'action': action, 'value': value, 'summary': summary, 'expires': now + 300}
        return summary + '\nApprove within 5 minutes: ' + self.origin + '/#request=' + ident

    def allowed_message(self, update):
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        timestamp = message.get('date')
        if (chat.get('type') == 'private' and chat.get('id') == self.operator
                and sender.get('id') == self.operator and type(timestamp) is int
                and self.started <= timestamp <= time.time() + 10 and time.time() - timestamp <= 120
                and isinstance(message.get('text'), str)):
            return message['text'].strip()[:256]
        return None

    async def command(self, message):
        command, _, argument = message.partition(' ')
        argument = argument.strip()
        if command in ('/hosts', '/status', '/connect', '/revoke') and not self.remote:
            return 'Remote SSH is not configured.'
        if command.startswith('/vpn') and not self.vpn:
            return 'wg-easy is not configured.'
        if command == '/hosts':
            hosts = await self.remote.call('hosts')
            return '\n'.join(str(host['id']) + ' · ' + label(host['name']) for host in hosts) or 'No allowed hosts are available.'
        if command in ('/status', '/connect'):
            if not re.fullmatch(r'[1-9][0-9]{0,8}', argument):
                return 'Usage: ' + command + ' HOST_ID'
            host = int(argument)
            info = await self.remote.call('status', host=host)
            name = label(info['name'])
            if command == '/connect':
                return self.intent('ssh', host, 'Open SSH workspace for ' + name)
            checked = info['checked']
            if not checked:
                return name + '\nNo sample yet. Open Monitoring in Remote SSH.'
            stats = ' · '.join(k.upper() + ' ' + str(v) + '%' for k, v in info['metrics'].items())
            return name + '\nSample age: ' + str(max(0, int(time.time() - checked) // 60)) + ' min\n' + stats
        if command == '/revoke':
            if not re.fullmatch(r'[A-Za-z0-9_-]{16}', argument):
                return 'Usage: /revoke GRANT_ID'
            return self.intent('revoke', argument, 'Revoke Helper-issued workspace ' + argument)
        if command == '/vpn':
            peers = await self.vpn.profiles()
            return '\n'.join(f"{p['id']} · {p['name']} · " + ('enabled' if p['enabled'] else 'disabled')
                             for p in peers) or 'No VPN profiles found.'
        if command == '/vpn-new':
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,59}', argument):
                return 'Usage: /vpn-new NAME (1–60 letters, numbers, spaces, dots, hyphens or underscores)'
            return self.intent('vpn-new', argument, 'Create VPN profile ' + argument)
        if command in ('/vpn-config', '/vpn-enable', '/vpn-disable'):
            if not re.fullmatch(r'[1-9][0-9]{0,8}', argument):
                return 'Usage: ' + command + ' ID'
            ident = int(argument)
            profile = await self.vpn.profile(ident)
            verb = {'/vpn-config': 'Download', '/vpn-enable': 'Enable', '/vpn-disable': 'Disable'}[command]
            return self.intent(command[1:], ident, f"{verb} VPN profile {profile['name']} (#{ident})")
        return HELP

    async def telegram(self, client, method, data):
        async with client.post('https://api.telegram.org/bot' + self.token + '/' + method,
                               json=data, allow_redirects=False) as response:
            if response.status in (401, 409):
                raise RuntimeError('Bot token was rejected, a webhook is enabled, or another process is polling this bot.')
            if response.status != 200:
                raise OSError('Telegram request unsuccessful.')
            payload = await response.json()
            if not payload.get('ok'):
                raise OSError('Telegram request unsuccessful.')
            return payload['result']

    async def poll(self, session):
        while True:
            try:
                updates = await self.telegram(session, 'getUpdates', {
                    'offset': self.offset, 'timeout': 25, 'allowed_updates': ['message'],
                })
                for update in updates:
                    self.offset = update['update_id'] + 1
                    message = self.allowed_message(update)
                    if not message:
                        continue
                    try:
                        reply = await self.command(message)
                    except ValueError as error:
                        reply = str(error)
                    except Exception:
                        reply = 'Integration unavailable. Check the gateway configuration.'
                    await self.telegram(session, 'sendMessage', {
                        'chat_id': self.operator, 'text': reply[:4000], 'protect_content': True,
                        'link_preview_options': {'is_disabled': True},
                    })
            except (aiohttp.ClientError, OSError, TimeoutError):
                await asyncio.sleep(5)

    def lookup(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ident):
            raise web.HTTPNotFound(text='Request expired or unavailable.')
        item = self.requests.get(ident)
        if not item or item['expires'] <= time.monotonic():
            self.requests.pop(ident, None)
            raise web.HTTPNotFound(text='Request expired or unavailable.')
        return item

    def same_origin(self, request):
        if request.headers.get('Origin') != self.origin:
            raise web.HTTPForbidden(text='Open the approval page from the configured HTTPS origin.')

    async def preview(self, request):
        self.same_origin(request)
        payload = await request.json()
        return web.json_response({'summary': self.lookup(payload.get('id'))['summary']})

    async def approve(self, request):
        self.same_origin(request)
        form = await request.post()
        ident = form.get('id')
        item = self.lookup(ident)
        now = time.monotonic()
        while self.failures and self.failures[0] < now - 60:
            self.failures.popleft()
        if len(self.failures) >= 12 or self.verify_lock.locked():
            raise web.HTTPTooManyRequests(text='Wait a moment and try again.')
        password = form.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 512:
            raise web.HTTPBadRequest(text='Enter the operator passphrase.')
        async with self.verify_lock:
            computed = await asyncio.to_thread(hash_password, password, self.salt)
            if not hmac.compare_digest(computed, self.verifier):
                self.failures.append(now)
                return self.page('Try again', '<p>Incorrect passphrase.</p><p>' + html.escape(item['summary']) + '</p>' + self.form(ident), status=401)
            self.lookup(ident)
            self.requests.pop(ident)
        try:
            return await self.execute(item['action'], item['value'])
        except ValueError as error:
            return self.page('Operation unavailable', '<p>' + html.escape(str(error)) + '</p><p>Check the integration before requesting another approval.</p>', status=502)

    async def execute(self, action, value):
        if action == 'ssh':
            grant = await self.remote.call('grant', host=value)
            target = urlsplit(grant['url'])
            if target.scheme != 'https' or not target.hostname or target.username or target.password:
                raise ValueError('The broker returned an invalid workspace URL.')
            url = html.escape(grant['url'], quote=True)
            passcode = html.escape(grant['password'])
            ident = html.escape(grant['id'])
            return self.page('Workspace ready', f'<p><a rel="noreferrer" href="{url}">Open Remote SSH</a></p>'
                             f'<p>Temporary password <code>{passcode}</code></p><p>Grant ID <code>{ident}</code></p>'
                             '<p>This workspace expires in 30 minutes. Keep its credentials in this browser.</p>')
        if action == 'revoke':
            await self.remote.call('revoke', id=value)
            return self.page('Workspace revoked', '<p>Remote SSH has revoked this Helper-issued access link.</p>')
        if action == 'vpn-config':
            config = await self.vpn.configuration(value)
            return web.Response(body=config, content_type='application/octet-stream',
                                headers={'Content-Disposition': f'attachment; filename="wireguard-{value}.conf"'})
        if action == 'vpn-new':
            ident = await self.vpn.create(value)
            return self.page('VPN profile created', f'<p>Profile <code>{ident}</code> is ready. Use <code>/vpn-config {ident}</code> for its configuration.</p>')
        if action in ('vpn-enable', 'vpn-disable'):
            enabled = action == 'vpn-enable'
            await self.vpn.set_enabled(value, enabled)
            return self.page('VPN profile updated', '<p>Access is ' + ('enabled.' if enabled else 'disabled.') + '</p>')
        raise web.HTTPBadRequest(text='Unknown approval action.')

    @staticmethod
    def page(title, body, status=200):
        return web.Response(status=status, content_type='text/html', text=f'''<!doctype html><html lang="en">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Murashka Helper Tool</title><link rel="stylesheet" href="/portal.css">
<main><p class="label">MURASHKA HELPER TOOL</p><h1>{title}</h1>{body}</main></html>''')

    @staticmethod
    def form(ident=''):
        hidden = '' if ident else ' hidden'
        safe = html.escape(ident, quote=True)
        return f'''<form action="/approve" method="post"{hidden}><input type="hidden" name="id" value="{safe}">
<label>Operator passphrase<input name="password" type="password" autocomplete="current-password" maxlength="512" required></label>
<button>Approve this action</button></form>'''

    async def index(self, request):
        return self.page('Approve a request',
                         '<p id="status" role="status">Open the approval link from your private bot chat.</p>'
                         + self.form() + '<script src="/portal.js" defer></script>')

    def application(self):
        @web.middleware
        async def security_headers(request, handler):
            try:
                response = await handler(request)
            except web.HTTPException as error:
                response = web.Response(status=error.status, text=error.text)
            except (ValueError, KeyError, TypeError, AttributeError):
                response = web.Response(status=400, text='Invalid request.')
            response.headers.update({
                'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                'Content-Security-Policy': "default-src 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
            })
            return response
        app = web.Application(client_max_size=8192, middlewares=[security_headers])
        app.router.add_get('/', self.index)
        app.router.add_post('/preview', self.preview)
        app.router.add_post('/approve', self.approve)

        async def asset(request):
            return web.FileResponse(Path(__file__).with_name('portal.' + request.match_info['ext']))
        app.router.add_get('/portal.{ext:css|js}', asset)
        return app
