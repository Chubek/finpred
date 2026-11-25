"""Run the management scripts against a fake VPS filesystem and service tools."""
import base64
import importlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

DEPLOYMENT = Path(__file__).resolve().parents[1] / 'deployment'
FIRST = '10203040-5060-4780-90a0-b0c0d0e0f000'
SECOND = '10203040-5060-4780-90a0-b0c0d0e0f001'


def prefix(instance):
    return 'yc-' + base64.b32encode(uuid.UUID(instance).bytes).decode().lower().rstrip('=')


@pytest.fixture
def vps(tmp_path):
    root = tmp_path / 'root'
    tools = tmp_path / 'tools'
    stage = tmp_path / 'stage'
    copied = stage / 'addon/deployment'
    copied.mkdir(parents=True)
    tools.mkdir()
    for directory in ('etc/systemd/system', 'etc/init.d', 'etc/caddy/yieldcraft.d',
                      'etc/nginx/sites-available', 'etc/nginx/sites-enabled',
                      'opt', 'var/lib', 'var/log'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for file in ('instance.sh', 'manage.sh', 'reconfigure.py'):
        text = (DEPLOYMENT / file).read_text()
        for path in ('/etc/', '/opt/', '/var/'):
            text = text.replace(path, str(root) + path)
        (copied / file).write_text(text)
    (copied / 'probe.py').write_text('pass\n')
    (copied / 'install.sh').write_text('''#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/instance.sh"
mode=$1 id=$2 port=$3 init=$4 proxy=$5 domain=$6 email=$7 cf=$8
instance_paths "$id"
record="$registry/$id.instance"
if [[ $mode == install ]]; then
 [[ $# == 13 ]] || exit 41
 [[ ! -e $record && ! -e $registry/$id.retired ]] &&
   available_route "$port" "$domain" '' || exit 43
 save_record "$record" active "$port" "$init" "$proxy" "$domain" "$email" "$cf"
 exit 0
fi
printf 'proxy %s %s\\n' "$proxy" "$domain" >> "$TRACE"
[[ $domain != "${FAIL_DOMAIN:-}" ]] || exit 51
if [[ $proxy == caddy ]]; then
 printf '# Yieldcraft instance %s\\n' "$id" > "$FAKE_ROOT/etc/caddy/yieldcraft.d/$backend.caddy"
fi
''')

    for name, script in {
        'id': 'echo 0',
        'stat': f'{shutil.which("stat")} "$@" | sed -e "s/^{os.getuid()}:/0:/" -e "s/^{os.getuid()}$/0/"',
        'systemctl': 'echo "systemctl $*" >> "$TRACE"',
        'service': 'echo "service $*" >> "$TRACE"; [[ $* != "${FAIL_SERVICE:-}" ]]',
        'caddy': 'exit 0',
        'nginx': 'exit 0',
        'runuser': 'exit 0',
        'chown': 'exit 0',
        'install': f'if [[ $3 == -o ]]; then shift 6; fi; {shutil.which("install")} "$@"',
    }.items():
        path = tools / name
        path.write_text('#!/bin/bash\n' + script + '\n')
        path.chmod(0o755)
    trace = tmp_path / 'trace'
    trace.touch()
    env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}', TRACE=str(trace), FAKE_ROOT=str(root))
    registry = root / 'etc/yieldcraft-instances'

    def run(action, instance=FIRST, *options, **settings):
        return subprocess.run(['bash', str(copied / 'manage.sh'), str(stage), action, instance, *options],
                              capture_output=True, text=True, env=dict(env, **settings), timeout=10)

    def install(instance=FIRST, port='8788', host='first.example'):
        return run('install', instance, port, 'systemd', 'caddy', host, '-', '-',
                   'https://example.com/repo.git', '0' * 40, '1', '1')

    def materialize(instance, port, host):
        key = prefix(instance)
        base, etc, state = [root / folder / key for folder in ('opt', 'etc', 'var/lib')]
        for folder in (base, etc, state):
            folder.mkdir()
        (base / 'run-mcp').write_text('managed launcher')
        (state / 'private-run').write_text('private data')
        (etc / 'tokens.json').write_text('private credentials')
        conf = etc / 'config.toml'
        conf.write_text(f'''finpred_root = "{base}/finpred"
state_dir = "{state}"
bind = "127.0.0.1"
port = {port}
auth_required = true
token_file = "{etc}/tokens.json"
daemon_config = "{etc}/dragnet.json"
daemon_autostart = true
public_url = "https://{host}/mcp"
''')
        unit = root / f'etc/systemd/system/{key}-mcp.service'
        unit.write_text(f'ExecStart={base}/run-mcp\n')
        site = root / f'etc/caddy/yieldcraft.d/{key}-mcp.caddy'
        site.write_text(f'# Yieldcraft instance {instance}\n')
        return base, etc, state, conf, unit, site

    return run, install, materialize, registry, trace


