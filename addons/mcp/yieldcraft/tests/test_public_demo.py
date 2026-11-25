import json
import os
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from yieldcraft_mcp.config import Config
from yieldcraft_mcp.server import build_app


def public_config(config, **overrides):
    return Config.model_validate({
        **config.model_dump(), 'auth_required': False, 'token_file': None, **overrides,
    })


@pytest.mark.parametrize('conflict', [
    {'token_file': Path('/unused/tokens.json')}, {'oauth_issuer': 'https://auth.example'},
    {'enable_live': True}, {'allow_llm': True}, {'allowed_hosts': ['api.openai.com']},
    {'daemon_config': Path('/unused/Dragnet.json')}, {'daemon_autostart': True},
])
def test_public_config_rejects_credentials_and_acquisition(config, conflict):
    with pytest.raises(ValidationError):
        public_config(config, **conflict)


def test_local_config_still_requires_authentication_by_default(config):
    assert config.auth_required
    with pytest.raises(ValidationError, match='authenticated mode requires token_file'):
        Config.model_validate({**config.model_dump(), 'token_file': None})


async def rpc(client, method, params):
    response = await client.post('/mcp', headers={
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': '2025-11-25',
    }, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    assert response.status_code == 200
    assert 'www-authenticate' not in response.headers
    assert response.headers['cache-control'] == 'no-store'
    return response.json()['result']


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_public_endpoint_without_credentials_exposes_only_demo_tools(config):
    pytest.importorskip('mcp')
    config.token_file.unlink()
    app = build_app(public_config(config))
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='https://demo.trycloudflare.com') as client:
            info = await rpc(client, 'initialize', {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'demo-test', 'version': '1'},
            })
            assert info['serverInfo']['name'] == 'Yieldcraft MCP'
            listing = await rpc(client, 'tools/list', {})
            assert {tool['name'] for tool in listing['tools']} == {
                'yieldcraft_demo', 'ottomat_validate', 'ottomat_highlight', 'ottomat_list_strategies',
            }
            for tool in ('artifact_upload', 'artifact_list', 'artifact_read', 'yieldcraft_replay',
                         'dragnet_search', 'dragnet_offline_capture', 'dragnet_start', 'ottomat_execute'):
                assert (await rpc(client, 'tools/call', {'name': tool, 'arguments': {}}))['isError']
            assert (await client.get('/.well-known/oauth-protected-resource/mcp')).status_code == 404
    assert not list(config.state_dir.iterdir())


@pytest.mark.sdk
@pytest.mark.native
@pytest.mark.asyncio
async def test_public_demo_runs_native_fixtures_without_retaining_state(config):
    pytest.importorskip('mcp')
    root = os.environ.get('FINPRED_NATIVE_ROOT')
    if not root:
        pytest.skip('compiled FinPRED checkout not provided')
    app = build_app(public_config(config, finpred_root=Path(root)))
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://localhost:8788') as client:
            for case, price in [('contribution', '19000'), ('market', '17100'), ('multiroom', '16000')]:
                result = await rpc(client, 'tools/call', {'name': 'yieldcraft_demo', 'arguments': {'case': case}})
                assert not result.get('isError'), result
                data = result.get('structuredContent') or json.loads(result['content'][0]['text'])
                assert data == {
                    'case': case, 'currency': 'EUR', 'recommendation_minor': price,
                    'reason': data['reason'], 'synthetic': True, 'published': False,
                }
                assert not list(config.state_dir.iterdir())
