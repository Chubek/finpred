from __future__ import annotations
from pathlib import Path
import re, hashlib, json
from typing import Literal
from pydantic import Field
from .models import Strict
from .engine import MARKET
from .processes import EngineError

WORD=r'[a-z][a-z0-9_-]{0,31}'
REF=rf'{WORD}(?:\.{WORD})?'
CONTRACT=rf'{WORD}(?:\.{WORD})+@[1-9][0-9]*'
HANDLER=rf'{WORD}(?:\.{WORD})*@[1-9][0-9]*'
SCALAR={'scalar-spread':'scalar-spread.ottomat','scalar-select':'scalar-select.ottomat','scalar-midpoint':'scalar-midpoint.ottomat'}
BUILTINS={**MARKET,**SCALAR,'contribution':'contribution.ottomat'}
BLAKE3=re.compile(rb'blake3:[0-9a-f]{64}\Z')
# These are the native status codes from ottomat.financial/financial_run and
# automat.financial_graph/financial_archive. Do not forward arbitrary stdout
# as diagnostic text, including for native failures reported with exit 0.
LOWERING=frozenset(b'ok size compiler_identity syntax denied port duplicate_id unknown_handler duplicate_import node undeclared_import binding emit output version budget graph_shape descriptor_mismatch unknown_reference cycle edge_type'.split())
GRAPH_STATUS=LOWERING|frozenset(b'lowering archive_size archive_digest archive_format graph_mismatch input replay_mismatch pin_mismatch invalid_request invalid_output handler_failure'.split())

def native_digests(*fields):
    if any(not BLAKE3.fullmatch(field) for field in fields): raise EngineError('invalid native Ottomat response')
    return tuple(field.decode('ascii') for field in fields)

def match(pattern,value):
    if not re.fullmatch(pattern,value): raise ValueError('invalid Ottomat token')
    return value
class Port(Strict):
    name:str; contract:str; unit:str; currency:str='none'; required:Literal['required','optional']='required'; max_bytes:int=Field(ge=1,le=2_000_000)
    def line(self,kind):
        for val,pat in [(self.name,WORD),(self.contract,CONTRACT),(self.unit,WORD),(self.currency,r'(?:[A-Z]{3}|none)')]: match(pat,val)
        return f'{kind} {self.name} {self.contract} {self.unit} {self.currency} {self.required} {self.max_bytes}'
class Node(Strict):
    name:str; handler:str; bindings:dict[str,str]=Field(min_length=1,max_length=16)
    def line(self):
        match(WORD,self.name); match(HANDLER,self.handler)
        return 'let '+self.name+' = '+self.handler+' '+' '.join(match(WORD,k)+'='+match(REF,v) for k,v in self.bindings.items())
class GraphDraft(Strict):
    inputs:list[Port]=Field(min_length=1,max_length=16)
    nodes:list[Node]=Field(min_length=1,max_length=32)
    outputs:list[Port]=Field(min_length=1,max_length=16)
    emit:dict[str,str]=Field(min_length=1,max_length=16)
    def source(self):
        inputs=[x.name for x in self.inputs]; nodes=[x.name for x in self.nodes]; outputs=[x.name for x in self.outputs]
        if len(set(inputs+nodes))!=len(inputs+nodes) or len(set(outputs))!=len(outputs) or set(outputs)!=set(self.emit): raise ValueError('duplicate or missing declarations')
        graph={n.name:set() for n in self.nodes}
        def check(ref):
            match(REF,ref); parts=ref.split('.')
            if len(parts)==1 and parts[0] not in inputs or len(parts)==2 and parts[0] not in nodes: raise ValueError('unresolved reference')
            return parts[0] if len(parts)==2 else None
        for n in self.nodes:
            graph[n.name]={x for v in n.bindings.values() if (x:=check(v)) is not None}
        for v in self.emit.values(): check(v)
        remain=dict(graph); completed=set()
        while remain:
            ready=[k for k,v in remain.items() if v<=completed]
            if not ready: raise ValueError('cyclic graph')
            for k in ready: completed.add(k); del remain[k]
        lines=['ottomat 6','effect pure']+[p.line('input') for p in self.inputs]+['import '+h for h in dict.fromkeys(n.handler for n in self.nodes)]+[n.line() for n in self.nodes]+[p.line('output') for p in self.outputs]+['emit '+match(WORD,k)+' '+match(REF,self.emit[k]) for k in outputs]
        src='\n'.join(lines)+'\n'
        if len(src.encode())>4096: raise ValueError('draft exceeds native v6 source budget')
        return src

