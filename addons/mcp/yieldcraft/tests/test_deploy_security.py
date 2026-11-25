"""Offline-only regression coverage for deployment credential boundaries."""
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

ADDON = Path(__file__).resolve().parents[1]
DEPLOYMENT = ADDON / 'deployment'
SENTINEL = 'mock-only-sensitive-value'
URL = 'https://service.example/mcp'


@pytest.fixture
def deployment_module(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOYMENT))
    return importlib.import_module


@pytest.fixture
def mocked_ssh(tmp_path):
    addon = tmp_path / 'addon'
    shutil.copytree(ADDON, addon, ignore=shutil.ignore_patterns('.venv', '__pycache__', '.pytest_cache'))
    private_paths = ['.env', 'config.toml', 'token-without-extension', 'deployment/credentials.json',
                     'yieldcraft_mcp/.env', 'yieldcraft_mcp/ui/operator-key.js']
    for path in private_paths:
        (addon / path).write_text(SENTINEL)
    commands = tmp_path / 'fake-bin'
    commands.mkdir()
    ssh = commands / 'ssh'
    ssh.write_text(f"""#!{sys.executable}
import json, os, stat, subprocess, sys
from pathlib import Path
work = Path(os.environ['MOCK_DIR'])
stage_archive = Path(os.readlink('/proc/self/fd/0'))
with (work / 'ssh.json').open('w') as f:
    json.dump([sys.argv[1:], str(stage_archive.parent),
               stat.S_IMODE(stage_archive.stat().st_mode),
               stat.S_IMODE(stage_archive.parent.stat().st_mode)], f)
archive = sys.stdin.buffer.read()
(work / 'uploaded.tar.gz').write_bytes(archive)
if remote_bin := os.environ.get('MOCK_REMOTE_BIN'):
    remote_env = dict(os.environ, PATH=remote_bin + ':' + os.environ['PATH'])
    sys.exit(subprocess.run(['/bin/sh', '-c', sys.argv[-1]], input=archive, env=remote_env).returncode)
print(os.environ['MOCK_SECRET'])
print(os.environ['MOCK_SECRET'], file=sys.stderr)
print('MCP_SERVER_URL=https://unverified.example/mcp')
print(os.environ['MOCK_STATUS'])
if os.environ.get('MOCK_NOISY_TRAILER'):
    print('noisy output ' * 20000)
sys.exit(int(os.environ.get('MOCK_RC', '0')))
""")
    python = commands / 'python3'
    python.write_text(f"""#!/bin/bash
if [[ $1 == */deployment/probe.py && $2 != --candidate ]]; then
    printf '%s\\n' "$@" > "$MOCK_DIR/probe-argv"
    exit "${{MOCK_PROBE_RC:-0}}"
fi
exec "{sys.executable}" "$@"
""")
    ssh.chmod(0o755)
    python.chmod(0o755)
    env = dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}', MOCK_DIR=str(tmp_path),
               MOCK_SECRET=SENTINEL, MOCK_STATUS=f'MCP_CANDIDATE_URL={URL}', TMPDIR=str(tmp_path))

    def run(*args, authenticated=True, **settings):
        auth_args = ['--auth', '--token-out', str(tmp_path / 'token')] if authenticated else []
        return subprocess.run(['bash', '-x', str(addon / 'deploy.sh'), 'root@127.0.0.1',
                               '-r', 'caddy', '-d', 'service.example', *auth_args, *args],
                              cwd=addon, env=dict(env, **settings), capture_output=True,
                              text=True, timeout=20)

    return run, addon


def test_deploy_only_sends_runtime_source_and_hashed_token(mocked_ssh, tmp_path):
    run, _ = mocked_ssh
    result = run()
    assert result.returncode == 0, result.stderr
    token_file = tmp_path / 'token'
    token = token_file.read_text().strip()
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    ssh_args, stage, file_mode, dir_mode = json.loads((tmp_path / 'ssh.json').read_text())
    assert {'-T', 'StrictHostKeyChecking=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes'} <= set(ssh_args)
    assert file_mode == 0o600 and dir_mode == 0o700
    assert not Path(stage).exists()
    with tarfile.open(tmp_path / 'uploaded.tar.gz') as tar:
        assert all(member.isfile() or member.isdir() for member in tar.getmembers())
        files = {member.name: tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()}
    assert 'addon/yieldcraft_mcp/ui/editor.html' in files
    assert 'addon/deployment/install.sh' in files
    assert json.loads(files['tokens.json'])[0]['sha256'] == hashlib.sha256(token.encode()).hexdigest()
    assert all(token.encode() not in value and SENTINEL.encode() not in value for value in files.values())
    probe_args = (tmp_path / 'probe-argv').read_text()
    assert probe_args.splitlines()[1:] == [URL, str(token_file)]
    observed = result.stdout + result.stderr + probe_args + ' '.join(ssh_args)
    assert token not in observed and SENTINEL not in observed
    assert result.stdout.count('MCP_SERVER_URL=') == 1 and f'MCP_SERVER_URL={URL}\n' in result.stdout
    assert 'unverified.example' not in observed


