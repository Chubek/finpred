"""Offline tests for the read-only deployment endpoint lookup."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[1]
DEPLOYMENT = ADDON / 'deployment'
URL = 'https://mcp.example.net/mcp'
QUICK = 'https://latest-quick-host.trycloudflare.com'
SENTINEL = 'mock-sensitive-output'


@pytest.fixture
def lookup(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(DEPLOYMENT))
    module = importlib.import_module('show_endpoint')
    monkeypatch.setattr(module, 'CONFIG', tmp_path / 'config.toml')
    monkeypatch.setattr(module, 'LOGS', tmp_path)
    return module


def test_configured_url_does_not_require_log(lookup, tmp_path):
    assert lookup.existing_endpoint({'public_url': URL}, tmp_path / 'missing') == URL


@pytest.mark.parametrize('url', [
    None, False, '', 'http://mcp.example.net/mcp', 'https://mcp.example.net/mcp/',
    'https://mcp.example.net/mcp?token=anything', 'https://username@mcp.example.net/mcp',
    'https://mcp.example.net:443/mcp', 'https://mcp.example.net./mcp',
    'https://mcp.example.net/mcp\n', f'https://{"a" * 64}.example/mcp',
    f'https://{".".join(["a" * 63] * 4)}/mcp',
])
def test_invalid_explicit_url_does_not_fall_back_to_logs(lookup, tmp_path, url):
    (tmp_path / 'cloudflared.log').write_text(QUICK + '\n')
    with pytest.raises(ValueError):
        lookup.existing_endpoint({'public_url': url}, tmp_path)


def test_quick_tunnel_uses_latest_valid_hostname(lookup, tmp_path):
    (tmp_path / 'cloudflared.log').write_text(
        'launch info | https://first-host.trycloudflare.com |\n'
        + json.dumps({'level': 'info', 'message': f'|   {QUICK}   |'}) + '\n'
        'https://-bad.trycloudflare.com\n'
        'https://bad-.trycloudflare.com\n'
        'https://a.b.trycloudflare.com\n'
        'https://bad.trycloudflare.com.other.example\n'
        'https://bad.trycloudflare.com.\n'
        'https://bad.trycloudflare.com@other.example\n'
        'https://bad.trycloudflare.com:443\n'
        'https://bad.trycloudflare.com?query=x\n'
        'https://bad.trycloudflare.com\r.other.example\n'
        'https://bad.trycloudflare.com/elsewhere\n'
        'https://other.example/https://bad.trycloudflare.com\n'
        'http://bad.trycloudflare.com\n'
    )
    assert lookup.existing_endpoint({}, tmp_path) == QUICK + '/mcp'


def test_quick_tunnel_rejects_ambiguity_and_only_checks_bounded_tail(lookup, tmp_path, monkeypatch):
    log = tmp_path / 'cloudflared.log'
    log.write_text(f'{QUICK} https://another-host.trycloudflare.com\n')
    with pytest.raises(ValueError, match='ambiguous'):
        lookup.existing_endpoint({}, tmp_path)
    monkeypatch.setattr(lookup, 'LOG_TAIL', 256)
    log.write_text(QUICK + '\n' + 'padding\n' * 128)
    with pytest.raises(ValueError, match='missing'):
        lookup.existing_endpoint({}, tmp_path)
    with log.open('a') as f:
        f.write(QUICK + '\n')
    assert lookup.existing_endpoint({}, tmp_path) == QUICK + '/mcp'
    monkeypatch.setattr(lookup, 'LOG_TAIL', len(QUICK) + 1)
    assert lookup.existing_endpoint({}, tmp_path) == QUICK + '/mcp'
    log.write_text('incomplete-prefix' + QUICK + '\n')
    with pytest.raises(ValueError, match='missing'):
        lookup.existing_endpoint({}, tmp_path)


def test_quick_tunnel_never_follows_links_or_reads_pipes(lookup, tmp_path):
    unrelated = tmp_path / 'unrelated'
    unrelated.write_text(QUICK + '\n')
    log = tmp_path / 'cloudflared.log'
    log.symlink_to(unrelated)
    with pytest.raises(OSError):
        lookup.existing_endpoint({}, tmp_path)
    log.unlink()
    log.hardlink_to(unrelated)
    with pytest.raises(ValueError):
        lookup.existing_endpoint({}, tmp_path)
    log.unlink()
    os.mkfifo(log)
    with pytest.raises(ValueError):
        lookup.existing_endpoint({}, tmp_path)


@pytest.mark.parametrize('config, port, status, url', [
    ('port = 8788\n', '8788', 0, QUICK + '/mcp'),
    (f'port = 8888\npublic_url = "{URL}"\n', '8888', 0, URL),
    ('port = 8788\n', '8888', 54, None),
    ('port = true\n', '1', 54, None),
    ('port = "8788"\n', '8788', 54, None),
    ('port = 65536\n', '65536', 54, None),
    ('port =\n', '8788', 54, None),
    ('', '8788', 54, None),
    ('port = 8788\npublic_url = ""\n', '8788', 55, None),
])
def test_remote_validates_port_before_output(lookup, tmp_path, capsys, config, port, status, url):
    lookup.CONFIG.write_text(config)
    (tmp_path / 'cloudflared.log').write_text(QUICK + '\n')
    assert lookup.main([port]) == status
    result = capsys.readouterr()
    assert result.out == (f'MCP_CANDIDATE_URL={url}\n' if url else '')
    assert result.err == ''


@pytest.fixture
def mocked_show(tmp_path):
    bin_dir = tmp_path / 'fake-bin'
    bin_dir.mkdir()
    ssh = bin_dir / 'ssh'
    ssh.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
work = Path(os.environ['MOCK_DIR'])
(work / 'ssh-argv').write_text(json.dumps(sys.argv[1:]))
assert sys.stdin.buffer.read() == Path(os.environ['MOCK_HELPER']).read_bytes()
print({SENTINEL!r})
print({SENTINEL!r}, file=sys.stderr)
print(os.environ['MOCK_REPLY'])
sys.exit(int(os.environ['MOCK_RC']))
""")
    python = bin_dir / 'python3'
    python.write_text(f"""#!/bin/bash
if [[ $2 == --candidate ]]; then
    exec "{sys.executable}" "$@"
fi
touch "$MOCK_DIR/unexpected-python"
exit 1
""")
    ssh.chmod(0o755)
    python.chmod(0o755)
    env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', TMPDIR=str(tmp_path),
               MOCK_DIR=str(tmp_path), MOCK_HELPER=str(DEPLOYMENT / 'show_endpoint.py'),
               MOCK_REPLY=f'MCP_CANDIDATE_URL={URL}', MOCK_RC='0')

    def run(target, *args, **settings):
        return subprocess.run(['bash', str(ADDON / 'deploy.sh'), target, '--show-endpoint', *args],
                              cwd=tmp_path, env=dict(env, **settings), capture_output=True,
                              text=True, timeout=10)

    return run