def test_uuid_prefix_encodes_all_bits_and_is_short():
    result = subprocess.run(['bash', '-c', 'source "$1"; instance_prefix "$2"; instance_prefix "$3"',
                             'test', str(DEPLOYMENT / 'instance.sh'), FIRST, SECOND],
                            check=True, capture_output=True, text=True)
    assert result.stdout.splitlines() == [prefix(FIRST), prefix(SECOND)]
    assert len(prefix(FIRST)) == 29


def test_duplicate_ids_ports_and_domains_refused(vps):
    _, install, _, _, _ = vps
    assert install().returncode == 0
    assert install(FIRST, '8789', 'other.example').returncode == 43
    assert install(SECOND, '8788', 'other.example').returncode == 43
    assert install(SECOND, '8789', 'first.example').returncode == 43
    assert install(SECOND, '8789', 'second.example').returncode == 0


def test_uninstall_keeps_other_instance_and_releases_its_port(vps):
    run, install, materialize, registry, trace = vps
    assert install().returncode == 0
    assert install(SECOND, '8789', 'second.example').returncode == 0
    base, etc, state, config, unit, site = materialize(FIRST, 8788, 'first.example')
    other = materialize(SECOND, 8789, 'second.example')
    assert run('uninstall', FIRST, '8789').returncode == 60
    result = run('uninstall', FIRST, '0')
    assert result.returncode == 0, result.stderr
    assert not base.exists() and not unit.exists() and not site.exists()
    assert config.exists() and (etc / 'tokens.json').exists() and (state / 'private-run').exists()
    assert all(p.exists() for p in other)
    assert prefix(SECOND) not in trace.read_text()
    assert (registry / f'{FIRST}.retired').exists()
    assert install(FIRST, '8788', 'first.example').returncode == 43
    assert install('10203040-5060-4780-90a0-b0c0d0e0f002').returncode == 0


def test_uninstall_refuses_unmanaged_site_or_shared_proxy_reload_failure(vps):
    run, install, materialize, registry, _ = vps
    assert install().returncode == 0
    base, _, _, _, unit, site = materialize(FIRST, 8788, 'first.example')
    original = site.read_bytes()
    site.write_text('# unrelated operator config\n')
    assert run('uninstall', FIRST, '0').returncode == 61
    assert site.read_text() == '# unrelated operator config\n'
    site.write_bytes(original)
    assert run('uninstall', FIRST, '0', FAIL_SERVICE='caddy reload').returncode == 61
    assert site.read_bytes() == original and base.exists() and unit.exists()
    assert (registry / f'{FIRST}.instance').exists()


