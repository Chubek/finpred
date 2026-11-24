from __future__ import annotations
import asyncio, os, signal, tempfile
from pathlib import Path
from .config import Config
from .artifacts import Store

class EngineError(RuntimeError): pass
class Runner:
    def __init__(self,cfg:Config,store:Store): self.cfg=cfg; self.store=store; self.sem=asyncio.Semaphore(cfg.max_concurrent)
    def env(self,project,extra=None):
        p=self.store.project(project)
        e={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','HOME':str(p),'TMPDIR':str(p/'tmp'),'FINPRED_HOME':str(p/'runs'),'FINPRED_CUBE_HOME':str(p/'cube'),'FINPRED_FORECAST_HOME':str(p/'forecast')}
        if extra:
            if not all(k.startswith('YC_') or k in {'FINPRED_OFFERS','FINPRED_SCENARIO','FINPRED_VALUATION','FINPRED_STRATEGY','FINPRED_SCALAR_FIRST','FINPRED_SCALAR_SECOND','FINPRED_SCALAR_BUDGET','OPENAI_API_KEY','OPENAI_ACCESS_TOKEN','OPENAI_MODEL','OPENAI_ORG_ID','OPENAI_PROJECT_ID'} for k in extra): raise ValueError('invalid internal environment override')
            e.update(extra)
        return e
    def executable(self,tool):
        if tool not in ('finpred','yieldcraft','yieldcraft-demand','yieldcraft-inventory','dragnet','ottomat-bridge'): raise ValueError('unregistered executable')
        path=(self.cfg.finpred_root/'build/dev/finpred-ottomat-mcp' if tool=='ottomat-bridge' else self.cfg.finpred_root/'bin'/tool)
        if not path.is_file() or not os.access(path,os.X_OK): raise EngineError(f'{tool} unavailable; build FinPRED first')
        return str(path)
    async def spawn(self,project,tool,args,extra=None,cwd=None):
        return await asyncio.create_subprocess_exec(self.executable(tool),*map(str,args),cwd=cwd or self.cfg.finpred_root,env=self.env(project,extra),stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,limit=min(self.cfg.max_artifact_bytes,2_000_000)+1)
    @staticmethod
    async def stop(proc):
        # kill the process group even if the immediate child has exited
        try: os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        try: await asyncio.wait_for(proc.wait(),2)
        except TimeoutError: pass
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        try: await asyncio.wait_for(proc.wait(),2)
        except TimeoutError:
            # Pipes can retain buffered data after child exit; close transport on abort.
            proc._transport.close()
    @staticmethod
    async def bounded(stream,limit):
        data=bytearray()
        while chunk:=await stream.read(65536):
            data.extend(chunk)
            if len(data)>limit: raise EngineError('subprocess output limit exceeded')
        return bytes(data)
    async def run(self,project,tool,*args,extra=None,cwd=None):
        if self.sem.locked(): raise EngineError('engine busy; retry later')
        async with self.sem:
            proc=await self.spawn(project,tool,args,extra,cwd)
            tasks=[asyncio.create_task(self.bounded(proc.stdout,self.cfg.max_artifact_bytes)),asyncio.create_task(self.bounded(proc.stderr,65536)),asyncio.create_task(proc.wait())]
            try:
                out,err,code=await asyncio.wait_for(asyncio.gather(*tasks),self.cfg.timeout)
                if code: raise EngineError(f'{tool} rejected request (exit {code}); see private operator logs or validate input')
                return out
            except TimeoutError: raise EngineError('engine timeout') from None
            except BaseException:
                await self.stop(proc)
                raise
            finally:
                if proc.returncode is None or any(not t.done() for t in tasks): await self.stop(proc)
                for t in tasks:
                    if not t.done(): t.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    def workspace(self,project): return tempfile.TemporaryDirectory(prefix='job-',dir=self.store.project(project)/'tmp')
