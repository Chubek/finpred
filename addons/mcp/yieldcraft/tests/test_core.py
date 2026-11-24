import asyncio, hashlib, json, os, re, subprocess
from pathlib import Path
import pytest
from pydantic import ValidationError
from yieldcraft_mcp.artifacts import js_safe,safe_json
from yieldcraft_mcp.auth import Authenticator,Guard,Principal,principal,current
from yieldcraft_mcp.models import Scenario,Valuation,Search
from yieldcraft_mcp.dragnet import frames
from yieldcraft_mcp.ottomat import GraphDraft
from yieldcraft_mcp.highlight import html
from yieldcraft_mcp.processes import EngineError
from conftest import TOKEN
import httpx
from starlette.responses import JSONResponse

@pytest.fixture
def scenario(): return Scenario(observed_at='2026-11-20T08:00:00Z',ingested_at='2026-11-20T09:00:00Z',decision_at='2026-11-20T10:00:00Z',arrival='2026-12-16',departure='2026-12-18',adults=2,max_rooms=2,min_properties=5)

def test_csv(scenario):
    assert scenario.csv().splitlines()[0]==b'scenario_id,observed_at,ingested_at,decision_at,arrival,departure,adults,children,max_rooms,min_properties,target_bps,curve,currency,max_age_days,search_budget'
    with pytest.raises(ValidationError): Scenario.model_validate({**scenario.model_dump(),'adults':9})
    with pytest.raises(ValidationError): Scenario.model_validate({**scenario.model_dump(),'departure':'2026-12-16'})
    with pytest.raises(ValidationError): Scenario.model_validate({**scenario.model_dump(),'decision_at':'2026-01-01T00:00:00Z'})
    with pytest.raises(ValidationError): Search(keywords=['a\n--option'])

def test_artifact_isolation(runtime):
    store=runtime.store; d=store.put('default',b'abc'); assert d==hashlib.sha256(b'abc').hexdigest();assert store.put('default',b'abc')==d
    assert store.read('default',d)==b'abc'
    with pytest.raises(FileNotFoundError): store.read('other',d)
    with pytest.raises(ValueError): store.read('default','../../etc/passwd')
    with pytest.raises(ValueError): store.put('default',b'x'*65537)
    (store.project('default')/'objects'/d).write_bytes(b'tamper')
    with pytest.raises(ValueError): store.read('default',d)
    assert js_safe({'value':10**18,'normal':5})=={'value':str(10**18),'normal':5}
    with pytest.raises(ValueError):safe_json(b'{"a":1,"a":2}')

@pytest.mark.asyncio
async def test_auth(config):
    a=Authenticator(config); assert (await a.verify(TOKEN)).project=='default'; assert await a.verify('wrong') is None
    with pytest.raises(PermissionError): principal('research:read')
    t=current.set(Principal('one',frozenset({'research:read'})))
    try:
        assert principal('research:read').project=='one'
        with pytest.raises(PermissionError):principal('daemon:manage')
    finally:current.reset(t)

