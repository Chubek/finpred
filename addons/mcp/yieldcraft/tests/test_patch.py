"""Test config transitions and service rollback without touching the host."""
import fcntl
import importlib
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from yieldcraft_mcp.config import load


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    addon = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(addon / 'deployment'))
    patch = importlib.import_module('patch')
    etc, state, base, logs = (tmp_path / name for name in ('etc', 'state', 'opt', 'logs'))
    for name, path in [('ETC', etc), ('STATE', state), ('BASE', base), ('LOGS', logs),
                       ('SYSTEMD', tmp_path / 'unit'), ('SYSV', tmp_path / 'init')]:
        monkeypatch.setattr(patch, name, path)
    user = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
    monkeypatch.setattr(patch, 'trusted', lambda info: info.st_uid == user.pw_uid and not info.st_mode & 0o022)
    monkeypatch.setattr(patch.os, 'fchown', lambda *_: None)
    monkeypatch.setattr(patch.pwd, 'getpwnam', lambda name: user)
    etc.mkdir(mode=0o750)
    state.mkdir(mode=0o700)
    projects = state / 'projects'
    projects.mkdir(mode=0o700)
    (projects / 'record').write_text('private run data')
    tokens = etc / 'tokens.json'
    tokens.write_text('unchanged token records')
    tokens.chmod(0o600)
    patch.SYSTEMD.touch(mode=0o644)
    path = etc / 'config.toml'
    original = f'''# preserve these bytes in the backup
finpred_root = "{base / 'finpred'}"
state_dir = "{projects}"
bind = "127.0.0.1"
port = 8788
auth_required = true
token_file = "{tokens}"
enable_live = true
allow_llm = true
allowed_hosts = ["api.openai.com"]
offer_hosts = ["api.openai.com"]
daemon_config = "{etc / 'Dragnet.json'}"
daemon_autostart = true
public_url = "https://service.example/mcp"
oauth_issuer = "https://issuer.example"
oauth_introspection_url = "https://issuer.example/introspect"
oauth_client_id = "operator-client"
oauth_secret_file = "{etc / 'oauth-secret'}"
allowed_origins = ["https://client.example"]
max_concurrent = 3
'''.encode()
    path.write_bytes(original)
    path.chmod(0o640)
    restarts = []
    settings = {'--local-demo': True, '--local-ready': True, 'validate': True}

    def run(argv, *, timeout):
        if argv[0] in ('/usr/bin/systemctl', '/usr/sbin/service'):
            restarts.append((argv, load(path).auth_required))
            return True
        assert argv[:4] == ['/usr/sbin/runuser', '-u', patch.NAME, '--']
        if argv[4] == '/usr/bin/mkdir':
            Path(argv[-1]).mkdir(mode=0o700)
            return True
        assert argv[4] == base / 'venv/bin/python'
        assert load(argv[-1]).auth_required is False
        return settings['validate']

    monkeypatch.setattr(patch, 'run', run)
    monkeypatch.setattr(patch, 'local_probe', lambda port, mode: settings[mode])
    monkeypatch.setattr(patch, 'wait_local', lambda port, mode: settings[mode])
    return SimpleNamespace(patch=patch, path=path, original=original, state=state, projects=projects,
                           tokens=tokens, restarts=restarts, settings=settings)