@pytest.mark.parametrize('target', ['vps.example.net', 'deploy@vps.example.net'])
@pytest.mark.parametrize('url', [URL, QUICK + '/mcp'])
def test_show_endpoint_prints_only_url_via_strict_ssh(mocked_show, tmp_path, target, url):
    result = mocked_show(target, '--ssh', '--port', '8888', '--ssh-port', '2222',
                         '--identity', 'key file', MOCK_REPLY=f'MCP_CANDIDATE_URL={url}')
    assert result.returncode == 0, result.stderr
    assert result.stdout == url + '\n'
    assert result.stderr == ''
    args = json.loads((tmp_path / 'ssh-argv').read_text())
    assert {'-T', 'StrictHostKeyChecking=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes'} <= set(args)
    assert args[args.index('-p') + 1] == '2222'
    assert args[args.index('-i') + 1] == 'key file'
    assert args[-2] == target
    assert 'sudo -n -u "$u"' in args[-1] and args[-1].endswith(" - '8888'")
    assert not (tmp_path / 'unexpected-python').exists()
    assert not (tmp_path / 'yieldcraft-mcp.token').exists()
    assert not list(tmp_path.glob('tmp.*'))


@pytest.mark.parametrize('remote_rc, reply, message', [
    (255, '', 'SSH transport failed'),
    (54, f'MCP_CANDIDATE_URL={URL}', 'installed config'),
    (55, '', 'Quick Tunnel logs'),
    (0, '', 'exactly one valid MCP candidate'),
    (0, f'MCP_CANDIDATE_URL={URL}\nMCP_CANDIDATE_URL={URL}', 'exactly one valid MCP candidate'),
    (0, 'MCP_CANDIDATE_URL=https://mcp.example.net:443/mcp', 'exactly one valid MCP candidate'),
])
def test_show_endpoint_failure_never_leaks_reply(mocked_show, remote_rc, reply, message):
    result = mocked_show('vps.example.net', MOCK_RC=str(remote_rc), MOCK_REPLY=reply)
    assert result.returncode != 0
    assert result.stdout == ''
    assert message in result.stderr
    assert SENTINEL not in result.stderr and URL not in result.stderr


def test_show_endpoint_domain_is_an_optional_assertion(mocked_show):
    result = mocked_show('vps.example.net', '--domain', 'mcp.example.net')
    assert result.returncode == 0 and result.stdout == URL + '\n'
    result = mocked_show('vps.example.net', '-d', 'unexpected.example.net')
    assert result.returncode != 0 and result.stdout == ''
    assert 'matching any requested domain' in result.stderr


@pytest.mark.parametrize('flags', [
    ('--auth',), ('--no-auth',), ('--patch', '--no-auth'), ('--telnet', '--ssh'),
    ('--no-daemon',), ('--systemd',), ('--sysvinit',), ('--token-out', 'token'),
    ('--reverse-proxy', 'caddy'), ('--telnet-port', '2223'),
    ('--repo', 'https://g.example.net/o/p.git'), ('--ref', '0' * 40),
    ('--email', 'op@example.net'), ('--cloudflared-config', '/etc/cloudflared/yieldcraft.yml'),
])
def test_show_endpoint_rejects_install_options_without_connecting(mocked_show, tmp_path, flags):
    result = mocked_show('vps.example.net', '--dry-run', *flags)
    assert result.returncode != 0
    assert '--show-endpoint' in result.stderr
    assert not (tmp_path / 'ssh-argv').exists()


def test_show_endpoint_dry_run_does_not_connect(mocked_show, tmp_path):
    result = mocked_show('deploy@vps.example.net', '--dry-run')
    assert result.returncode == 0
    assert result.stdout == 'target=deploy@vps.example.net protocol=ssh action=show-endpoint port=8788 domain=existing\n'
    assert result.stderr == ''
    assert not (tmp_path / 'ssh-argv').exists()
