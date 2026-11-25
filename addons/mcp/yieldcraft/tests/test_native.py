"""Run with FINPRED_NATIVE_ROOT=/absolute/checkout after building native hosts."""
import asyncio
import os
from pathlib import Path
import pytest
from yieldcraft_mcp.processes import EngineError
from yieldcraft_mcp.server import Runtime
ROOT=os.getenv('FINPRED_NATIVE_ROOT')
pytestmark=[pytest.mark.native,pytest.mark.skipif(not ROOT,reason='compiled FinPRED checkout not provided')]
@pytest.mark.asyncio
async def test_native_pricing(config):
    root=Path(ROOT); rt=Runtime(config.model_copy(update={'finpred_root':root,'max_artifact_bytes':2_000_000,'timeout':120}))
    ids={n:rt.store.put('default',(root/'fixtures'/n).read_bytes()) for n in [
        'scenario.csv','valuation.csv','demand_contribution.csv','offers.csv',
        'scenario_multiroom.csv','offers_multiroom.csv',
    ]}
    args=('default',ids['scenario.csv'],ids['valuation.csv'])
    result=await rt.engine.recommend(*args,demand=ids['demand_contribution.csv'])
    assert result['summary']['recommendation_minor']=='19000' and not result['published']
    assert 'replay_ok=true' in (await rt.engine.inspect('default','replay',result['run_id']))['result']
    trace=(await rt.engine.inspect('default','explain',result['run_id']))['result']
    assert 'expected_contribution_minor_milli=1155000000' in trace.splitlines()
    market=await rt.engine.recommend(*args,offers=ids['offers.csv'])
    assert market['summary']['recommendation_minor']=='17100' and not market['published']
    multiroom=await rt.engine.recommend(
        'default',ids['scenario_multiroom.csv'],ids['valuation.csv'],offers=ids['offers_multiroom.csv'],
    )
    assert multiroom['summary']['recommendation_minor']=='16000' and not multiroom['published']

    for run_id in (result['run_id'],market['run_id'],multiroom['run_id']):
        for operation in ('replay','explain','evidence','poindexter'):
            with pytest.raises(EngineError):
                await rt.engine.inspect('another-project',operation,run_id)
    assert rt.store.list('another-project')==[]

@pytest.mark.asyncio
async def test_native_offline_dragnet_is_project_local(config):
    root=Path(ROOT)
    rt=Runtime(config.model_copy(update={
        'finpred_root':root,'daemon_config':root/'plugins/dragnet/examples/Dragnet.json',
        'max_artifact_bytes':2_000_000,'timeout':120,
    }))
    result=await rt.dragnet.one_offline('default')
    capture=rt.store.read('default',result['artifact_sha256'])
    assert capture.splitlines()[0].startswith(b'{"format":"dragnet.batch@1"')
    assert b'"format":"dragnet.batch-end@1"' in capture.splitlines()[-1]
    assert not result['published']
    with pytest.raises(FileNotFoundError):
        rt.store.read('another-project',result['artifact_sha256'])
    assert rt.store.list('another-project')==[]

    admitted=asyncio.Event()
    admit=rt.dragnet.admit

    async def signal_admission(project, raw):
        capture=await admit(project,raw)
        admitted.set()
        return capture

    rt.dragnet.admit=signal_admission
    await rt.dragnet.start('default')
    try:
        await asyncio.wait_for(admitted.wait(),10)
        owner_status=rt.dragnet.status('default')
        assert owner_status['running'] and owner_status['cycles']==1
        assert owner_status['last_capture']['artifact_sha256']==result['artifact_sha256']
        assert 'last_capture' not in rt.dragnet.status('another-project')
        with pytest.raises(PermissionError):
            await rt.dragnet.start('another-project')
        with pytest.raises(PermissionError):
            await rt.dragnet.stop('another-project')
    finally:
        await rt.dragnet.stop('default')
