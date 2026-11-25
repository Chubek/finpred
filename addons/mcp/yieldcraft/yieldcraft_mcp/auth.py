from __future__ import annotations
import asyncio, hashlib, hmac, json, math, re, stat, time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import httpx
from .config import Config, authority, https_origin, https_url

SCOPES=frozenset({'research:read','artifact:write','dragnet:search','yieldcraft:analyze','yieldcraft:recommend','ottomat:generate','ottomat:simulate','daemon:manage','admin'})
PROJECT=re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
OAUTH_PROJECT=re.compile(r'oauth-[0-9a-f]{48}')
OAUTH_TIMEOUT=5
OAUTH_RESPONSE_LIMIT=65536
OAUTH_SCOPE=re.compile(r'[\x21\x23-\x5b\x5d-\x7e]+(?: +[\x21\x23-\x5b\x5d-\x7e]+)*')
TOKEN68=re.compile(r'[A-Za-z0-9._~+/-]+=*',re.ASCII)
BEARER=re.compile(r'Bearer +([A-Za-z0-9._~+/-]+=*)',re.ASCII|re.IGNORECASE)
QUICK_TUNNEL=re.compile(r'[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
PUBLIC_ROUTES=frozenset(('/healthz','/readyz','/version','/editor','/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-protected-resource'))
SINGLETON_HEADERS=frozenset((b'authorization',b'origin',b'host',b'content-length',b'content-type',b'transfer-encoding',b'mcp-protocol-version',b'mcp-session-id'))
@dataclass(frozen=True)
class Principal:
    project: str
    scopes: frozenset[str]
    def require(self, *scopes):
        if not set(scopes)<=self.scopes: raise PermissionError('insufficient scope')
current: ContextVar[Principal|None]=ContextVar('principal',default=None)
PUBLIC_DEMO=Principal('public-demo',frozenset({'research:read'}))
def principal(*scopes):
    p=current.get()
    if p is None: raise PermissionError('authenticated principal required')
    p.require(*scopes); return p

def private_read(path: Path, maximum=65536):
    import os
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_mode&0o077 or s.st_uid not in (0,os.geteuid()): raise ValueError('secret must be a private regular file owned by root/service user')
        b=f.read(maximum+1)
        if len(b)>maximum: raise ValueError('secret too large')
        return b

def _unique_object(items):
    out={}
    for key,value in items:
        if key in out: raise ValueError('duplicate JSON member')
        out[key]=value
    return out

def _reject_constant(_):
    raise ValueError('nonfinite JSON number')

def parse_tokens(path):
    rows=json.loads(private_read(path),object_pairs_hook=_unique_object,parse_constant=_reject_constant)
    if not isinstance(rows,list) or not 1<=len(rows)<=128: raise ValueError('invalid token list')
    out=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'sha256','project','scopes'}: raise ValueError('invalid token record')
        digest,project,scopes=row['sha256'],row['project'],row['scopes']
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or not isinstance(project,str) or not PROJECT.fullmatch(project) or not isinstance(scopes,list) or any(not isinstance(s,str) or s not in SCOPES for s in scopes): raise ValueError('invalid token record')
        if OAUTH_PROJECT.fullmatch(project): raise ValueError('static token project overlaps OAuth namespace')
        if any(hmac.compare_digest(digest,x[0]) for x in out): raise ValueError('duplicate token')
        out.append((digest,Principal(project,frozenset(scopes))))
    return out

class Authenticator:
    def __init__(self,cfg:Config):
        self.cfg=cfg; self.tokens=parse_tokens(cfg.token_file)
        self.secret=private_read(cfg.oauth_secret_file).decode().strip() if cfg.oauth_secret_file else None
        if cfg.oauth_introspection_url and not self.secret: raise ValueError('OAuth secret must not be empty')
        self.sem=asyncio.Semaphore(8)

    async def verify(self,token):
        if not token or len(token)>8192 or not TOKEN68.fullmatch(token): return None
        digest=hashlib.sha256(token.encode()).hexdigest()
        for expected,p in self.tokens:
            if hmac.compare_digest(digest,expected): return p
        if not self.cfg.oauth_introspection_url or self.sem.locked(): return None
        # RFC 7662: trusted operator's authorization server, not a caller URL.
        try:
            async with asyncio.timeout(OAUTH_TIMEOUT), self.sem:
                async with httpx.AsyncClient(timeout=OAUTH_TIMEOUT,follow_redirects=False,trust_env=False) as client:
                    async with client.stream('POST',self.cfg.oauth_introspection_url,auth=(self.cfg.oauth_client_id,self.secret),data={'token':token,'token_type_hint':'access_token'},headers={'Accept':'application/json','Accept-Encoding':'identity'}) as response:
                        if response.status_code!=200 or response.headers.get('content-encoding','identity').lower()!='identity': return None
                        body=bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body)+len(chunk)>OAUTH_RESPONSE_LIMIT: return None
                            body.extend(chunk)
            v=json.loads(body.decode('utf-8'),object_pairs_hook=_unique_object,parse_constant=_reject_constant)
            if not isinstance(v,dict) or v.get('active') is not True or v.get('iss')!=self.cfg.oauth_issuer: return None
            aud=v.get('aud')
            if isinstance(aud,str): aud=[aud]
            if not isinstance(aud,list) or any(not isinstance(a,str) for a in aud) or self.cfg.public_url not in aud: return None
            exp,sub,scopes=v.get('exp'),v.get('sub'),v.get('scope','')
            if type(exp) not in (int,float) or not math.isfinite(exp) or exp<=time.time() or not isinstance(sub,str) or not sub: return None
            if not isinstance(scopes,str) or (scopes and not OAUTH_SCOPE.fullmatch(scopes)): return None
            # Project derives from issuer + subject; no caller-supplied workspace selector.
            project='oauth-'+hashlib.sha256((self.cfg.oauth_issuer+'\0'+sub).encode()).hexdigest()[:48]
            return Principal(project,frozenset(scopes.split())&SCOPES)
        except (httpx.HTTPError,ValueError,TypeError,TimeoutError,OverflowError,RecursionError):
            return None