@pytest.mark.parametrize('flags', [(), ('--no-auth',)])
def test_public_deployment_runs_without_token_records(mocked_ssh, tmp_path, flags):
    run, addon = mocked_ssh
    old_token = addon / 'yieldcraft-mcp.token'
    old_token.write_text(SENTINEL)
    dry_run = run(*flags, '--dry-run', authenticated=False)
    assert dry_run.returncode == 0 and 'daemon=0 auth=0' in dry_run.stdout
    assert run(*flags, '--token-out', str(old_token), authenticated=False).returncode != 0
    result = run(*flags, authenticated=False)
    assert result.returncode == 0, result.stderr
    assert old_token.read_text() == SENTINEL and not (tmp_path / 'token').exists()
    with tarfile.open(tmp_path / 'uploaded.tar.gz') as tar:
        assert 'tokens.json' not in tar.getnames()
        assert all(not name.endswith('.token') for name in tar.getnames())
    ssh_args, *_ = json.loads((tmp_path / 'ssh.json').read_text())
    assert "'0' '0'" in ssh_args[-1]
    assert (tmp_path / 'probe-argv').read_text().splitlines()[1:] == [URL]
    assert f'MCP_SERVER_URL={URL}\n' in result.stdout and 'TOKEN_FILE=' not in result.stdout


@pytest.mark.parametrize('settings,probed,message', [
    ({'MOCK_STATUS': ''}, False, 'did not report exactly one valid MCP candidate URL'),
    ({'MOCK_STATUS': 'MCP_CANDIDATE_URL=https://other.example/mcp'}, False,
     'did not report exactly one valid MCP candidate URL'),
    ({'MOCK_STATUS': f'MCP_CANDIDATE_URL={URL}\nMCP_CANDIDATE_URL={URL}'}, False,
     'did not report exactly one valid MCP candidate URL'),
    ({'MOCK_RC': '255', 'MOCK_STATUS': ''}, False, 'SSH transport failed'),
    ({'MOCK_RC': '43'}, False, 'existing Yieldcraft installation'),
    ({'MOCK_RC': '44', 'MOCK_STATUS': ''}, False, 'cloudflared is not available on the VPS'),
    ({'MOCK_RC': '47', 'MOCK_STATUS': 'MCP_CANDIDATE_URL=invalid',
      'MOCK_NOISY_TRAILER': '1'}, False, 'FinPRED checkout failed'),
    ({'MOCK_RC': '52', 'MOCK_STATUS': ''}, False, 'Quick Tunnel did not report an endpoint'),
    ({'MOCK_RC': '1'}, False, 'SSH command did not complete the deployment'),
    ({'MOCK_PROBE_RC': '1'}, True, 'public MCP probe failed'),
])
def test_deploy_failure_never_reports_success(mocked_ssh, tmp_path, settings, probed, message):
    result = mocked_ssh[0](**settings)
    assert result.returncode != 0
    assert message in result.stderr
    assert 'MCP_SERVER_URL=' not in result.stdout
    assert SENTINEL not in result.stdout + result.stderr
    assert 'unverified.example' not in result.stdout + result.stderr
    assert (tmp_path / 'probe-argv').exists() is probed
    assert not list(tmp_path.glob('tmp.*'))


@pytest.mark.parametrize('failure,message', [
    ('tar', 'VPS staging or archive extraction failed'),
    ('sudo', 'passwordless sudo -n'),
    ('install', 'FinPRED native build or self-test failed'),
])
def test_remote_ssh_wrapper_maps_failures(mocked_ssh, tmp_path, failure, message):
    commands = tmp_path / 'remote-bin'
    commands.mkdir()
    scripts = {
        'id': f"echo {1000 if failure == 'sudo' else 0}",
        'sudo': 'exit 1',
        'tar': 'exit 1' if failure == 'tar' else (
            'mkdir -p "$6/addon/deployment"\n'
            'printf "%s\\n" "exit 48" > "$6/addon/deployment/install.sh"'),
    }
    for name, script in scripts.items():
        command = commands / name
        command.write_text(f'#!/bin/sh\n{script}\n')
        command.chmod(0o755)
    result = mocked_ssh[0](MOCK_REMOTE_BIN=str(commands))
    assert result.returncode != 0 and message in result.stderr
    assert not (tmp_path / 'probe-argv').exists()
    assert not list(tmp_path.glob('tmp.*'))


