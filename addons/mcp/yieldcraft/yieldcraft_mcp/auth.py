from __future__ import annotations
import hashlib, hmac, json, re, stat, time, asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .config import Config

SCOPES=frozenset({'research:read','artifact:write','dragnet:search','yieldcraft:analyze','yieldcraft:recommend','ottomat:generate','ottomat:simulate','daemon:manage','admin'})
PROJECT=re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
@dataclass(frozen=True)
class Principal:
    project: str
    scopes: frozenset[str]
    def require(self, *scopes):
        if not set(scopes)<=self.scopes: raise PermissionError('insufficient scope')
current: ContextVar[Principal|None]=ContextVar('principal',default=None)
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

def parse_tokens(path):
    rows=json.loads(private_read(path))
    if not isinstance(rows,list) or not 1<=len(rows)<=128: raise ValueError('invalid token list')
    out=[]
    for row in rows:
        if set(row)!={'sha256','project','scopes'} or not re.fullmatch('[0-9a-f]{64}',row['sha256']) or not PROJECT.fullmatch(row['project']) or not isinstance(row['scopes'],list) or not set(row['scopes'])<=SCOPES: raise ValueError('invalid token record')
        if any(hmac.compare_digest(row['sha256'],x[0]) for x in out): raise ValueError('duplicate token')
        out.append((row['sha256'],Principal(row['project'],frozenset(row['scopes']))))
    return out

class Authenticator:
    def __init__(self,cfg:Config):
        self.cfg=cfg; self.tokens=parse_tokens(cfg.token_file)
        self.secret=private_read(cfg.oauth_secret_file).decode().strip() if cfg.oauth_secret_file else None
        self.sem=asyncio.Semaphore(8)
    async def verify(self,token):
        if not token or len(token)>8192 or any(ord(c)<33 or ord(c)>126 for c in token): return None
        digest=hashlib.sha256(token.encode()).hexdigest()
        for expected,p in self.tokens:
            if hmac.compare_digest(digest,expected): return p
        if not self.cfg.oauth_introspection_url: return None
        # RFC 7662: trusted operator's authorization server, not a caller URL.
        try:
            async with self.sem, httpx.AsyncClient(timeout=5,follow_redirects=False,trust_env=False) as client:
                async with client.stream('POST',self.cfg.oauth_introspection_url,auth=(self.cfg.oauth_client_id,self.secret),data={'token':token,'token_type_hint':'access_token'},headers={'Accept':'application/json'}) as r:
                    if r.status_code!=200: return None
                    body=bytearray()
                    async for chunk in r.aiter_bytes():
                        body.extend(chunk)
                        if len(body)>65536: return None
            v=json.loads(body); aud=v.get('aud',[]); aud=[aud] if isinstance(aud,str) else aud
            if v.get('active') is not True or v.get('iss')!=self.cfg.oauth_issuer or not isinstance(aud,list) or self.cfg.public_url not in aud or not isinstance(v.get('exp'),(int,float)) or v['exp']<=time.time() or not isinstance(v.get('sub'),str) or not v['sub']: return None
            # Project derives from issuer + subject; no caller-supplied workspace selector.
            project='oauth-'+hashlib.sha256((v['iss']+'\0'+v['sub']).encode()).hexdigest()[:48]
            return Principal(project,frozenset(v.get('scope','').split())&SCOPES)
        except (httpx.HTTPError,ValueError,TypeError,AttributeError): return None

class Guard:
    """Outer ASGI auth, origin, size and request concurrency boundary."""
    def __init__(self,app,cfg,auth):
        self.app=app; self.cfg=cfg; self.auth=auth; self.limit=asyncio.Semaphore(cfg.max_concurrent*4)
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        from starlette.responses import JSONResponse
        async def reject(code,msg,headers=None): await JSONResponse({'error':msg},status_code=code,headers=headers)(scope,receive,send)
        path=scope['path']; method=scope['method']; pairs=[(k.decode().lower(),v.decode('latin1')) for k,v in scope['headers']]
        for name in ('authorization','origin','host','content-length','content-type'):
            if sum(k==name for k,v in pairs)>1: return await reject(400,'duplicate security-sensitive header')
        hs=dict(pairs)
        # No caller-controlled CORS; reject browser origins unless explicitly trusted.
        origin=hs.get('origin'); allowed=set(self.cfg.allowed_origins)
        if self.cfg.public_url:
            u=urlsplit(self.cfg.public_url); allowed.add(f'{u.scheme}://{u.netloc}')
        if origin and origin not in allowed: return await reject(403,'origin denied')
        if path in ('/healthz','/readyz','/version','/editor','/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-protected-resource'):
            if method not in ('GET','HEAD'): return await reject(405,'method denied')
            return await self.app(scope,receive,send)
        if path!='/mcp': return await reject(404,'not found')
        if method not in ('POST','GET','DELETE'): return await reject(405,'method denied')
        header=hs.get('authorization',''); p=await self.auth.verify(header[7:]) if header.startswith('Bearer ') else None
        if p is None:
            challenge='Bearer'
            if self.cfg.oauth_issuer: challenge+=f' resource_metadata="{self.cfg.public_url.removesuffix("/mcp")}/.well-known/oauth-protected-resource/mcp"'
            return await reject(401,'authentication required',{'WWW-Authenticate':challenge})
        if self.limit.locked(): return await reject(429,'server busy')
        async with self.limit:
            # Buffer and cap request, including chunked uploads; SDK receives identical bytes.
            if method=='POST':
                if not hs.get('content-type','').split(';')[0].strip().lower()=='application/json': return await reject(415,'application/json required')
                try:
                    if int(hs.get('content-length','0'))>self.cfg.max_request_bytes: return await reject(413,'request too large')
                except ValueError: return await reject(400,'invalid content length')
                body=bytearray()
                try:
                    async with asyncio.timeout(15):
                        while True:
                            m=await receive()
                            if m['type']=='http.disconnect': return
                            body.extend(m.get('body',b''))
                            if len(body)>self.cfg.max_request_bytes: return await reject(413,'request too large')
                            if not m.get('more_body'): break
                except TimeoutError: return await reject(408,'request timeout')
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