class Guard:
    """Outer ASGI auth, origin, size and request concurrency boundary."""
    def __init__(self,app,cfg,auth):
        self.app=app; self.cfg=cfg; self.auth=auth; self.limit=asyncio.Semaphore(cfg.max_concurrent*4)
        self.origins={https_origin(origin) for origin in cfg.allowed_origins}
        self.public_host=None
        if cfg.public_url:
            self.public_host=authority(https_url(cfg.public_url).netloc)
            self.origins.add(https_origin(cfg.public_url))
        self.local_hosts={'localhost','127.0.0.1','[::1]'}

    def accepts_host(self,raw,server,scheme):
        try: host,port=authority(raw)
        except ValueError: return False
        if host in self.local_hosts and port in (None,self.cfg.port): return True
        if self.public_host:
            public_host,public_port=self.public_host
            if host==public_host and (port or 443)==(public_port or 443): return True
        elif port in (None,443) and QUICK_TUNNEL.fullmatch(host):
            # The Quick Tunnel assigns its public name after backend startup.
            return True
        # ASGI server is the listener address, not Host or proxy headers.
        if server and server[0]:
            server_host=server[0]
            if ':' in server_host and not server_host.startswith('['): server_host=f'[{server_host}]'
            try: server_host,_=authority(server_host)
            except ValueError: return False
            default_port=443 if scheme=='https' else 80
            return host==server_host and (port or default_port)==(server[1] or default_port)
        return False

    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan': return await self.app(scope,receive,send)
        if scope['type']=='websocket':
            return await send({'type':'websocket.close','code':1008})
        if scope['type']!='http': return
        from starlette.responses import JSONResponse
        path=scope['path']; method=scope['method']
        if path=='/mcp':
            original_send=send
            async def send(message):
                if message['type']=='http.response.start':
                    headers=[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'cache-control']
                    message={**message,'headers':[*headers,(b'cache-control',b'no-store')]}
                await original_send(message)
        async def reject(code,msg,headers=None):
            await JSONResponse({'error':msg},status_code=code,headers=headers)(scope,receive,send)
        hs={}
        for key,value in scope['headers']:
            key=key.lower()
            if key not in SINGLETON_HEADERS: continue
            if key in hs: return await reject(400,'duplicate security-sensitive header')
            hs[key]=value.decode('latin1')
        if not self.accepts_host(hs.get(b'host',''),scope.get('server'),scope.get('scheme')):
            return await reject(421,'host denied')
        if b'origin' in hs and hs[b'origin'] not in self.origins:
            return await reject(403,'origin denied')
        # The SDK and public routes do not handle credentials. Pass only the principal.
        scope={**scope,'headers':[(k,v) for k,v in scope['headers'] if k.lower()!=b'authorization']}
        if path in PUBLIC_ROUTES:
            if method not in ('GET','HEAD'): return await reject(405,'method denied')
            context=current.set(None)
            try: return await self.app(scope,receive,send)
            finally: current.reset(context)
        if path!='/mcp': return await reject(404,'not found')
        if method not in ('POST','GET','DELETE'): return await reject(405,'method denied')
        if self.limit.locked(): return await reject(429,'server busy')
        async with self.limit:
            if self.cfg.auth_required:
                header=hs.pop(b'authorization','')
                match=BEARER.fullmatch(header) if len(header)<=8200 else None
                p=await self.auth.verify(match[1]) if match else None
            else:
                p=PUBLIC_DEMO
            if p is None:
                challenge='Bearer'
                if self.cfg.oauth_issuer: challenge+=f' resource_metadata="{self.cfg.public_url.removesuffix("/mcp")}/.well-known/oauth-protected-resource/mcp"'
                return await reject(401,'authentication required',{'WWW-Authenticate':challenge})
            # Buffer and cap request, including chunked uploads; SDK receives identical bytes.
            if method=='POST':
                if hs.get(b'content-type','').split(';')[0].strip().lower()!='application/json':
                    return await reject(415,'application/json required')
                length=hs.get(b'content-length')
                if length is not None:
                    if b'transfer-encoding' in hs or not re.fullmatch(r'[0-9]{1,20}',length):
                        return await reject(400,'invalid content length')
                    length=int(length)
                    if length>self.cfg.max_request_bytes: return await reject(413,'request too large')
                elif hs.get(b'transfer-encoding','chunked').lower()!='chunked':
                    return await reject(400,'invalid transfer encoding')
                body=bytearray()
                try:
                    async with asyncio.timeout(15):
                        while True:
                            m=await receive()
                            if m['type']=='http.disconnect': return
                            chunk=m.get('body',b''); size=len(body)+len(chunk)
                            if size>self.cfg.max_request_bytes: return await reject(413,'request too large')
                            if length is not None and size>length: return await reject(400,'content length mismatch')
                            body.extend(chunk)
                            if not m.get('more_body'): break
                except TimeoutError: return await reject(408,'request timeout')
                if length is not None and len(body)!=length: return await reject(400,'content length mismatch')
                original=receive; sent=False
                async def replay():
                    nonlocal sent
                    if not sent:
                        sent=True; return {'type':'http.request','body':bytes(body),'more_body':False}
                    return await original()
                receive=replay
            token=current.set(p)
            try: return await self.app(scope,receive,send)
            finally: current.reset(token)
