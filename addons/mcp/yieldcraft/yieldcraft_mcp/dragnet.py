from __future__ import annotations
import asyncio, json, logging, os, stat
from pathlib import Path
from .artifacts import safe_json,canonical_json
from .models import Search, now, utc
from .processes import EngineError
log=logging.getLogger(__name__)

async def frames(reader,maximum=2_000_000):
    """Recognize framing only. FinPRED verifies the actual digest and chronology."""
    data=bytearray(); pages=0
    while line:=await reader.readline():
        if not line.endswith(b'\n') or len(data)+len(line)>maximum: raise EngineError('invalid or oversized Dragnet frame')
        v=safe_json(line); fmt=v.get('format')
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
        # Operator config may use a private env_file; no client credential injection.
        if config.get('extraction')!='gpt': return None
        return {k:os.environ[k] for k in ('OPENAI_API_KEY','OPENAI_ACCESS_TOKEN','OPENAI_MODEL','OPENAI_ORG_ID','OPENAI_PROJECT_ID') if k in os.environ}
    async def verify(self,project,path,cutoff):
        utc(cutoff)
        return (await self.runner.run(project,'finpred','dragnet-inspect',path,cutoff)).decode('utf-8')
    async def admit(self,project,data):
        header=safe_json(data.splitlines()[0]); requested=header.get('requested_as_of'); cutoff=now() if requested=='now' else utc(requested)
        with self.runner.workspace(project) as folder:
            path=Path(folder)/'batch.jsonl'; path.write_bytes(data)
            inspect=await self.verify(project,path,cutoff)
        return {'artifact_sha256':self.store.put(project,data),'verified_cutoff':cutoff,'inspection':inspect,'published':False}
    def operator_config(self):
        path=self.cfg.daemon_config
        if path is None or not path.is_file(): raise ValueError('operator daemon_config not configured')
        if path.stat().st_size>262144: raise ValueError('daemon configuration too large')
        v=safe_json(path.read_bytes()); self.grants(v); return path,v
    async def search(self,project,request:Search):
        config=request.config(); args=self.grants(config)
        with self.runner.workspace(project) as folder:
            path=Path(folder)/'Dragnet.json'; path.write_bytes(canonical_json(config))
            data=await self.runner.run(project,'dragnet','--handoff','--config',path,*args,extra=self.credentials(config),cwd=folder)
        return await self.admit(project,data)
    async def one_offline(self,project):
        path,v=self.operator_config()
        if v.get('transport')!='offline': raise PermissionError('operator config is not offline')
        data=await self.runner.run(project,'dragnet','--handoff','--config',path,cwd=self.cfg.finpred_root)
        return await self.admit(project,data)
    async def _loop(self,project,path,config):
        stderr=None
        try:
            self.proc=await self.runner.spawn(project,'dragnet',['--daemon','--handoff','--config',path,*self.grants(config)],self.credentials(config),self.cfg.finpred_root)
            async def drain():
                while await self.proc.stderr.read(65536): pass
            stderr=asyncio.create_task(drain())
            async for data in frames(self.proc.stdout,min(2_000_000,self.cfg.max_artifact_bytes)):
                self.last=await self.admit(project,data); self.cycles+=1
            code=await self.proc.wait()
            if code: raise EngineError(f'Dragnet exited {code}')
        except asyncio.CancelledError: raise
        except Exception as e:
            self.error=type(e).__name__; log.warning('Dragnet stopped: %s',self.error)
        finally:
            if self.proc: await self.runner.stop(self.proc)
            if stderr: stderr.cancel(); await asyncio.gather(stderr,return_exceptions=True)
            self.proc=None
    async def start(self,project):
        async with self.lock:
            if self.task and not self.task.done():
                if self.owner!=project: raise PermissionError('daemon belongs to another project')
                return self.status(project)
            path,c=self.operator_config(); self.owner=project; self.last=None; self.error=None; self.cycles=0
            self.task=asyncio.create_task(self._loop(project,path,c)); return self.status(project)
    async def stop(self,project,shutdown=False):
        async with self.lock:
            if self.owner not in (None,project) and not shutdown: raise PermissionError('daemon belongs to another project')
            if self.task and not self.task.done(): self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
            self.task=None; return self.status(project)
    def status(self,project):
        if self.owner not in (None,project): return {'running':bool(self.task and not self.task.done()),'owned_by_current_project':False}
        return {'running':bool(self.task and not self.task.done()),'owned_by_current_project':True,'cycles':self.cycles,'last_capture':self.last,'error':self.error}