class Ottomat:
    def __init__(self,runner,store,cfg): self.runner=runner; self.store=store; self.cfg=cfg
    def catalog(self):
        return [{'profile':k,'file':v,'execution':'scalar' if k in SCALAR else 'yieldcraft','available':(self.cfg.finpred_root/'strategies'/v).is_file()} for k,v in BUILTINS.items()]
    def builtin(self,profile):
        if profile not in BUILTINS: raise ValueError('unknown built-in strategy')
        return (self.cfg.finpred_root/'strategies'/BUILTINS[profile]).read_bytes()
    def generate(self,project,profile=None,graph=None):
        if (profile is None)==(graph is None): raise ValueError('select profile or structured graph')
        raw=self.builtin(profile) if profile else graph.source().encode()
        d=self.store.put(project,raw)
        return {'artifact_sha256':d,'source':raw.decode(),'language':'ottomat','status':'known_builtin' if profile else 'draft_requires_native_lowering','native_validated':False,'published':False}
    def validate(self,raw):
        if len(raw)>8192: return {'status':'rejected','diagnostics':['source exceeds addon limit'],'native_validated':False}
        try: src=raw.decode('ascii')
        except UnicodeDecodeError: return {'status':'rejected','diagnostics':['source must be ASCII'],'native_validated':False}
        for k in BUILTINS:
            try:
                if raw==self.builtin(k): return {'status':'known_builtin','profile':k,'native_validated':False,'diagnostics':[]}
            except FileNotFoundError: pass
        lines=src.splitlines()
        if not lines or not re.fullmatch(r'(?:ottmat|ottomat) [1-6]',lines[0]): return {'status':'rejected','native_validated':False,'diagnostics':['invalid version header']}
        diagnostics=[]
        if lines[0].endswith(('3','4','5','6')):
            if not src.endswith('\n') or '\r' in src: diagnostics.append('LF termination required')
            for i,line in enumerate(lines,1):
                if not line or line.strip()!=line or '  ' in line or '\t' in line: diagnostics.append(f'line {i}: noncanonical whitespace')
        return {'status':'rejected' if diagnostics else 'draft_requires_native_lowering','native_validated':False,'diagnostics':diagnostics or ['No general native validation bridge is installed. Do not execute this draft.']}
    def bridge_env(self):
        exe=self.cfg.finpred_root/'build/dev/finpred-ottomat-mcp'
        manifest=exe.with_suffix('.json')
        if not exe.is_file() or not manifest.is_file(): raise ValueError('optional native Ottomat bridge not built')
        meta=json.loads(manifest.read_text()); digest=hashlib.sha256(exe.read_bytes()).hexdigest()
        if meta.get('bridge_sha256')!=digest or not re.fullmatch(r'sha256:[0-9a-f]{64}',meta.get('compiler_identity','')): raise ValueError('native bridge build identity mismatch')
        return {'YC_BRIDGE_SHA256':digest,'YC_COMPILER_ID':meta['compiler_identity']}
    async def native_validate(self,project,source):
        initial=self.validate(source.encode())
        if not source.startswith('ottomat 6\n') or initial['status']=='rejected': return initial
        if not (self.cfg.finpred_root/'build/dev/finpred-ottomat-mcp').is_file(): return initial
        env=self.bridge_env()
        with self.runner.workspace(project) as f:
            path=Path(f)/'strategy.ottomat'; path.write_bytes(source.encode()); env.update(YC_TASK='validate',YC_SOURCE=str(path))
            raw=await self.runner.run(project,'ottomat-bridge',extra=env)
        lines=raw.splitlines()
        fields=lines[0].split(b' ') if lines else []
        if len(fields)!=3 or fields[0] not in LOWERING or any(not re.fullmatch(rb'[0-9]{1,4}',n) for n in fields[1:]):
            raise EngineError('invalid native Ottomat response')
        status,line,col=fields
        ok=status==b'ok'
        if len(lines)!=(3 if ok else 1): raise EngineError('invalid native Ottomat response')
        graph,source_digest=native_digests(*lines[1:]) if ok else (None,None)
        return {'status':status.decode('ascii'),'line':int(line),'column':int(col),'native_validated':ok,'graph_digest':graph,'source_digest':source_digest,'bridge_sha256':env['YC_BRIDGE_SHA256']}
    async def execute_graph(self,project,source_id,roots,cutoff):
        from .models import utc
        utc(cutoff); source=self.store.read(project,source_id).decode('ascii'); validation=await self.native_validate(project,source)
        if validation.get('native_validated') is not True: raise ValueError('strategy did not pass native v6 lowering')
        if not 1<=len(roots)<=16: raise ValueError('invalid graph root count')
        env=self.bridge_env(); env.update(YC_TASK='capture',YC_CUTOFF=cutoff,YC_ROOT_COUNT=str(len(roots)))
        with self.runner.workspace(project) as f:
            path=Path(f)/'strategy.ottomat'; path.write_bytes(source.encode()); env['YC_SOURCE']=str(path)
            for i,(name,digest) in enumerate(sorted(roots.items())):
                match(WORD,name); path=Path(f)/f'root-{i}'; path.write_bytes(self.store.read(project,digest)); env[f'YC_NAME_{i}']=name; env[f'YC_FILE_{i}']=str(path)
            raw=await self.runner.run(project,'ottomat-bridge',extra=env)
        status,_,rest=raw.partition(b'\n')
        if status!=b'ok':
            if status in GRAPH_STATUS: raise EngineError('native graph rejected execution: '+status.decode('ascii'))
            raise EngineError('native graph rejected execution')
        fields=rest.split(b'\n',2)
        if len(fields)!=3 or not fields[2]: raise EngineError('invalid native Ottomat response')
        digest,graph=native_digests(*fields[:2])
        return {'archive_sha256':self.store.put(project,fields[2]),'native_archive_digest':digest,'graph_digest':graph,'bridge_sha256':env['YC_BRIDGE_SHA256'],'published':False}
    async def replay_graph(self,project,archive_id,expected):
        if not re.fullmatch(r'blake3:[0-9a-f]{64}',expected): raise ValueError('expected native archive digest required')
        env=self.bridge_env(); env.update(YC_TASK='replay',YC_EXPECTED=expected)
        with self.runner.workspace(project) as f:
            path=Path(f)/'archive'; path.write_bytes(self.store.read(project,archive_id)); env['YC_ARCHIVE']=str(path)
            raw=await self.runner.run(project,'ottomat-bridge',extra=env)
        lines=raw.splitlines()
        if not lines or lines[0] not in GRAPH_STATUS: raise EngineError('invalid native Ottomat response')
        ok=lines[0]==b'ok'
        if len(lines)!=(2 if ok else 1): raise EngineError('invalid native Ottomat response')
        graph=native_digests(lines[1])[0] if ok else None
        return {'status':lines[0].decode('ascii'),'replay_ok':ok,'graph_digest':graph,'published':False}
    async def scalar(self,project,profile,first,second,budget=16):
        if profile not in SCALAR or any(type(x) is not int or not 0<=x<=10**12 for x in (first,second)) or not 1<=budget<=16: raise ValueError('invalid scalar request')
        # Only built-in pure scalar files, not user-supplied source. Internal env allowlist.
        env={'FINPRED_STRATEGY':str(self.cfg.finpred_root/'strategies'/SCALAR[profile]),'FINPRED_SCALAR_FIRST':str(first),'FINPRED_SCALAR_SECOND':str(second),'FINPRED_SCALAR_BUDGET':str(budget)}
        raw=await self.runner.run(project,'finpred','run','--engine','scalar',extra=env)
        return {'result':raw.decode(),'artifact_sha256':self.store.put(project,raw),'native_executed':True,'published':False}
