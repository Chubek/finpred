"""Official SDK integration: intentionally skipped only if dependency is absent."""
import asyncio
import socket

import httpx
import pytest
import uvicorn
from starlette.testclient import TestClient
from conftest import TOKEN
pytest.importorskip('mcp')
from yieldcraft_mcp.server import build_app
@pytest.mark.sdk
def test_protocol(config):
    with TestClient(build_app(config)) as client:
        h={'Authorization':'Bearer '+TOKEN,'Accept':'application/json, text/event-stream','Content-Type':'application/json','MCP-Protocol-Version':'2025-11-25'}
        def call(method,params,id=1):
            d={'jsonrpc':'2.0','method':method,'params':params}
            if id is not None:d['id']=id
            r=client.post('/mcp',headers=h,json=d);assert r.status_code in (200,202),r.text
            return r.json()['result'] if id is not None else None
        assert client.post('/mcp',json={}).status_code==401
        call('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'tests','version':'1'}})
        call('notifications/initialized',{},None)
        tools=call('tools/list',{})['tools'];assert any(t['name']=='ottomat_execute' for t in tools)
        ui=next(t for t in tools if t['name']=='ottomat_highlight');assert ui['_meta']['ui']['resourceUri'].startswith('ui://')
        r=call('tools/call',{'name':'artifact_upload','arguments':{'text':'abc'}});assert not r.get('isError',False),r
        r=call('resources/read',{'uri':'ui://yieldcraft/ottomat-editor.html'});assert r['contents'][0]['mimeType']=='text/html;profile=mcp-app'

@pytest.mark.sdk
@pytest.mark.asyncio
async def test_sdk_loopback_transport(config):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    ready = asyncio.Event()

    class LoopbackServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        app = build_app(config.model_copy(update={'port': port}))
        server = LoopbackServer(uvicorn.Config(
            app, host='127.0.0.1', port=port, access_log=False, log_config=None, proxy_headers=False,
        ))
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                await ready.wait()
                assert server.started
                url = f'http://127.0.0.1:{port}/mcp'
                async with httpx.AsyncClient(trust_env=False) as http:
                    assert (await http.post(url, json={})).status_code == 401
                    http.headers['Authorization'] = 'Bearer ' + TOKEN
                    async with streamable_http_client(url, http_client=http) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            info = await session.initialize()
                            assert info.serverInfo.name == 'Yieldcraft MCP'
                            assert 'artifact_upload' in {tool.name for tool in (await session.list_tools()).tools}
                            result = await session.call_tool('artifact_upload', {'text': 'loopback smoke test'})
                            assert not result.isError
        finally:
            server.should_exit = True
            await asyncio.wait_for(running, timeout=5)
