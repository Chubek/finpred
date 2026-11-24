#!/usr/bin/env python3
"""Generate bearer credentials without storing cleartext on the service host."""
import argparse, hashlib, json, os, secrets, re
from pathlib import Path
SCOPES=['research:read','artifact:write','dragnet:search','yieldcraft:analyze','yieldcraft:recommend','ottomat:generate','ottomat:simulate','daemon:manage','admin']
def exclusive(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(data+'\n')
def main():
    p=argparse.ArgumentParser();p.add_argument('--cleartext',type=Path,required=True);p.add_argument('--records',type=Path,required=True);p.add_argument('--project',default='default');p.add_argument('--admin',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',a.project):p.error('invalid project')
    token=secrets.token_urlsafe(48); scopes=SCOPES if a.admin else SCOPES[:-2]
    exclusive(a.cleartext,token); exclusive(a.records,json.dumps([{'sha256':hashlib.sha256(token.encode()).hexdigest(),'project':a.project,'scopes':scopes}],indent=2))
if __name__=='__main__':main()
