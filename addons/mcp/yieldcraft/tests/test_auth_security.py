import asyncio
import hashlib
import json
import time

import httpx
import pytest
from pydantic import ValidationError
from starlette.responses import JSONResponse

from conftest import TOKEN
from yieldcraft_mcp import auth
from yieldcraft_mcp.auth import Authenticator, Guard, current, principal
from yieldcraft_mcp.config import Config
from yieldcraft_mcp.server import UI_URI, build_app


def reconfigure(config, **values):
    return Config.model_validate({**config.model_dump(), **values})


def token_record(token, project, *scopes):
    return {'sha256': hashlib.sha256(token.encode()).hexdigest(), 'project': project, 'scopes': list(scopes)}


@pytest.fixture
def oauth_config(config, tmp_path):
    secret = tmp_path / 'oauth-secret'
    secret.write_text('fixture-only-secret\n')
    secret.chmod(0o600)
    return reconfigure(config, public_url='https://service.example/mcp',
                       oauth_issuer='https://issuer.example',
                       oauth_introspection_url='https://issuer.example/introspect',
                       oauth_client_id='fixture-client', oauth_secret_file=secret)


@pytest.mark.parametrize('settings', [
    {'public_url': 'https://service.example:invalid/mcp'},
    {'public_url': 'https://service.example\n/mcp'},
    {'public_url': 'https://user@service.example/mcp'},
    {'public_url': 'https://service.example/mcp?'},
    {'allowed_origins': ['https://service.example/editor']},
    {'allowed_origins': ['']},
    {'oauth_client_id': ''},
])
def test_config_rejects_ambiguous_auth_settings(config, settings):
    with pytest.raises(ValidationError):
        reconfigure(config, **settings)


def test_oauth_requires_a_nonempty_secret(oauth_config):
    oauth_config.oauth_secret_file.write_text('\n')
    with pytest.raises(ValueError, match='secret must not be empty'):
        Authenticator(oauth_config)


@pytest.mark.parametrize('record', [
    b'{"project":"one","project":"two","scopes":[],"sha256":"' + b'a' * 64 + b'"}',
    b'null',
    b'{"project":"one","scopes":[{}],"sha256":"' + b'a' * 64 + b'"}',
    b'{"project":"oauth-' + b'a' * 48 + b'","scopes":[],"sha256":"' + b'a' * 64 + b'"}',
])
def test_token_file_rejects_invalid_or_overlapping_records(config, record):
    config.token_file.write_bytes(b'[' + record + b']')
    with pytest.raises(ValueError):
        Authenticator(config)


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def introspection(monkeypatch):
    real_client = httpx.AsyncClient

    def setup(handler):
        sent = []

        async def mock(request):
            sent.append(request)
            assert request.method == 'POST'
            assert str(request.url) == 'https://issuer.example/introspect'
            assert request.headers['accept-encoding'] == 'identity'
            return await handler(request)

        def client(**options):
            assert not options['trust_env'] and not options['follow_redirects']
            return real_client(transport=httpx.MockTransport(mock), **options)

        monkeypatch.setattr(auth.httpx, 'AsyncClient', client)
        return sent

    return setup


@pytest.fixture
def claims(oauth_config):
    return {'active': True, 'iss': oauth_config.oauth_issuer,
            'aud': [oauth_config.public_url], 'exp': int(time.time()) + 60,
            'sub': 'fixture-subject', 'scope': 'research:read unrelated:scope'}


@pytest.mark.asyncio
async def test_oauth_pins_claims_and_does_not_forward_known_static_token(oauth_config, claims, introspection):
    async def handler(request):
        assert request.content == b'token=dummy-oauth&token_type_hint=access_token'
        return httpx.Response(200, stream=ByteStream(json.dumps(claims).encode()))

    sent = introspection(handler)
    authenticator = Authenticator(oauth_config)
    assert (await authenticator.verify(TOKEN)).project == 'default'
    assert not sent
    verified = await authenticator.verify('dummy-oauth')
    expected = hashlib.sha256(b'https://issuer.example\0fixture-subject').hexdigest()[:48]
    assert verified.project == 'oauth-' + expected
    assert verified.scopes == frozenset({'research:read'})
    assert len(sent) == 1