def test_installer_reports_preflight_status_before_mutating_host():
    result = subprocess.run(['bash', str(DEPLOYMENT / 'install.sh')],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 42
    assert 'root and 11 arguments required' in result.stderr


def test_dry_run_and_source_symlink_do_not_create_token_or_connect(mocked_ssh, tmp_path):
    run, addon = mocked_ssh
    assert run('--dry-run').returncode == 0
    source = addon / 'yieldcraft_mcp/ui/editor.html'
    source.unlink()
    source.symlink_to(addon / '.env')
    assert run().returncode != 0
    assert not (tmp_path / 'token').exists()
    assert not (tmp_path / 'ssh.json').exists()


def test_quick_tunnel_candidates_use_one_exact_trycloudflare_hostname(deployment_module):
    candidate_url = deployment_module('probe').candidate_url
    good = 'https://my-tunnel-1.trycloudflare.com/mcp'
    assert candidate_url(['ignored', f'MCP_CANDIDATE_URL={good}\r\n'], '-') == good
    for host in ('trycloudflare.com', 'a.b.trycloudflare.com', 't.trycloudflare.com.other.example',
                 't.trycloudflare.com@other.example', 'other.example', 't.trycloudflare.com:443'):
        with pytest.raises(ValueError):
            candidate_url([f'MCP_CANDIDATE_URL=https://{host}/mcp'], '-')


@pytest.mark.parametrize('token', [None, SENTINEL])
def test_probe_uses_verified_direct_https_and_never_prints_response(
        deployment_module, monkeypatch, capsys, token):
    probe = deployment_module('probe')
    monkeypatch.setenv('SSLKEYLOGFILE', '/not-a-real-keylog-file')
    methods = []

    class Response(io.BytesIO):
        headers = Message()
        headers['Content-Type'] = 'application/json'

    def fake_open(req, *, timeout):
        assert req.full_url == URL
        assert req.get_header('Authorization') == ('Bearer ' + token if token is not None else None)
        payload = json.loads(req.data)
        method = payload['method']
        methods.append(method)
        tool = 'yieldcraft_demo' if token is None else 'yieldcraft_optimize_contribution'
        contents = {'initialize': {'serverInfo': {'name': SENTINEL}}, 'notifications/initialized': {},
                    'tools/list': {'tools': [{'name': tool}]}}
        return Response(json.dumps({'id': payload.get('id'), 'result': contents[method]}).encode())

    def fake_opener(redirects, proxy, https):
        assert redirects.redirect_request() is None
        assert proxy.proxies == {}
        assert https._context.check_hostname and https._context.verify_mode == ssl.CERT_REQUIRED
        assert https._context.keylog_filename is None
        return SimpleNamespace(open=fake_open)

    monkeypatch.setattr(probe.urllib.request, 'build_opener', fake_opener)
    probe.probe(URL, token)
    assert methods == ['initialize', 'notifications/initialized', 'tools/list']
    assert capsys.readouterr().out == '[OK] MCP initialization and tools/list verified\n'
    with pytest.raises(ValueError):
        probe.probe('http://service.example/mcp', SENTINEL)


def test_probe_rejects_shared_or_symlinked_token_without_reading_it(
        deployment_module, tmp_path, monkeypatch, capsys):
    probe = deployment_module('probe')
    monkeypatch.setattr(probe, 'probe', lambda *_: pytest.fail('invalid token reached probe'))
    token = tmp_path / 'token'
    token.write_text(SENTINEL + '\n')
    token.chmod(0o644)
    assert probe.main([URL, str(token)]) == 1
    token.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to(token)
    assert probe.main([URL, str(link)]) == 1
    assert SENTINEL not in capsys.readouterr().err


@pytest.mark.parametrize('failure', [None, 'password-echo', 'ready', 'install'])
def test_telnet_never_prints_echoes_or_diagnostics(
        deployment_module, monkeypatch, tmp_path, capsys, failure):
    transport = deployment_module('telnet_transport')
    lines = []
    nonce = 'a' * 32

    class FakePexpectError(Exception):
        pass

    class FakeChild:
        before = f'{SENTINEL}\r\nMCP_CANDIDATE_URL={URL}\r\n'
        match = re.match(r'([0-9]+)', '1' if failure == 'install' else '0')

        def expect(self, pattern, **kwargs):
            if isinstance(pattern, str) and 'YC_READY_' in pattern and failure == 'ready':
                raise FakePexpectError(self.before)
            return 0

        def waitnoecho(self, **kwargs):
            return failure != 'password-echo'

        def sendline(self, line):
            lines.append(line)

        def close(self, **kwargs):
            pass

    def spawn(program, argv, **kwargs):
        assert program == 'telnet' and argv == ['-c', '127.0.0.1', '12345']
        return FakeChild()

    monkeypatch.setitem(sys.modules, 'pexpect', SimpleNamespace(spawn=spawn, ExceptionPexpect=FakePexpectError))
    monkeypatch.setattr(transport.getpass, 'getpass', lambda _: SENTINEL)
    monkeypatch.setattr(transport.secrets, 'token_hex', lambda _: nonce)
    archive = tmp_path / 'archive'
    archive.write_bytes(b'mocked payload')
    status = transport.main(['root@localhost', '12345', str(archive),
                             '8788', 'caddy', 'service.example', 'systemd', 'repo', 'ref', '-', '-', '0', '0'])
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
    if failure is None:
        assert status == 0 and captured.out == URL + '\n'
    else:
        assert status == 1 and captured.out == ''
    assert ('YC_END_PAYLOAD' in lines) is (failure not in ('password-echo', 'ready'))
    for line in lines:
        assert f'YC_READY_{nonce}' not in line and f'YC_DONE_{nonce}' not in line


def test_named_tunnel_rejects_unsafe_permissions_and_secret_output(monkeypatch, tmp_path, capsys):
    pytest.importorskip('yaml', reason='named-tunnel preflight requires python3-yaml')
    original_lstat = Path.lstat
    # The secure tree is the test's private directory; pytest may stage it below
    # world-writable /tmp on CI. Emulate trusted ancestors above the fixture.
    monkeypatch.setattr(Path, 'lstat', lambda path: (
        SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)
        if path in tmp_path.parents else original_lstat(path)))
    monkeypatch.syspath_prepend(str(DEPLOYMENT))
    tunnel = importlib.import_module('tunnel_config')
    config = tmp_path / 'config.yml'
    credentials = tmp_path / 'creds.json'
    credentials.write_text(SENTINEL)
    credentials.chmod(0o600)
    config.write_text(f'tunnel: example\ncredentials-file: "{credentials}"\n')
    config.chmod(0o600)
    assert tunnel.main([str(config)]) == 0
    if credentials.stat().st_gid == os.getegid():
        credentials.chmod(0o640)
        assert tunnel.main([str(config)]) == 0
    for path in (config, credentials):
        path.chmod(0o644)
        assert tunnel.main([str(config)]) == 1
        path.chmod(0o600)
    tmp_path.chmod(0o770)
    assert tunnel.main([str(config)]) == 1
    tmp_path.chmod(0o700)
    credentials.unlink()
    credentials.symlink_to(config)
    assert tunnel.main([str(config)]) == 1
    config.write_text(f'token: {SENTINEL}\ntoken: duplicate\n')
    assert tunnel.main([str(config)]) == 1
    assert SENTINEL not in capsys.readouterr().err


@pytest.mark.parametrize('proxy,marker,tls,upstream', [
    ('nginx', 'NGINX', 'listen 443 ssl;', 'proxy_pass http://127.0.0.1:'),
    ('apache2', 'APACHE', '<VirtualHost *:443>', 'ProxyPass / http://127.0.0.1:'),
])
def test_certificate_bootstrap_templates_never_proxy_cleartext(proxy, marker, tls, upstream):
    installer = (DEPLOYMENT / 'install.sh').read_text()
    section = installer.split(f'\n {proxy})\n')[1].split(';;', 1)[0]
    bootstrap, final = re.findall(rf'<<{marker}\n(.*?)\n{marker}', section, re.S)
    assert 'certbot certonly' in section.split(bootstrap)[1].split(final)[0]
    assert upstream not in bootstrap
    cleartext, secure = final.split(tls, 1)
    assert upstream not in cleartext and '308' in cleartext
    assert upstream in secure
