"""Explicit allowlisted interfaces to the SSH broker and wg-easy."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

MAX_API_BYTES = 2 * 1024 * 1024


def valid_url(value, allow_local_http=False):
    url = urlsplit(value.strip())
    if (
        url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password
        or url.path not in ('', '/') or url.query or url.fragment
        or not re.fullmatch(r'[A-Za-z0-9.:-]+', url.hostname)
        or (url.port is not None and not 1 <= url.port <= 65535)
        or (url.scheme == 'http' and (not allow_local_http or url.hostname not in ('127.0.0.1', '::1')))
    ):
        raise ValueError('Use an HTTPS origin, or a loopback HTTP address for wg-easy.')
    host = f'[{url.hostname}]' if ':' in url.hostname else url.hostname
    port = f':{url.port}' if url.port not in (None, 443 if url.scheme == 'https' else 80) else ''
    return url.scheme + '://' + host + port


def label(value):
    return ' '.join(str(value).split())[:80]


class Remote:
    def __init__(self, path, token):
        self.path = str(path)
        self.token = token

    @classmethod
    def configured(cls, config):
        secret = Path(config['token_file']).expanduser()
        if not secret.is_file() or secret.is_symlink() or secret.stat().st_mode & 0o077:
            raise ValueError('The broker token must be a private file.')
        token = secret.read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{60,90}', token):
            raise ValueError('Invalid broker token.')
        return cls(config['socket'], token)

    async def call(self, operation, **parameters):
        if operation not in ('hosts', 'status', 'grant', 'revoke'):
            raise ValueError('Unknown broker operation.')
        writer = None
        try:
            async with asyncio.timeout(5):
                reader, writer = await asyncio.open_unix_connection(self.path, limit=8192)
                writer.write((json.dumps({'op': operation, 'token': self.token, **parameters}) + '\n').encode())
                await writer.drain()
                response = json.loads(await reader.readline())
        except (OSError, TimeoutError, ValueError):
            raise ValueError('Remote SSH broker is unavailable. Check its socket and service.') from None
        finally:
            if writer:
                writer.close()
        if response.get('ok') is not True:
            raise ValueError(label(response.get('error', 'Remote SSH rejected this operation.')))
        return response['result']


class VPN:
    def __init__(self, config):
        self.base = valid_url(config['url'], allow_local_http=True)
        self.username, self.password = config['username'], config['password']

    async def request(self, method, path, body=None, binary=False):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as client:
                async with client.request(method, self.base + '/api/client' + path, json=body,
                                          headers={'Authorization': aiohttp.encode_basic_auth(self.username, self.password, encoding='utf-8')},
                                          allow_redirects=False) as response:
                    if response.status in (401, 403):
                        raise ValueError('wg-easy rejected Basic Auth. Check credentials and the upstream authentication policy.')
                    if response.status == 404:
                        raise ValueError('wg-easy endpoint or profile was not found. Check v15.4.0 compatibility.')
                    if response.status not in (200, 201):
                        raise ValueError('wg-easy returned HTTP ' + str(response.status) + '. Verify the service and API contract.')
                    data = bytearray()
                    limit = 65536 if binary else MAX_API_BYTES
                    async for block in response.content.iter_chunked(8192):
                        data.extend(block)
                        if len(data) > limit:
                            raise ValueError('wg-easy response exceeded the configured limit.')
        except (aiohttp.ClientError, OSError, TimeoutError):
            raise ValueError('Cannot reach wg-easy with a verified connection.') from None
        if binary:
            if b'[Interface]' not in data or b'[Peer]' not in data:
                raise ValueError('wg-easy did not return a WireGuard configuration.')
            return bytes(data)
        try:
            return json.loads(data)
        except ValueError:
            raise ValueError('wg-easy did not return the expected API response.') from None

    async def profiles(self):
        result = await self.request('GET', '')
        if not isinstance(result, list):
            raise ValueError('Unexpected wg-easy profile response.')
        return [{'id': peer['id'], 'name': label(peer.get('name', 'VPN profile')),
                 'enabled': peer.get('enabled') is True}
                for peer in result[:100] if isinstance(peer, dict) and type(peer.get('id')) is int]

    async def profile(self, ident):
        if type(ident) is not int or ident < 1:
            raise ValueError('Invalid VPN profile ID.')
        result = await self.request('GET', f'/{ident}')
        if not isinstance(result, dict) or result.get('id') != ident:
            raise ValueError('Unexpected wg-easy profile response.')
        return {'id': ident, 'name': label(result.get('name', 'VPN profile'))}

    async def create(self, name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,59}', name):
            raise ValueError('Use 1–60 letters, digits, spaces, dots, hyphens or underscores.')
        result = await self.request('POST', '', {'name': name, 'expiresAt': None})
        if not isinstance(result, dict) or result.get('success') is not True or type(result.get('clientId')) is not int:
            raise ValueError('Unexpected creation result. Check wg-easy before retrying.')
        return result['clientId']

    async def set_enabled(self, ident, enabled):
        await self.profile(ident)
        result = await self.request('POST', f'/{ident}/' + ('enable' if enabled else 'disable'))
        if not isinstance(result, dict) or result.get('success') is not True:
            raise ValueError('Unexpected update result. Check wg-easy before retrying.')

    async def configuration(self, ident):
        await self.profile(ident)
        return await self.request('GET', f'/{ident}/configuration', binary=True)
