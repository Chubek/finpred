from __future__ import annotations
from pathlib import Path
from .artifacts import identifier,safe_json,js_safe
from .models import Scenario,Valuation,utc
from .processes import EngineError

MARKET={'scenario':'yieldcraft.ottomat','value-p40':'value-p40.ottomat','balanced-p55':'balanced-p55.ottomat','premium-p75':'premium-p75.ottomat','lead-linear':'lead-linear.ottomat','lead-quadratic':'lead-quadratic.ottomat'}
MODELS={'naive','ema','drift','seasonal','holt','ensemble'}
class Engine:
    def __init__(self,runner,store,cfg): self.runner=runner; self.store=store; self.cfg=cfg
    def result(self,project,raw,kind='text',**kwargs):
        text=raw.decode('utf-8'); parsed=safe_json(raw) if kind=='json' else None; digest=self.store.put(project,raw)
        r={'artifact_sha256':digest,'published':False,'format':kind,**kwargs}
        if kind=='json': r['result']=js_safe(parsed) if len(raw)<=131072 else None
        elif len(raw)<=131072: r['result']=text
        else: r['result']=None
        if r['result'] is None: r['note']='Use artifact_read in bounded chunks; exact bytes are archived.'
        return r
    def inputs(self,project,folder,**values):
        files={}
        for name,digest in values.items():
            if digest is None: continue
            p=Path(folder)/name; p.write_bytes(self.store.read(project,identifier(digest))); files[name]=p
        return files
    async def scenario(self,project,scenario:Scenario):
        raw=scenario.csv(); d=self.store.put(project,raw)
        with self.runner.workspace(project) as f:
            p=Path(f)/'scenario.csv'; p.write_bytes(raw)
            # Native scenario digest helper also checks scenario parsing where supported; full pricing validates again.
            out=await self.runner.run(project,'yieldcraft-demand','scenario-digest',p)
        try: digest=identifier(out.rstrip(b'\n').decode('ascii'))
        except ValueError: raise EngineError('invalid native scenario digest') from None
        return {'artifact_sha256':d,'native_scenario_digest':digest,'validation':'native digest helper; full semantic validation occurs during pricing'}
    def valuation(self,project,valuation:Valuation): return {'artifact_sha256':self.store.put(project,valuation.csv())}
    async def recommend(self,project,scenario,valuation,*,demand=None,offers=None,capture=None,profile='scenario'):
        if sum(x is not None for x in (demand,offers,capture))!=1: raise ValueError('supply exactly one evidence type')
        identifier(scenario); identifier(valuation)
        if profile not in MARKET: raise ValueError('unknown market profile')
        if demand is not None and profile!='scenario': raise ValueError('market profile cannot apply to contribution')
        with self.runner.workspace(project) as f:
            files=self.inputs(project,f,scenario=scenario,valuation=valuation,demand=demand,offers=offers,capture=capture)
            args=['--scenario',files['scenario'],'--valuation',files['valuation']]; extra={}
            if demand is not None: args+=['--demand',files['demand']]
            else:
                args+=['--strategy',self.cfg.finpred_root/'strategies'/MARKET[profile]]
                if offers is not None: extra['FINPRED_OFFERS']=str(files['offers'])
                else: args+=['--capture',files['capture']]
            raw=await self.runner.run(project,'yieldcraft',*args,extra=extra)
        fields={}
        for line in raw.decode().splitlines():
            if '=' in line:
                k,v=line.split('=',1); fields[k]=v
        run=identifier(fields.get('run_id',''))
        if fields.get('published')!='false': raise EngineError('unexpected publication status')
        return self.result(project,raw,run_id=run,summary=fields,objective='contribution' if demand is not None else 'market_positioning',input_sha256={'scenario':scenario,'valuation':valuation,'demand':demand,'offers':offers,'capture':capture})
    async def estimate(self,project,scenario,exposures,panel=False):
        with self.runner.workspace(project) as f:
            files=self.inputs(project,f,scenario=scenario,exposures=exposures)
            args=[files['scenario'],files['exposures']]
            if panel:
                raw=await self.runner.run(project,'yieldcraft-demand','panel',*args)
                return self.result(project,raw,'json',decision_eligible=False)
            raw=await self.runner.run(project,'yieldcraft-demand','estimate',*args)
            evidence=await self.runner.run(project,'yieldcraft-demand','evidence',*args)
            v=safe_json(evidence); eid=v['id'];
            snap=Path(f)/'demand.csv'; snap.write_bytes(raw); ev=Path(f)/'evidence.json'; ev.write_bytes(evidence)
            await self.runner.run(project,'yieldcraft-demand','replay',*args,snap,ev,eid)
        return self.result(project,raw,'csv',evidence_sha256=self.store.put(project,evidence),native_evidence_id=eid,upstream_replayed=True)
    async def stress(self,project,scenario,valuation,demand,stress):
        with self.runner.workspace(project) as f:
            x=self.inputs(project,f,scenario=scenario,valuation=valuation,demand=demand,stress=stress)
            raw=await self.runner.run(project,'yieldcraft-inventory','stress-contribution',*[x[k] for k in ('scenario','valuation','demand','stress')])
        return self.result(project,raw,'json',uncertainty='operator_assumptions_not_calibrated_intervals')
    async def coupled(self,project,grid,export=False):
        with self.runner.workspace(project) as f:
            x=self.inputs(project,f,grid=grid)
            raw=await self.runner.run(project,'yieldcraft-inventory','compare-csv' if export else 'evaluate',x['grid'])
        return self.result(project,raw,'csv' if export else 'json',comparison='modeled_not_observed')
    async def cube(self,project,snapshots,cells,policies):
        with self.runner.workspace(project) as f:
            x=self.inputs(project,f,snapshots=snapshots,cells=cells,policies=policies)
            raw=await self.runner.run(project,'finpred','cube','evaluate',*[x[k] for k in ('snapshots','cells','policies')])
        return self.result(project,raw,'json')
    async def forecast(self,project,history,model,horizon,season=None,first_target=None):
        if model not in MODELS or type(horizon) is not int or not 1<=horizon<=365: raise ValueError('invalid model or horizon')
        if (model=='seasonal')!=(season is not None) or (season is not None and not 1<=season<=256): raise ValueError('season required only for seasonal model')
        if first_target is not None and not horizon<=first_target<=255: raise ValueError('invalid first target')
        with self.runner.workspace(project) as f:
            x=self.inputs(project,f,history=history); args=['price-predict' if first_target is None else 'price-backtest',model,horizon]
            if first_target is not None: args.append(first_target)
            args.append(x['history'])
            if season is not None: args.append(season)
            raw=await self.runner.run(project,'finpred',*args)
        return self.result(project,raw,'json')
    async def inspect(self,project,operation,run):
        if operation not in ('replay','explain','evidence','poindexter'): raise ValueError('invalid run operation')
        raw=await self.runner.run(project,'finpred',operation,identifier(run))
        return self.result(project,raw,'csv' if operation=='poindexter' else 'text',run_id=run)
