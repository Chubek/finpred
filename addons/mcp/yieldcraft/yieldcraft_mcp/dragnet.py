from __future__ import annotations
import asyncio, logging, os, stat
from pathlib import Path
from .artifacts import safe_json,canonical_json
from .models import Search, now, utc
from .processes import DRAGNET_AUTH, OPENAI_BASE_URL, EngineError
log=logging.getLogger(__name__)
OPERATOR_PROJECT='default'
CONFIG_MAX=262144

def json_object(raw):
    try: value=safe_json(raw)
    except (ValueError,RecursionError): raise EngineError('invalid Dragnet JSON') from None
    if not isinstance(value,dict): raise EngineError('invalid Dragnet JSON')
    return value

def write_private(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f: f.write(raw)

async def frames(reader,maximum=2_000_000):
    """Recognize framing only. FinPRED verifies the actual digest and chronology."""
    data=bytearray(); pages=0
    while line:=await reader.readline():
        if not line.endswith(b'\n') or len(data)+len(line)>maximum: raise EngineError('invalid or oversized Dragnet frame')
        fmt=(v:=json_object(line)).get('format')
        if not data:
            if fmt!='dragnet.batch@1': raise EngineError('missing Dragnet header')
        elif fmt=='dragnet.page@1':
            pages+=1
            if pages>80: raise EngineError('too many Dragnet pages')
        elif fmt=='dragnet.batch-end@1':
            if type(v.get('pages')) is not int or v['pages']!=pages: raise EngineError('Dragnet page count mismatch')
            data.extend(line); yield bytes(data); data.clear(); pages=0; continue
        else: raise EngineError('invalid Dragnet framing')
        data.extend(line)
    if data: raise EngineError('truncated Dragnet frame')

class Dragnet:
    def __init__(self,runner,store,cfg):
        self.runner=runner; self.store=store; self.cfg=cfg; self.task=None; self.proc=None; self.owner=None; self.last=None; self.error=None; self.cycles=0; self.lock=asyncio.Lock()
    def grants(self,config):
        if config.get('transport')=='offline': return []
        if config.get('transport')!='https' or not self.cfg.enable_live: raise PermissionError('live acquisition disabled by operator')
        provider={'google':'www.google.com','bing':'www.bing.com'}.get(config.get('provider'))
        if provider not in self.cfg.allowed_hosts: raise PermissionError('provider is not granted')
        if config.get('extraction')=='offer-csv-v1' and not self.cfg.offer_hosts: raise PermissionError('no trusted offer providers')
        args=[]
        for host in self.cfg.allowed_hosts: args+=['--allow-host',host]
        if config.get('extraction')=='offer-csv-v1':
            for host in self.cfg.offer_hosts: args+=['--allow-offer-host',host]
        if config.get('extraction')=='gpt':
            if not self.cfg.allow_llm or 'api.openai.com' not in self.cfg.allowed_hosts: raise PermissionError('LLM egress disabled')
            args+=['--allow-llm']
        return args
    def credentials(self,config):
        if config.get('extraction')!='gpt': return None
        e={k:os.environ[k] for k in ('OPENAI_MODEL',) if k in os.environ}
        if config.get('transport')=='https':
            e.update({k:os.environ[k] for k in DRAGNET_AUTH if k in os.environ})
            # Process env takes precedence over native dotenv/inline settings.
            # A search-host grant must not also become an LLM-endpoint grant.
            e['OPENAI_BASE_URL']=OPENAI_BASE_URL
        return e
    async def verify(self,project,path,cutoff):
        utc(cutoff)
        return (await self.runner.run(project,'finpred','dragnet-inspect',path,cutoff)).decode('utf-8')
    async def admit(self,project,data):
        header=json_object(data.partition(b'\n')[0]); requested=header.get('requested_as_of'); cutoff=now() if requested=='now' else utc(requested)
        with self.runner.workspace(project) as folder:
            path=Path(folder)/'batch.jsonl'; path.write_bytes(data)
            inspect=await self.verify(project,path,cutoff)
        return {'artifact_sha256':self.store.put(project,data),'verified_cutoff':cutoff,'inspection':inspect,'published':False}
    def operator_config(self,project):
        if project!=OPERATOR_PROJECT: raise PermissionError('operator Dragnet configuration belongs to another project')
        path=self.cfg.daemon_config
        if path is None: raise ValueError('operator daemon_config not configured')
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as f:
                info=os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode): raise ValueError('invalid operator Dragnet configuration')
                raw=f.read(CONFIG_MAX+1)
        except OSError: raise ValueError('operator daemon_config unavailable') from None
        if len(raw)>CONFIG_MAX: raise ValueError('daemon configuration too large')
        v=json_object(raw)
        # Preserve native restrictions on the source before making a 0600 copy.
        if 'environment' in v and (info.st_uid!=os.geteuid() or info.st_mode&0o077):
            raise ValueError('inline environment requires private service-owned configuration')
        self.grants(v)
        return raw,v
    def config_snapshot(self,folder,raw,config):
        path=Path(folder)/'Dragnet.json'
        if config.get('extraction')=='gpt' and 'env_file' not in config:
            # Do not allow native's implicit checkout-relative .env fallback.
            empty=path.with_name('empty.env')
            write_private(empty,b'')
            raw=canonical_json({**config,'env_file':str(empty)})
            if len(raw)>CONFIG_MAX: raise ValueError('daemon configuration too large')
        write_private(path,raw)
        return path
    async def search(self,project,request:Search):
        config=request.config(); args=self.grants(config)
        with self.runner.workspace(project) as folder:
            path=self.config_snapshot(folder,canonical_json(config),config)
            data=await self.runner.run(project,'dragnet','--handoff','--config',path,*args,extra=self.credentials(config),cwd=folder)
        return await self.admit(project,data)
    async def one_offline(self,project):
        raw,v=self.operator_config(project)
        if v.get('transport')!='offline': raise PermissionError('operator config is not offline')
        with self.runner.workspace(project) as folder:
            path=self.config_snapshot(folder,raw,v)
            data=await self.runner.run(project,'dragnet','--handoff','--config',path,extra=self.credentials(v),cwd=self.cfg.finpred_root)
        return await self.admit(project,data)
    async def _loop(self,project,raw,config):
        try:
            with self.runner.workspace(project) as folder:
                path=self.config_snapshot(folder,raw,config)
                proc=await self.runner.spawn(project,'dragnet',['--daemon','--handoff','--config',path,*self.grants(config)],self.credentials(config),self.cfg.finpred_root)
                self.proc=proc
                async def drain():
                    while await proc.stderr.read(65536): pass
                stderr=asyncio.create_task(drain())
                try:
                    async for data in frames(proc.stdout,min(2_000_000,self.cfg.max_artifact_bytes)):
                        self.last=await self.admit(project,data); self.cycles+=1
                    if await proc.wait(): raise EngineError('Dragnet exited unsuccessfully')
                finally:
                    try: await self.runner.stop(proc)
                    finally:
                        stderr.cancel(); await asyncio.gather(stderr,return_exceptions=True)
                        self.proc=None
        except asyncio.CancelledError: raise
        except Exception:
            self.error='acquisition_failed'; log.warning('Dragnet acquisition failed')
    async def start(self,project):
        async with self.lock:
            if project!=OPERATOR_PROJECT: raise PermissionError('operator Dragnet configuration belongs to another project')
            if self.task and not self.task.done():
                return self.status(project)
            raw,c=self.operator_config(project); self.owner=project; self.last=None; self.error=None; self.cycles=0
            self.task=asyncio.create_task(self._loop(project,raw,c)); return self.status(project)
    async def stop(self,project,shutdown=False):
        async with self.lock:
            if project!=OPERATOR_PROJECT and not shutdown: raise PermissionError('operator Dragnet configuration belongs to another project')
            if self.task and not self.task.done(): self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
            self.task=None; return self.status(project)
    def status(self,project):
        if project!=OPERATOR_PROJECT: return {'running':False,'owned_by_current_project':False}
        return {'running':bool(self.task and not self.task.done()),'owned_by_current_project':True,'cycles':self.cycles,'last_capture':self.last,'error':self.error}
