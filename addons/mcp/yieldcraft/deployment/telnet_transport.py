#!/usr/bin/env python3
"""Interactive Telnet upload over an independently secured loopback tunnel."""
import base64
import getpass
import re
import secrets
import shlex
import sys
import warnings
from pathlib import Path

from probe import candidate_url


def transfer(pexpect, target, port, archive, args):
    user, host = target.split('@', 1)
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('loopback management tunnel required')
    if (re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,31}', user) is None
            or re.fullmatch(r'[1-9][0-9]{0,4}', port) is None or int(port) > 65535):
        raise ValueError('invalid Telnet login or port')
    # The localhost spelling is supported without using host name resolution.
    child = pexpect.spawn('telnet', ['-c', '127.0.0.1', port], encoding='utf-8',
                          codec_errors='replace', timeout=45, maxread=65536)
    try:
        child.expect(r'(?i)(login|username):\s*')
        child.sendline(user)
        if child.expect([r'(?i)password:\s*', r'[$#]\s*']) == 0:
            if not child.waitnoecho(timeout=10):
                raise ValueError('Telnet did not suppress password echo')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                child.sendline(getpass.getpass('Telnet password (secured tunnel): '))
            child.expect(r'[$#]\s*')

        nonce = secrets.token_hex(16)
        # No shell history or terminal echo for the transfer. A failed stty/mktemp
        # aborts before acknowledging. The expected marker is never sent verbatim.
        child.sendline(
            "set +x; set +v; unset HISTFILE || exit 1; stty -echo || exit 1; "
            "umask 077; t=$(mktemp -d) || exit 1; "
            "trap 'rm -rf -- \"$t\"' 0; trap 'exit 1' HUP INT TERM; "
            f"printf '\\nYC_%s_%s\\n' READY {nonce}"
        )
        child.expect(rf'\r?\nYC_READY_{nonce}\r?\n')
        child.sendline("base64 -d > \"$t/payload.tar.gz\" <<'YC_END_PAYLOAD' || exit 1")
        with archive.open('rb') as f:
            while data := f.read(384):
                child.sendline(base64.b64encode(data).decode('ascii'))
        child.sendline('YC_END_PAYLOAD')
        install = 'bash "$t/addon/deployment/manage.sh" "$t" ' + shlex.join(args)
        child.sendline(
            'if tar --no-same-owner --no-same-permissions -xzf "$t/payload.tar.gz" -C "$t"; '
            'then if [ "$(id -u)" = 0 ]; then ' + install + '; else sudo -n ' + install +
            '; fi; rc=$?; else rc=1; fi; rm -rf -- "$t" || exit 1; trap - 0; '
            f'printf "\\nYC_%s_%s_%s\\n" DONE {nonce} "$rc"'
        )
        child.expect(rf'\r?\nYC_DONE_{nonce}_([0-9]+)\r?\n', timeout=3600)
        # pexpect's transcript and exception messages may include password echoes
        # and installer output. Emit no transcript, even on successful installs.
        if child.match.group(1) != '0':
            return 1
        url = candidate_url(child.before.split('\n'), args[5])
        child.sendline('exit')
        print(url)
        return 0
    finally:
        child.close(force=True)


def main(argv):
    try:
        import pexpect
    except ImportError:
        print('Telnet transport requires pexpect', file=sys.stderr)
        return 2
    if len(argv) != 15:
        print('Telnet transport requires connection, archive and installation arguments', file=sys.stderr)
        return 2
    try:
        return transfer(pexpect, argv[0], argv[1], Path(argv[2]), argv[3:])
    except (pexpect.ExceptionPexpect, getpass.GetPassWarning,
            EOFError, OSError, ValueError, KeyboardInterrupt):
        print('Telnet transport failed; no session transcript was retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
