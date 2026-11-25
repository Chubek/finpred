"""Project and child-process policy tests using dummy local data only."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from yieldcraft_mcp.processes import EngineError, OPENAI_BASE_URL
from yieldcraft_mcp.server import Runtime


@pytest.mark.parametrize('component', ['project', 'objects'])
def test_artifact_directories_do_not_follow_links(runtime, component):
    store = runtime.store
    digest = store.put('first', b'project-owned artifact')
    first = store.project('first')
    if component == 'project':
        (store.root / 'second').symlink_to(first, target_is_directory=True)
    else:
        second = store.project('second')
        (second / 'objects').rmdir()
        (second / 'objects').symlink_to(first / 'objects', target_is_directory=True)
    for operation in (lambda: store.read('second', digest),
                      lambda: store.list('second'),
                      lambda: store.put('second', b'other artifact')):
        with pytest.raises(ValueError, match='private state directory required'):
            operation()
    assert store.list('first') == [digest]


def test_artifact_objects_are_private_unlinked_files(runtime):
    store = runtime.store
    digest = store.put('first', b'dummy artifact')
    owner = store.project('first') / 'objects' / digest
    other = store.project('second') / 'objects'
    copied = store.put('second', b'normal local upload')
    (other / digest).symlink_to(owner)
    assert store.list('second') == [copied]
    with pytest.raises(ValueError, match='unsafe artifact object'):
        store.read('second', digest)
    (other / digest).unlink()
    os.link(owner, other / digest)
    assert store.list('second') == [copied]
    with pytest.raises(ValueError, match='unsafe artifact object'):
        store.read('second', digest)
    with pytest.raises(ValueError, match='unsafe artifact object'):
        store.put('second', b'dummy artifact')
    (other / digest).unlink()
    assert store.read('first', digest) == b'dummy artifact'
    with pytest.raises(FileNotFoundError, match=r'^artifact not found$'):
        store.read('second', digest)


@pytest.mark.asyncio
@pytest.mark.parametrize('alias', ['home', 'manifest-directory', 'archive-file'])
async def test_native_replay_rejects_linked_project_store(runtime, fake, alias):
    fake('finpred', 'print("dummy replay")')
    a = runtime.store.project('first') / 'runs'
    b = runtime.store.project('second') / 'runs'
    run_id = '1' * 64
    (a / 'runs').mkdir(mode=0o700)
    owner = a / 'runs' / (run_id + '.txt')
    owner.write_bytes(b'dummy archive bytes')
    if alias == 'home':
        b.rmdir()
        b.symlink_to(a, target_is_directory=True)
    elif alias == 'manifest-directory':
        (b / 'runs').symlink_to(a / 'runs', target_is_directory=True)
    else:
        (b / 'runs').mkdir(mode=0o700)
        (b / 'runs' / owner.name).symlink_to(owner)
    with pytest.raises(ValueError, match='private state directory required|unsafe native store entry'):
        await runtime.engine.inspect('second', 'replay', run_id)
    assert owner.read_bytes() == b'dummy archive bytes'
    assert (await runtime.engine.inspect('first', 'replay', run_id))['result'] == 'dummy replay\n'


@pytest.mark.asyncio
async def test_native_child_is_private_and_has_no_ambient_environment(runtime, fake, monkeypatch):
    for name in ('OPENAI_API_KEY', 'FINPRED_HOME', 'HTTPS_PROXY', 'LD_PRELOAD', 'YC_ARCHIVE'):
        monkeypatch.setenv(name, 'dummy-ambient-setting')
    fake('finpred', '''import json, os, pathlib
target = pathlib.Path(os.environ['TMPDIR']) / 'child-file'
target.write_bytes(b'dummy')
print(json.dumps({
    'home': os.environ['FINPRED_HOME'],
    'mode': target.stat().st_mode & 0o777,
    'ambient': any(k in os.environ for k in ('OPENAI_API_KEY','HTTPS_PROXY','LD_PRELOAD','YC_ARCHIVE')),
}))''')
    result = json.loads(await runtime.runner.run('second', 'finpred', 'selftest'))
    assert result == {'home': str(runtime.store.project('second') / 'runs'), 'mode': 0o600, 'ambient': False}
    with pytest.raises(ValueError, match='invalid internal environment override'):
        await runtime.runner.run('second', 'finpred', 'selftest', extra={'OPENAI_API_KEY': 'dummy'})
    with pytest.raises(ValueError, match='invalid internal environment override'):
        runtime.runner.env('second', {'YC_FILE_16': 'dummy'}, tool='ottomat-bridge')
    with pytest.raises(ValueError, match='invalid Dragnet endpoint override'):
        runtime.runner.env('second', {'OPENAI_BASE_URL': 'https://ungranted.example/v1'}, tool='dragnet')


@pytest.mark.asyncio
async def test_child_failure_hides_stderr_and_local_paths(runtime, fake, caplog):
    marker = 'dummy diagnostic marker'
    fake('finpred', f'import sys; print({marker!r}, file=sys.stderr); raise SystemExit(2)')
    with pytest.raises(EngineError, match=r'^finpred rejected request \(exit 2\); validate input$'):
        await runtime.runner.run('first', 'finpred')
    with pytest.raises(EngineError, match=r'^finpred could not start$'):
        await runtime.runner.run('first', 'finpred', cwd=runtime.cfg.finpred_root / marker)
    assert marker not in caplog.text


def test_dragnet_gpt_credentials_are_mode_and_endpoint_scoped(runtime, monkeypatch, tmp_path):
    for name in ('OPENAI_API_KEY', 'OPENAI_ACCESS_TOKEN', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID'):
        monkeypatch.setenv(name, 'dummy-gpt-setting')
    monkeypatch.setenv('OPENAI_MODEL', 'dummy-model')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://search-provider.example/v1')
    dragnet = runtime.dragnet
    offline = {'transport': 'offline', 'extraction': 'gpt'}
    assert dragnet.credentials(offline) == {'OPENAI_MODEL': 'dummy-model'}
    assert dragnet.credentials({'transport': 'https', 'extraction': 'basic'}) is None
    live = dragnet.credentials({'transport': 'https', 'extraction': 'gpt'})
    assert live['OPENAI_API_KEY'] == 'dummy-gpt-setting'
    assert live['OPENAI_BASE_URL'] == OPENAI_BASE_URL
    path = dragnet.config_snapshot(tmp_path, json.dumps(offline).encode(), offline)
    snapshot = json.loads(path.read_bytes())
    env_file = Path(snapshot['env_file'])
    assert env_file.parent == tmp_path and env_file.read_bytes() == b''
    assert path.stat().st_mode & 0o777 == env_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_operator_capture_owner_and_immutable_daemon_config(config, fake, tmp_path):
    path = tmp_path / 'operator.json'
    configuration = {'transport': 'offline', 'keywords': ['dummy operator data']}
    path.write_text(json.dumps(configuration))
    rt = Runtime(config.model_copy(update={'daemon_config': path}))
    data = (b'{"format":"dragnet.batch@1","requested_as_of":"2026-11-24T00:00:00Z"}\n'
            b'{"format":"dragnet.batch-end@1","pages":0}\n')
    fake('dragnet', f'''import json, pathlib, sys
path = pathlib.Path(sys.argv[sys.argv.index('--config')+1])
assert path != pathlib.Path({str(path)!r})
assert path.stat().st_mode & 0o777 == 0o600
assert pathlib.Path.cwd() == pathlib.Path({str(config.finpred_root)!r})
assert json.loads(path.read_bytes()) == {configuration!r}
sys.stdout.buffer.write({data!r})''')
    fake('finpred', 'import sys; assert sys.argv[1] == "dragnet-inspect"; print("dummy inspection")')
    with pytest.raises(PermissionError, match='another project'):
        await rt.dragnet.one_offline('other')
    with pytest.raises(PermissionError, match='another project'):
        await rt.dragnet.start('other')
    with pytest.raises(PermissionError, match='another project'):
        await rt.dragnet.stop('other')
    result = await rt.dragnet.one_offline('default')
    assert rt.store.read('default', result['artifact_sha256']) == data
    await rt.dragnet.start('default')
    assert rt.dragnet.status('other') == {'running': False, 'owned_by_current_project': False}
    path.write_text('{"transport":"https"}')
    await rt.dragnet.task
    status = rt.dragnet.status('default')
    assert status['cycles'] == 1 and status['last_capture'] == result and status['error'] is None
    assert rt.store.list('other') == []
    assert rt.dragnet.status('other') == {'running': False, 'owned_by_current_project': False}


@pytest.mark.asyncio
async def test_recommend_requires_project_artifact_input_ids(runtime, fake):
    fake('yieldcraft', 'raise AssertionError("must not launch")')
    digest = runtime.store.put('default', b'dummy input')
    for key in ('demand', 'offers', 'capture'):
        with pytest.raises(ValueError, match='expected 64 lowercase hex characters'):
            await runtime.engine.recommend('default', digest, digest, **{key: ''})
    with pytest.raises(FileNotFoundError, match='artifact not found'):
        await runtime.engine.recommend('other', digest, digest, demand=digest)


@pytest.mark.asyncio
async def test_ottomat_unexpected_protocol_output_is_not_disclosed(runtime, monkeypatch):
    native = runtime.cfg.finpred_root / 'build/dev/finpred-ottomat-mcp'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'dummy local bridge')
    native.with_suffix('.json').write_text(json.dumps({
        'bridge_sha256': hashlib.sha256(native.read_bytes()).hexdigest(),
        'compiler_identity': 'sha256:' + '2' * 64,
    }))
    marker = b'DUMMY_DIAGNOSTIC'
    digest = b'blake3:' + b'3' * 64
    source = b'ottomat 6\neffect pure\n'
    source_id = runtime.store.put('default', source)

    async def bridge(project, tool, *, extra):
        return {
            'validate': b'ok 0 0\n' + digest + b'\n' + digest + b'\n',
            'capture': marker + b'\n',
            'replay': marker + b'\n',
        }[extra['YC_TASK']]

    monkeypatch.setattr(runtime.runner, 'run', bridge)
    report = await runtime.ottomat.native_validate('default', source.decode())
    assert report['native_validated'] and report['source_digest'] == digest.decode()
    with pytest.raises(EngineError, match=r'^native graph rejected execution$'):
        await runtime.ottomat.execute_graph('default', source_id, {'scene': source_id}, '2026-11-24T00:00:00Z')
    with pytest.raises(EngineError, match=r'^invalid native Ottomat response$'):
        await runtime.ottomat.replay_graph('default', source_id, digest.decode())

    archive = b'dummy archive\nwith exact trailing whitespace \r\n'

    async def capture(project, tool, *, extra):
        if extra['YC_TASK'] == 'capture':
            return b'ok\n' + digest + b'\n' + digest + b'\n' + archive
        return await bridge(project, tool, extra=extra)

    monkeypatch.setattr(runtime.runner, 'run', capture)
    report = await runtime.ottomat.execute_graph('default', source_id, {'scene': source_id}, '2026-11-24T00:00:00Z')
    assert runtime.store.read('default', report['archive_sha256']) == archive
