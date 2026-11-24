"""Official SDK integration: intentionally skipped only if dependency is absent."""
import pytest,httpx
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
