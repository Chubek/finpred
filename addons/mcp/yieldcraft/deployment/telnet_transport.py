#!/usr/bin/env python3
"""Interactive Telnet upload over an independently secured loopback tunnel.
Requires pexpect and the system telnet client. No credential or upload logging.
"""
import base64,getpass,sys,shlex,re
from pathlib import Path

def main():
    import pexpect
    user,host=sys.argv[1].split('@',1); port=sys.argv[2]; archive=Path(sys.argv[3]); args=sys.argv[4:]
    if host not in ('127.0.0.1','localhost'): raise SystemExit('loopback management tunnel required')
    child=pexpect.spawn('telnet',[host,port],encoding='utf-8',timeout=45,maxread=65536)
    try:
        child.expect(r'(?i)(login|username):\s*'); child.sendline(user)
        i=child.expect([r'(?i)password:\s*',r'[$#]\s*'])
        if i==0:
            child.sendline(getpass.getpass('Telnet password (secured tunnel): ')); child.expect(r'[$#]\s*')
        child.sendline("stty -echo; printf '\\nYC_%s\\n' READY")
        child.expect(r'\r?\nYC_READY\r?\n')
        child.sendline("umask 077; t=$(mktemp -d); base64 -d > \"$t/payload.tar.gz\" <<'YC_END_PAYLOAD'")
        with archive.open('rb') as f:
            while data:=f.read(384): child.sendline(base64.b64encode(data).decode())
        child.sendline('YC_END_PAYLOAD')
        install='bash "$t/addon/deployment/install.sh" "$t" '+shlex.join(args)
        child.sendline('if tar -xzf "$t/payload.tar.gz" -C "$t"; then if [ "$(id -u)" = 0 ]; then '+install+'; else sudo -n '+install+'; fi; rc=$?; else rc=1; fi; rm -rf -- "$t"; printf "\\nYC_DONE_%s\\n" "$rc"')
        child.expect(r'\r?\nYC_DONE_([0-9]+)\r?\n',timeout=3600)
        print(child.before.replace('\r',''),end=''); rc=int(child.match.group(1)); child.sendline('exit'); return rc
    finally: child.close(force=True)
if __name__=='__main__': sys.exit(main())
