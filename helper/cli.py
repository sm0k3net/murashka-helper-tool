"""Configure and run the single-operator Murashka Helper Tool."""
import argparse
import asyncio
import contextlib
import fcntl
import getpass
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web

from integrations import Remote, VPN, valid_url
from service import Helper, hash_password


def atomic_config(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.config-')
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(data, file, indent=2)
            file.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def init(state, path, origin, port):
    if not 1024 <= port <= 65535:
        raise ValueError('Set a listen port between 1024 and 65535.')
    origin = valid_url(origin)
    if path.exists() or path.is_symlink():
        raise ValueError('This state has already been initialized.')
    token = getpass.getpass('Telegram bot token: ').strip()
    operator = input('Your numeric Telegram user ID: ').strip()
    if not re.fullmatch(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,128}', token) or not re.fullmatch(r'[1-9][0-9]{0,15}', operator):
        raise ValueError('Provide a BotFather token and a positive Telegram user ID.')
    password = getpass.getpass('Independent browser approval passphrase (16+ characters): ')
    if not 16 <= len(password) <= 512 or password == token:
        raise ValueError('Use a separate browser approval passphrase with 16–512 characters.')
    if password != getpass.getpass('Confirm browser approval passphrase: '):
        raise ValueError('Passphrases did not match.')
    salt = secrets.token_hex(16)
    atomic_config(path, {'origin': origin, 'port': port, 'operator': int(operator), 'telegram_token': token,
                         'salt': salt, 'verifier': hash_password(password, salt)})
    print('Initialized Helper Tool in ' + str(state))


async def start(config, remote, vpn):
    helper = Helper(config, remote, vpn)
    runner = web.AppRunner(helper.application(), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '127.0.0.1', config['port']).start()
        print(f"Browser approval API ready on 127.0.0.1:{config['port']}.", flush=True)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as client:
            await helper.poll(client)
    finally:
        await runner.cleanup()


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--state', default=os.getenv('MURASHKA_HELPER_STATE', '~/.local/state/murashka-helper-tool'))
    commands = cli.add_subparsers(dest='command', required=True)
    configure = commands.add_parser('init', help='Initialize the Telegram operator and HTTPS origin')
    configure.add_argument('--origin', required=True)
    configure.add_argument('--port', type=int, default=8770)
    remote = commands.add_parser('configure-remote', help='Set the local Remote SSH broker socket and token file')
    remote.add_argument('--socket', type=Path, required=True)
    remote.add_argument('--token-file', type=Path, required=True)
    wg = commands.add_parser('configure-wg', help='Set wg-easy 15.4.0 origin and Basic Auth credentials')
    wg.add_argument('--url', required=True)
    commands.add_parser('check', help='Check configured integration connectivity without writes')
    commands.add_parser('serve', help='Run one daemon for the Telegram bot and approval web API')
    return cli


async def check(remote, vpn):
    if remote:
        hosts = await remote.call('hosts')
        print(f'Remote SSH: {len(hosts)} allowed host(s).')
    if vpn:
        print(f'wg-easy: {len(await vpn.profiles())} visible profile(s).')


def main():
    os.umask(0o077)
    cli = parser()
    args = cli.parse_args()
    state = Path(args.state).expanduser().absolute()
    config_path = state / 'config.json'
    try:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if state.is_symlink() or state.stat().st_mode & 0o077 or state.stat().st_uid != os.getuid():
            raise ValueError('The state directory must belong to this account and have mode 0700.')
        if args.command == 'init':
            return init(state, config_path, args.origin, args.port)
        if config_path.is_symlink() or not config_path.is_file() or config_path.stat().st_mode & 0o077:
            raise ValueError('Run init first; config.json must be a private regular file.')
        config = json.loads(config_path.read_text())
        if args.command == 'configure-remote':
            remote = {'socket': str(args.socket.expanduser().absolute()),
                      'token_file': str(args.token_file.expanduser().absolute())}
            Remote.configured(remote)
            config['remote'] = remote
            atomic_config(config_path, config)
            print('Remote SSH broker saved.')
            return
        if args.command == 'configure-wg':
            endpoint = valid_url(args.url, allow_local_http=True)
            username = input('wg-easy API username: ').strip()
            password = getpass.getpass('wg-easy API password: ')
            if not username or ':' in username or not password:
                raise ValueError('Provide valid wg-easy Basic Auth credentials.')
            config['vpn'] = {'url': endpoint, 'username': username, 'password': password}
            atomic_config(config_path, config)
            print('wg-easy saved.')
            return
        remote = Remote.configured(config['remote']) if config.get('remote') else None
        vpn = VPN(config['vpn']) if config.get('vpn') else None
        if not remote and not vpn:
            raise ValueError('Configure Remote SSH, wg-easy, or both first.')
        if args.command == 'check':
            return asyncio.run(check(remote, vpn))
        fd = os.open(state / 'service.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another Helper daemon is using this state directory.') from None
            with contextlib.suppress(KeyboardInterrupt):
                asyncio.run(start(config, remote, vpn))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        cli.error(str(error))


if __name__ == '__main__':
    main()
