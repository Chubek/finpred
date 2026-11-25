from __future__ import annotations
import asyncio, os, re, signal, tempfile
from .config import Config
from .artifacts import Store

class EngineError(RuntimeError): pass

DRAGNET_AUTH=('OPENAI_API_KEY','OPENAI_ACCESS_TOKEN','OPENAI_ORG_ID','OPENAI_PROJECT_ID')
OPENAI_BASE_URL='https://api.openai.com/v1'
TOOL_ENV={
    'yieldcraft':{'FINPRED_OFFERS'},
    'finpred':{'FINPRED_STRATEGY','FINPRED_SCALAR_FIRST','FINPRED_SCALAR_SECOND','FINPRED_SCALAR_BUDGET'},
    'dragnet':{*DRAGNET_AUTH,'OPENAI_MODEL','OPENAI_BASE_URL'},
    'ottomat-bridge':{'YC_BRIDGE_SHA256','YC_COMPILER_ID','YC_TASK','YC_SOURCE',
                      'YC_CUTOFF','YC_ROOT_COUNT','YC_EXPECTED','YC_ARCHIVE'},
}
BRIDGE_ROOT_ENV=re.compile(r'YC_(?:NAME|FILE)_(?:[0-9]|1[0-5])\Z')

class Runner:
    def __init__(self,cfg:Config,store:Store): self.cfg=cfg; self.store=store; self.sem=asyncio.Semaphore(cfg.max_concurrent)
    def env(self,project,extra=None,*,tool=None):
        p=self.store.project(project)
        e={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','HOME':str(p),'TMPDIR':str(p/'tmp'),'FINPRED_HOME':str(p/'runs'),'FINPRED_CUBE_HOME':str(p/'cube'),'FINPRED_FORECAST_HOME':str(p/'forecast')}
        if extra:
            if any(k not in TOOL_ENV.get(tool,()) and not (tool=='ottomat-bridge' and BRIDGE_ROOT_ENV.fullmatch(k))
                   for k in extra): raise ValueError('invalid internal environment override')
            if 'OPENAI_BASE_URL' in extra and extra['OPENAI_BASE_URL']!=OPENAI_BASE_URL:
                raise ValueError('invalid Dragnet endpoint override')
            e.update(extra)
        return e
    def executable(self,tool):
        if tool not in ('finpred','yieldcraft','yieldcraft-demand','yieldcraft-inventory','dragnet','ottomat-bridge'): raise ValueError('unregistered executable')
        path=(self.cfg.finpred_root/'build/dev/finpred-ottomat-mcp' if tool=='ottomat-bridge' else self.cfg.finpred_root/'bin'/tool)
        if not path.is_file() or not os.access(path,os.X_OK): raise EngineError(f'{tool} unavailable; build FinPRED first')
        return str(path)
    async def spawn(self,project,tool,args,extra=None,cwd=None):
        executable=self.executable(tool)
        env=self.env(project,extra,tool=tool)
        mode=args[0] if args else None
        if tool=='yieldcraft' or (tool=='finpred' and mode in ('replay','explain','evidence','poindexter')):
            self.store.check_native_home(project,'runs')
        elif tool=='finpred' and mode in ('cube','forecast'):
            self.store.check_native_home(project,mode)
        try:
            return await asyncio.create_subprocess_exec(executable,*map(str,args),cwd=cwd or self.cfg.finpred_root,env=env,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,umask=0o077,limit=min(self.cfg.max_artifact_bytes,2_000_000)+1)
        except (OSError,ValueError):
            raise EngineError(f'{tool} could not start') from None
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
                out,_,code=await asyncio.wait_for(asyncio.gather(*tasks),self.cfg.timeout)
                if code: raise EngineError(f'{tool} rejected request (exit {code}); validate input')
                return out
            except TimeoutError:
                await self.stop(proc)
                raise EngineError('engine timeout') from None
            except BaseException:
                await self.stop(proc)
                raise
            finally:
                for t in tasks:
                    if not t.done(): t.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    def workspace(self,project): return tempfile.TemporaryDirectory(prefix='job-',dir=self.store.project(project)/'tmp')