def test_configure_combined_daemon_and_proxy_and_rolls_back_on_failure(vps):
    run, install, materialize, registry, trace = vps
    assert install().returncode == 0
    assert install(SECOND, '8789', 'second.example').returncode == 0
    _, etc, _, config, _, site = materialize(FIRST, 8788, 'first.example')
    original = config.read_bytes()
    assert run('configure', FIRST, '0', '0', 'caddy', 'second.example', '-', '-').returncode == 60
    options = ['0', '0', 'caddy', 'new.example', '-', '-']
    result = run('configure', FIRST, *options, FAIL_DOMAIN='new.example')
    assert result.returncode == 63, (result.stderr, trace.read_text())
    assert config.read_bytes() == original and site.exists()
    assert not (registry / f'{FIRST}.transition.instance').exists()
    assert 'first.example' in (registry / f'{FIRST}.instance').read_text()
    result = run('configure', FIRST, *options)
    assert result.returncode == 0, (result.stderr, trace.read_text())
    assert 'daemon_autostart = false' in config.read_text()
    assert 'public_url = "https://new.example/mcp"' in config.read_text()
    assert (etc / 'tokens.json').read_text() == 'private credentials'
    assert 'new.example' in (registry / f'{FIRST}.instance').read_text()


def test_failed_rollback_keeps_the_unverified_domain_reserved(vps):
    run, install, materialize, registry, _ = vps
    assert install().returncode == 0
    materialize(FIRST, 8788, 'first.example')
    # Refuse even the first shared proxy reload. Its old file is restored,
    # but we cannot verify the live proxy until the operator fixes the reload.
    result = run('configure', FIRST, '0', '=', 'caddy', 'new.example', '-', '-',
                 FAIL_SERVICE='caddy reload')
    assert result.returncode == 64
    assert (registry / f'{FIRST}.transition.instance').exists()
    assert install(SECOND, '8789', 'new.example').returncode == 43
    assert run('uninstall', FIRST, '0').returncode == 0
    assert not (registry / f'{FIRST}.transition.instance').exists()


def test_production_caddy_proxy_keeps_separate_sites(tmp_path):
    root, source, tools = (tmp_path / name for name in ('root', 'source', 'tools'))
    for path in (root / 'etc/caddy', source, tools):
        path.mkdir(parents=True)
    main = root / 'etc/caddy/Caddyfile'
    main.write_text('operator.example {\n respond OK\n}\n')
    for name in ('install.sh', 'instance.sh'):
        text = (DEPLOYMENT / name).read_text().replace('/opt/', str(root) + '/opt/')
        text = text.replace('/etc/', str(root) + '/etc/')
        (source / name).write_text(text)
    for name, script in {'id': 'echo 0', 'apt-get': ':', 'service': ':', 'caddy': ':'}.items():
        path = tools / name
        path.write_text(f'#!/bin/sh\n{script}\n')
        path.chmod(0o755)
    env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}')
    for ident, port, host in [(FIRST, '8788', 'first.example'), (SECOND, '8789', 'second.example')]:
        result = subprocess.run(['bash', str(source / 'install.sh'), 'proxy', ident, port, 'systemd',
                                 'caddy', host, '-', '-'], env=env, capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f'MCP_CANDIDATE_URL=https://{host}/mcp\n'
        site = main.parent / 'yieldcraft.d' / f'{prefix(ident)}-mcp.caddy'
        assert f'{host} {{' in site.read_text() and f'127.0.0.1:{port}' in site.read_text()
    assert main.read_text().count('import ') == 1
    assert main.read_text().startswith('operator.example')
    assert len(list((main.parent / 'yieldcraft.d').iterdir())) == 2


def test_reconfigure_rejects_daemon_in_demo_and_changes_to_oauth_hostname(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOYMENT))
    rewrite = importlib.import_module('reconfigure').rewrite
    config = 'finpred_root = "/opt/finpred"\nbind = "127.0.0.1"\nport = 8788\nauth_required = false\n'
    with pytest.raises(ValueError, match='authenticated'):
        rewrite(config, 8788, '/opt/finpred', '1', '=')
    with pytest.raises(ValueError, match='OAuth'):
        rewrite(config + 'oauth_issuer = "https://issuer.example"\n', 8788, '/opt/finpred', '=', 'new.example')
    assert rewrite(config, 8788, '/opt/finpred', '0', '=') == config