@pytest.mark.parametrize('changes', [
    {'exp': 0}, {'exp': True}, {'exp': float('nan')}, {'exp': float('inf')},
    {'exp': 'future'}, {'aud': ['https://issuer.example/mcp']},
    {'aud': ['https://service.example/mcp', None]},
    {'iss': 'https://other.example'}, {'active': 1}, {'sub': ''},
    {'scope': ['research:read']}, {'scope': 'research:read\u00a0daemon:manage'},
])
@pytest.mark.asyncio
async def test_oauth_denies_invalid_claims(oauth_config, claims, introspection, changes):
    async def handler(_):
        return httpx.Response(200, stream=ByteStream(json.dumps({**claims, **changes}).encode()))

    introspection(handler)
    assert await Authenticator(oauth_config).verify('dummy-oauth') is None


@pytest.mark.parametrize('failure', ['duplicate', 'huge_exp', 'oversized', 'compressed', 'redirect', 'unavailable'])
@pytest.mark.asyncio
async def test_oauth_denies_ambiguous_or_failed_responses(oauth_config, claims, introspection, failure):
    body = json.dumps(claims).encode()
    if failure == 'huge_exp':
        body = json.dumps({**claims, 'exp': 'out-of-range'}).encode().replace(b'"out-of-range"', b'1e999')

    async def handler(_):
        if failure == 'duplicate':
            return httpx.Response(200, stream=ByteStream(b'{"active":false,' + body[1:]))
        if failure == 'huge_exp':
            return httpx.Response(200, stream=ByteStream(body))
        if failure == 'oversized':
            return httpx.Response(200, stream=ByteStream(body, b' ' * 65536))
        if failure == 'compressed':
            return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=ByteStream(body))
        if failure == 'redirect':
            return httpx.Response(307, headers={'Location': 'https://other.example/introspect'})
        raise httpx.ReadError('fixture-only connection failure')

    sent = introspection(handler)
    assert await Authenticator(oauth_config).verify('dummy-oauth') is None
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_oauth_total_deadline_covers_stream_and_releases_slot(oauth_config, introspection, monkeypatch):
    closed = asyncio.Event()

    class Stalled(ByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def handler(_):
        return httpx.Response(200, stream=Stalled())

    introspection(handler)
    monkeypatch.setattr(auth, 'OAUTH_TIMEOUT', 0.02)
    authenticator = Authenticator(oauth_config)
    assert await asyncio.wait_for(authenticator.verify('dummy-oauth'), 1) is None
    assert closed.is_set()
    assert not authenticator.sem.locked()


@pytest.mark.asyncio
async def test_guard_validates_authority_and_strips_bearer(config):
    config = reconfigure(config, public_url='https://Service.example:443/mcp')
    seen = []

    async def endpoint(scope, receive, send):
        seen.append(scope['path'])
        assert not any(k.lower() == b'authorization' for k, _ in scope['headers'])
        if scope['path'] == '/mcp':
            assert principal('research:read').project == 'default'
        else:
            assert current.get() is None
        await JSONResponse({'ok': True}, headers={'Cache-Control': 'public'})(scope, receive, send)

    app = Guard(endpoint, config, Authenticator(config))
    headers = {'Authorization': 'bearer ' + TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8788') as client:
        response = await client.post('/mcp', headers={**headers, 'Host': 'service.example',
                                                     'Origin': 'https://service.example'}, json={})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert current.get() is None
        assert (await client.get('/version', headers=headers)).status_code == 200
        for host in ('other.example', 'service.example:444', 'service.example,127.0.0.1'):
            assert (await client.get('/version', headers={'Host': host})).status_code == 421
        for origin in ('', 'null', 'https://other.example', 'https://service.example/'):
            assert (await client.post('/mcp', headers={**headers, 'Origin': origin}, json={})).status_code == 403
        response = await client.post('/mcp', headers={'Authorization': 'Bearer invalid'}, json={})
        assert response.status_code == 401
        assert response.headers['cache-control'] == 'no-store'
        assert TOKEN not in response.text
    assert seen == ['/mcp', '/version']


@pytest.mark.asyncio
async def test_guard_rejects_ambiguous_headers_preserves_chunked_body(config):
    seen = []

    async def endpoint(scope, receive, send):
        seen.append(await receive())
        await JSONResponse({'ok': True})(scope, receive, send)

    async def chunks():
        yield b'{'
        yield b'}'

    app = Guard(endpoint, config, Authenticator(config))
    headers = [('Authorization', 'Bearer ' + TOKEN), ('Content-Type', 'application/json')]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8788') as client:
        for name, value in [('Authorization', 'Bearer ' + TOKEN), ('Origin', 'https://service.example'),
                            ('Host', 'localhost:8788'), ('MCP-Protocol-Version', '2025-11-25'),
                            ('MCP-Session-Id', 'unused'), ('Content-Length', '2')]:
            duplicates = [*headers, (name, value)]
            if name != 'Authorization':
                duplicates.append((name.lower(), value))
            assert (await client.post('/mcp', headers=duplicates, content=b'{}')).status_code == 400
        for framing in [[('Content-Length', '+2')], [('Content-Length', '3')],
                        [('Content-Length', '1')], [('Content-Length', '2'), ('Transfer-Encoding', 'chunked')]]:
            assert (await client.post('/mcp', headers=[*headers, *framing], content=b'{}')).status_code == 400
        assert (await client.post('/mcp', headers=headers, content=chunks())).status_code == 200
        assert (await client.post('/mcp', headers=[*headers, ('Host', 'fixture.trycloudflare.com')], content=b'{}')).status_code == 200
    assert seen == [{'type': 'http.request', 'body': b'{}', 'more_body': False}] * 2


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_real_sdk_scopes_isolation_errors_and_standalone_editor(config, caplog):
    pytest.importorskip('mcp')
    first, second, limited = 'dummy-one', 'dummy-two', 'dummy-limited'
    config.token_file.write_text(json.dumps([
        token_record(first, 'one', 'artifact:write', 'research:read'),
        token_record(second, 'two', 'artifact:write', 'research:read'),
        token_record(limited, 'one', 'artifact:write'),
    ]))
    app = build_app(config)
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8788') as client:
            headers = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}

            async def call(token, method, **params):
                response = await client.post('/mcp', headers={**headers, 'Authorization': 'Bearer ' + token},
                                             json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
                assert response.status_code == 200, response.text
                assert response.headers['cache-control'] == 'no-store'
                assert 'x-frame-options' not in response.headers
                assert 'content-security-policy' not in response.headers
                return response.json()

            async def tool(token, name, **args):
                return (await call(token, 'tools/call', name=name, arguments=args))['result']

            def content(result):
                assert not result.get('isError'), result
                return result.get('structuredContent') or json.loads(result['content'][0]['text'])

            one, two = await asyncio.gather(tool(first, 'artifact_upload', text='one'),
                                            tool(second, 'artifact_upload', text='two'))
            one_id, two_id = (content(item)['artifact_sha256'] for item in (one, two))
            lists = await asyncio.gather(tool(first, 'artifact_list'), tool(second, 'artifact_list'))
            assert [content(r)['ids'] for r in lists] == [[one_id], [two_id]]
            missing, denied = await asyncio.gather(tool(second, 'artifact_read', artifact_sha256=one_id),
                                                   tool(limited, 'artifact_read', artifact_sha256=one_id))
            assert missing['isError'] and 'requested data unavailable' in str(missing)
            assert str(config.state_dir) not in str(missing)
            assert str(config.state_dir) not in caplog.text
            assert denied['isError'] and 'insufficient scope' in str(denied)
            assert 'error' in await call(limited, 'resources/read', uri=UI_URI)
            assert 'error' in await call(limited, 'prompts/get', name='audit_financial_decision',
                                         arguments={'run_id': one_id})
            assert not (await call(first, 'prompts/get', name='audit_financial_decision',
                                   arguments={'run_id': one_id})).get('error')
            editor = await client.get('/editor')
            assert editor.status_code == 200
            assert editor.headers['x-frame-options'] == 'DENY'
            assert "frame-ancestors 'none'" in editor.headers['content-security-policy']
            ui = (await call(first, 'resources/read', uri=UI_URI))['result']['contents'][0]
            assert ui['mimeType'] == 'text/html;profile=mcp-app'
            assert ui['text'] == editor.text
