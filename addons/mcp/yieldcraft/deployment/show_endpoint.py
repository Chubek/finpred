#!/usr/bin/env python3
"""Read the existing MCP endpoint without changing or probing the deployment."""
import os
import re
import stat
import sys
import tomllib
from pathlib import Path

CONFIG = Path('/etc/yieldcraft-mcp/config.toml')
LOGS = Path('/var/log/yieldcraft-mcp')
CONFIG_LIMIT = 64 * 1024
LOG_TAIL = 256 * 1024
MARKER = 'MCP_CANDIDATE_URL='

# Keep the DNS/HTTPS rules in sync with the host-side selector in probe.py.
# This helper is sent on SSH stdin, so it cannot import an adjacent file.
LABEL = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
HTTPS_MCP = re.compile(rf'https://((?:{LABEL}\.)+{LABEL})/mcp')
# Match complete URL tokens, including in cloudflared's quoted JSON log messages
# and banner lines. A suffix, path, query, port or userinfo must not be stripped.
QUICK_URL = re.compile(
    rf'(?:^|[ \t"|])https://({LABEL}\.trycloudflare\.com)(?=$|[ \t"|])'.encode('ascii')
)


def open_regular(path, *, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('expected a regular file')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def existing_endpoint(config: dict, logs: Path) -> str:
    """Return the configured URL or the most recent complete Quick Tunnel URL."""
    if 'public_url' in config:
        url = config['public_url']
        match = HTTPS_MCP.fullmatch(url) if isinstance(url, str) else None
        if match is None or len(match[1]) > 253:
            raise ValueError('invalid HTTPS MCP destination')
        return url

    dir_fd = os.open(logs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with open_regular('cloudflared.log', dir_fd=dir_fd) as log:
            info = os.fstat(log.fileno())
            # The service owns both the directory and its log. Do not follow
            # links or read a file owned by another user (including from patch.py).
            if info.st_uid != os.fstat(dir_fd).st_uid or info.st_nlink != 1:
                raise ValueError('unexpected Cloudflare log ownership or link count')
            offset = max(0, info.st_size - LOG_TAIL)
            at_line_start = True
            if offset:
                log.seek(offset - 1)
                at_line_start = log.read(1) == b'\n'
            tail = log.read(LOG_TAIL)
    finally:
        os.close(dir_fd)
    if not at_line_start:
        tail = tail.partition(b'\n')[2]  # The first line may start mid-URL.
    for line in reversed(tail.split(b'\n')):
        hosts = QUICK_URL.findall(line.removesuffix(b'\r'))
        if len(hosts) > 1:
            raise ValueError('ambiguous Quick Tunnel log line')
        if hosts:
            return f'https://{hosts[0].decode("ascii")}/mcp'
    raise ValueError('missing Quick Tunnel URL')


def main(argv):
    if len(argv) != 1 or re.fullmatch(r'[1-9][0-9]{0,4}', argv[0]) is None:
        return 54
    port = int(argv[0])
    try:
        with open_regular(CONFIG) as file:
            data = file.read(CONFIG_LIMIT + 1)
        if len(data) > CONFIG_LIMIT:
            return 54
        config = tomllib.loads(data.decode('utf-8'))
        installed_port = config.get('port')
        if not 1 <= port <= 65535 or type(installed_port) is not int or installed_port != port:
            return 54
    except (OSError, ValueError):
        return 54
    try:
        url = existing_endpoint(config, LOGS)
    except (OSError, ValueError):
        return 55
    print(MARKER + url)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
