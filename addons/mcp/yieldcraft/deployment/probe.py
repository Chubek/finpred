#!/usr/bin/env python3
"""Validate the deployment destination and probe MCP without logging credentials."""
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.request

LABEL = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
HOST = re.compile(rf'(?=.{{1,253}}\Z)(?:{LABEL}\.)+{LABEL}')
URL = re.compile(r'https://([^/]+)/mcp')
QUICK_HOST = re.compile(rf'{LABEL}\.trycloudflare\.com')
MARKER = 'MCP_CANDIDATE_URL='


def destination(url):
    match = URL.fullmatch(url)
    if match is None or HOST.fullmatch(match[1]) is None:
        raise ValueError('invalid HTTPS MCP destination')
    return match[1]


def candidate_url(lines, domain):
    url = None
    for line in lines:
        if not line.startswith(MARKER):
            continue
        if url is not None:
            raise ValueError('multiple MCP candidates')
        url = line[len(MARKER):].removesuffix('\n').removesuffix('\r')
        host = destination(url)
        if not (QUICK_HOST.fullmatch(host) if domain == '-' else host == domain):
            raise ValueError('unexpected MCP candidate host')
    if url is None:
        raise ValueError('missing MCP candidate')
    return url


def read_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('expected a private regular token file')
        value = f.read(8194).removesuffix(b'\n')
    if re.fullmatch(rb'[A-Za-z0-9_-]{1,8192}', value) is None:
        raise ValueError('invalid token file')
    return value.decode('ascii')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url, token=None):
    destination(url)
    # Require ordinary TLS verification, but do not enable SSLKEYLOGFILE.
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls.load_default_certs()
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=tls)
    )

    def call(method, params, ident):
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if ident is not None:
            payload['id'] = ident
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': '2025-11-25',
        }
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with opener.open(req, timeout=15) as r:
            if ident is None:
                return
            if r.headers.get_content_type() != 'application/json':
                raise RuntimeError('expected JSON transport')
            body = r.read(2_000_001)
            if len(body) > 2_000_000:
                raise RuntimeError('response too large')
            v = json.loads(body)
            if v.get('id') != ident or 'error' in v:
                raise RuntimeError('MCP call rejected')
            return v['result']

    info = call('initialize', {
        'protocolVersion': '2025-11-25', 'capabilities': {},
        'clientInfo': {'name': 'yieldcraft-deploy-probe', 'version': '0.1.0'},
    }, 1)
    if not isinstance(info['serverInfo']['name'], str):
        raise RuntimeError('invalid MCP server info')
    call('notifications/initialized', {}, None)
    result = call('tools/list', {}, 2)
    expected = 'yieldcraft_demo' if token is None else 'yieldcraft_optimize_contribution'
    if not any(t['name'] == expected for t in result['tools']):
        raise RuntimeError('required tool missing')
    print('[OK] MCP initialization and tools/list verified')


def main(argv):
    if len(argv) not in (1, 2):
        print('Public probe requires a URL and optional token file', file=sys.stderr)
        return 2
    url = argv[0]
    if url == '--candidate':
        if len(argv) != 2:
            return 2
        try:
            print(candidate_url(sys.stdin, argv[1]))
            return 0
        except ValueError:
            # Let SSH finish and report its status even after an invalid marker.
            for _ in sys.stdin:
                pass
            return 1
    try:
        destination(url)
        token = read_token(argv[1]) if len(argv) == 2 else None
    except (OSError, ValueError):
        print('Public probe requires a valid HTTPS URL and, if supplied, a private token file', file=sys.stderr)
        return 1
    for i in range(12):
        try:
            probe(url, token)
            return 0
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
            if i != 11:
                time.sleep(5)
    print('Public probe failed', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