@pytest.mark.asyncio
async def test_guard(config):
    async def endpoint(scope,receive,send):
        p=principal('research:read'); m=await receive(); await JSONResponse({'project':p.project,'bytes':len(m.get('body',b''))})(scope,receive,send)
    app=Guard(endpoint,config,Authenticator(config)); h={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
        assert (await c.post('/mcp',json={})).status_code==401
        assert (await c.post('/mcp',json={},headers={**h,'Origin':'https://evil.example'})).status_code==403
        assert (await c.post('/mcp',content=b'x'*65537,headers=h)).status_code==413
        assert (await c.post('/mcp',json={},headers=h)).json()=={'project':'default','bytes':2}
        assert (await c.get('/etc/passwd',headers=h)).status_code==404

@pytest.mark.asyncio
async def test_process_bounds(runtime,fake):
    fake('finpred','import os; print(os.environ.get("FINPRED_MODE", "clean"))')
    assert await runtime.runner.run('default','finpred')==b'clean\n'
    fake('finpred','print("x"*100000)')
    with pytest.raises(EngineError): await runtime.runner.run('default','finpred')
    fake('finpred','import time; time.sleep(30)')
    with pytest.raises(EngineError,match='timeout'): await runtime.runner.run('default','finpred')
    with pytest.raises(ValueError): runtime.runner.executable('/bin/sh')

@pytest.mark.asyncio
async def test_engine_dispatch(runtime,fake,scenario):
    store=runtime.store; project='default'; sc=store.put(project,scenario.csv()); val=store.put(project,b'valuation'); demand=store.put(project,b'demand')
    fake('yieldcraft','import sys,os; assert "--demand" in sys.argv; assert "FINPRED_OFFERS" not in os.environ; print("run_id="+"a"*64+"\\nrecommendation_minor=19000\\npublished=false")')
    r=await runtime.engine.recommend(project,sc,val,demand=demand);assert r['run_id']=='a'*64 and r['published'] is False
    with pytest.raises(ValueError):await runtime.engine.recommend(project,sc,val,demand=demand,offers=demand)
    fake('yieldcraft','print("run_id="+"a"*64+"\\npublished=true")')
    with pytest.raises(EngineError):await runtime.engine.recommend(project,sc,val,demand=demand)
    fake('finpred','import sys; assert sys.argv[1:4]==["price-backtest","ema","2"]; print(\'{"value":1000000000000000000}\')')
    result=await runtime.engine.forecast(project,demand,'ema',2,first_target=4);assert result['result']['value']=='1000000000000000000'

@pytest.mark.asyncio
async def test_frames():
    b=b'{"format":"dragnet.batch@1"}\n{"format":"dragnet.batch-end@1","pages":0}\n'
    r=asyncio.StreamReader();r.feed_data(b+b);r.feed_eof();assert [x async for x in frames(r)]==[b,b]
    r=asyncio.StreamReader();r.feed_data(b.splitlines(keepends=True)[0]);r.feed_eof()
    with pytest.raises(EngineError): [x async for x in frames(r)]

@pytest.mark.asyncio
async def test_dragnet_grants_and_native_admission(runtime,fake):
    with pytest.raises(PermissionError):await runtime.dragnet.search('default',Search(keywords=['test']))
    data=b'{"format":"dragnet.batch@1","requested_as_of":"2026-11-24T00:00:00Z"}\n{"format":"dragnet.batch-end@1","pages":0}\n'
    fake('finpred','import sys; assert sys.argv[1]=="dragnet-inspect"; print("native verified")')
    result=await runtime.dragnet.admit('default',data);assert runtime.store.read('default',result['artifact_sha256'])==data
    fake('finpred','raise SystemExit(2)')
    with pytest.raises(EngineError):await runtime.dragnet.admit('other',data)
    assert runtime.store.list('other')==[]


def graph():
    return {'inputs':[{'name':'scenario','contract':'finpred.scenario-csv@1','unit':'none','currency':'EUR','max_bytes':2048}], 'nodes':[{'name':'node','handler':'example.handler@1','bindings':{'scenario':'scenario'}}],'outputs':[{'name':'decision','contract':'pricing.decision@1','unit':'none','currency':'EUR','max_bytes':512}],'emit':{'decision':'node.decision'}}

def test_ottomat(runtime):
    g=GraphDraft.model_validate(graph());result=runtime.ottomat.generate('default',graph=g);assert result['native_validated'] is False and result['source'].startswith('ottomat 6\neffect pure\n')
    bad=graph();bad['nodes'][0]['bindings']['scenario']='node.decision'
    with pytest.raises(ValueError,match='cyclic'):GraphDraft.model_validate(bad).source()
    bad=graph();bad['nodes'][0]['handler']='example.handler@1\nimport evil@1'
    with pytest.raises(ValueError):GraphDraft.model_validate(bad).source()
    assert '&lt;script&gt;' in html('<script>') or '&lt;' in html('<script>')
    assert runtime.ottomat.validate(b'ottomat 6\n effect pure\n')['status']=='rejected'


def test_deploy_dry_run():
    here=Path(__file__).resolve().parents[1];cmd=[str(here/'deploy.sh'),'root@204.168.206.175']
    p=subprocess.run(cmd+['--dry-run'],capture_output=True,text=True);assert p.returncode==0 and 'port=8788' in p.stdout and 'protocol=ssh' in p.stdout
    p=subprocess.run(cmd+['--telnet','--dry-run'],capture_output=True,text=True);assert p.returncode!=0
    p=subprocess.run(cmd+['-r','nginx','-d','foo.com','--email','ops@foo.com','--sysvinit','--dry-run'],capture_output=True,text=True);assert p.returncode==0 and 'init=sysvinit' in p.stdout
    for extra in [['-p','0'],['-d','foo.com;id'],['-r','unknown'],['--ref','master']]: assert subprocess.run(cmd+extra+['--dry-run'],capture_output=True).returncode!=0
