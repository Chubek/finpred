#!/usr/bin/env python3
"""Check public TLS + actual MCP handshake and tools/list without printing secrets."""
import json,sys,time,urllib.request,urllib.error
from pathlib import Path

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def probe(url,token):
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
    def call(method,params,ident):
        payload={'jsonrpc':'2.0','method':method,'params':params}
        if ident is not None: payload['id']=ident
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'})
        with opener.open(req,timeout=15) as r:
            if ident is None: return
            if 'application/json' not in r.headers.get('Content-Type',''): raise RuntimeError('expected JSON transport')
            v=json.loads(r.read(2_000_000))
            if v.get('id')!=ident or 'error' in v: raise RuntimeError('MCP call rejected')
            return v['result']
    info=call('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'yieldcraft-deploy-probe','version':'0.1.0'}},1)
    call('notifications/initialized',{},None)
    result=call('tools/list',{},2)
    if not any(t['name']=='yieldcraft_optimize_contribution' for t in result['tools']): raise RuntimeError('required tool missing')
    print('[OK] MCP initialization and tools/list verified:',info['serverInfo']['name'])
if __name__=='__main__':
    url=sys.argv[1]; token=Path(sys.argv[2]).read_text().strip()
    for i in range(12):
        try: probe(url,token); sys.exit(0)
        except (OSError,ValueError,RuntimeError,KeyError) as e:
            if i==11: print('Public probe failed: '+type(e).__name__,file=sys.stderr); sys.exit(1)
            time.sleep(5)
