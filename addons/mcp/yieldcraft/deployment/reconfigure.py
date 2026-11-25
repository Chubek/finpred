#!/usr/bin/env python3
"""Change only the requested deploy-managed top-level TOML settings."""
import json
from pathlib import Path
import re
import sys
import tomllib


def rewrite(text, port, finpred, daemon, domain):
    current = tomllib.loads(text)
    if type(current.get('port')) is not int or current['port'] != port:
        raise ValueError('backend port mismatch')
    if current.get('finpred_root') != finpred or current.get('bind') != '127.0.0.1':
        raise ValueError('not an instance config')
    expected = current.copy()
    if daemon != '=':
        if daemon == '1' and (
            current.get('auth_required', True) is not True or not current.get('daemon_config')
        ):
            raise ValueError('daemon requires authenticated mode and a daemon config')
        if current.get('auth_required', True) or 'daemon_autostart' in current:
            expected['daemon_autostart'] = daemon == '1'
    if domain != '=':
        url = f'https://{domain}/mcp' if domain != '-' else None
        if current.get('oauth_issuer') and url != current.get('public_url'):
            raise ValueError('cannot change the public hostname of an OAuth deployment')
        if url is None:
            expected.pop('public_url', None)
        else:
            expected['public_url'] = url

    for key in ('daemon_autostart', 'public_url'):
        if current.get(key) == expected.get(key):
            continue
        line = f'{key} = {json.dumps(expected[key])}\n' if key in expected else ''
        if key in current:
            text, count = re.subn(rf'(?m)^[ \t]*{key}[ \t]*=[^\n]*(?:\n|\Z)', lambda _: line, text)
            if count != 1:
                raise ValueError('nonstandard managed TOML key')
        else:
            text = line + text
    if tomllib.loads(text) != expected:
        raise ValueError('rewrite would alter unrelated settings')
    return text


def main(args):
    try:
        source, target, port, finpred, daemon, domain = args
        with Path(source).open('rb') as f:
            original = f.read(65_537)
        if len(original) > 65_536:
            raise ValueError('config exceeds size bound')
        text = rewrite(original.decode(), int(port), finpred, daemon, domain)
        Path(target).write_bytes(text.encode())
    except (OSError, TypeError, ValueError):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
