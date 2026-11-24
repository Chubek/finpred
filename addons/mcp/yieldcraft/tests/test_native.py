"""Run with FINPRED_NATIVE_ROOT=/absolute/checkout after building native hosts."""
import os
from pathlib import Path
import pytest
from yieldcraft_mcp.server import Runtime
ROOT=os.getenv('FINPRED_NATIVE_ROOT')
pytestmark=[pytest.mark.native,pytest.mark.skipif(not ROOT,reason='compiled FinPRED checkout not provided')]
@pytest.mark.asyncio
async def test_native_pricing(config):
    root=Path(ROOT); rt=Runtime(config.model_copy(update={'finpred_root':root,'max_artifact_bytes':2_000_000,'timeout':120}))
    ids={n:rt.store.put('default',(root/'fixtures'/n).read_bytes()) for n in ['scenario.csv','valuation.csv','demand_contribution.csv','offers.csv']}
    args=('default',ids['scenario.csv'],ids['valuation.csv'])
    result=await rt.engine.recommend(*args,demand=ids['demand_contribution.csv'])
    assert result['summary']['recommendation_minor']=='19000' and not result['published']
    assert 'replay_ok=true' in (await rt.engine.inspect('default','replay',result['run_id']))['result']
    market=await rt.engine.recommend(*args,offers=ids['offers.csv'])
    assert market['summary']['recommendation_minor']=='17100'