def test_patch_preserves_proxy_and_private_state_and_is_idempotent(deployed):
    d = deployed
    assert d.patch.apply_patch(8788, 'auto', '-') == 'https://service.example/mcp'
    config = load(d.path)
    assert not config.auth_required and not config.enable_live and not config.allow_llm
    assert config.token_file is config.oauth_issuer is config.daemon_config is None
    assert config.allowed_hosts == config.offer_hosts == []
    assert not config.daemon_autostart and config.state_dir == d.state / 'public-demo'
    assert config.allowed_origins == ['https://client.example'] and config.max_concurrent == 3
    assert config.public_url == 'https://service.example/mcp' and config.port == 8788
    assert (d.projects / 'record').read_text() == 'private run data'
    assert d.tokens.read_text() == 'unchanged token records'
    backup, = d.path.parent.glob('config.pre-patch-*.toml')
    assert backup.read_bytes() == d.original and stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert d.restarts == [(['/usr/bin/systemctl', 'restart', 'yieldcraft-mcp.service'], False)]
    assert d.patch.apply_patch(8788, 'systemd', 'service.example') == config.public_url
    assert list(d.path.parent.glob('config.pre-patch-*.toml')) == [backup]
    assert len(d.restarts) == 1


def test_patch_keeps_quick_tunnel_and_does_not_freeze_the_hostname(deployed):
    d = deployed
    d.path.write_bytes(b'\n'.join(line for line in d.original.splitlines()
                                  if not line.startswith((b'public_url', b'oauth_'))) + b'\n')
    d.patch.LOGS.mkdir()
    url = 'https://test-quick-host.trycloudflare.com'
    (d.patch.LOGS / 'cloudflared.log').write_text(f'cloudflared | {url} |\n')
    assert d.patch.apply_patch(8788, 'auto', '-') == url + '/mcp'
    assert load(d.path).public_url is None
    assert len(d.restarts) == 1 and 'yieldcraft-mcp.service' in d.restarts[0][0]


@pytest.mark.parametrize('port,init,domain,code', [
    (9000, 'auto', '-', 54), (8788, 'sysvinit', '-', 54), (8788, 'auto', 'different.example', 55),
])
def test_patch_rejects_wrong_installation_before_mutating(deployed, port, init, domain, code):
    d = deployed
    with pytest.raises(d.patch.PatchError) as error:
        d.patch.apply_patch(port, init, domain)
    assert error.value.code == code
    assert d.path.read_bytes() == d.original
    assert not (d.state / 'public-demo').exists()
    assert not d.restarts


def test_patch_refuses_to_reuse_a_symlink_to_private_state(deployed):
    d = deployed
    (d.state / 'public-demo').symlink_to(d.projects, target_is_directory=True)
    with pytest.raises(d.patch.PatchError) as error:
        d.patch.apply_patch(8788, 'auto', '-')
    assert error.value.code == 54
    assert d.path.read_bytes() == d.original and not d.restarts


def test_patch_checks_installed_addon_before_replacing_config(deployed):
    d = deployed
    d.settings['validate'] = False
    with pytest.raises(d.patch.PatchError) as error:
        d.patch.apply_patch(8788, 'auto', '-')
    assert error.value.code == 56
    assert d.path.read_bytes() == d.original and not d.restarts
    assert sorted(p.name for p in d.path.parent.iterdir()) == ['config.toml', 'tokens.json']


def test_patch_reports_a_concurrent_update(deployed, monkeypatch):
    d = deployed
    fd = os.open(d.path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        monkeypatch.setattr(d.patch.os, 'geteuid', lambda: 0)
        assert d.patch.main(['8788', 'auto', '-']) == 59
    finally:
        os.close(fd)
    assert d.path.read_bytes() == d.original and not d.restarts


@pytest.mark.parametrize('restored,code', [(True, 57), (False, 58)])
def test_patch_restores_previous_config_after_failed_startup(deployed, restored, code):
    d = deployed
    d.patch.SYSTEMD.unlink()
    d.patch.SYSV.touch(mode=0o755)
    d.settings.update({'--local-demo': False, '--local-ready': restored})
    with pytest.raises(d.patch.PatchError) as error:
        d.patch.apply_patch(8788, 'auto', '-')
    assert error.value.code == code
    assert d.path.read_bytes() == d.original and stat.S_IMODE(d.path.stat().st_mode) == 0o640
    command = ['/usr/sbin/service', 'yieldcraft-mcp', 'restart']
    assert d.restarts == [(command, False), (command, True)]
