#!/usr/bin/env python3
"""Switch a deploy.sh-managed installation to its isolated public demo."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

NAME = 'yieldcraft-mcp'
BASE = Path('/opt') / NAME
ETC = Path('/etc') / NAME
STATE = Path('/var/lib') / NAME
LOGS = Path('/var/log') / NAME
SYSTEMD = Path(f'/etc/systemd/system/{NAME}.service')
SYSV = Path('/etc/init.d') / NAME
FAILURES = (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError)
ENDPOINT_FAILURES = (*FAILURES, ImportError)
KEEP = (
    'public_url', 'allowed_origins', 'timeout', 'max_concurrent',
    'max_artifact_bytes', 'max_project_bytes', 'max_request_bytes',
)


class PatchError(Exception):
    def __init__(self, code):
        self.code = code


def trusted(info):
    return info.st_uid == 0 and not info.st_mode & 0o022


def read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not trusted(info):
            raise ValueError('not a root-managed config')
        data = source.read(65_537)
    if len(data) > 65_536:
        raise ValueError('config is too large')
    return data, info


def service_command(expected):
    managers = []
    for kind, path, command in (
        ('systemd', SYSTEMD, ['/usr/bin/systemctl', 'restart', f'{NAME}.service']),
        ('sysvinit', SYSV, ['/usr/sbin/service', NAME, 'restart']),
    ):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or not trusted(info):
            raise ValueError('not a root-managed service definition')
        managers.append((kind, command))
    if len(managers) != 1 or expected not in ('auto', managers[0][0]):
        raise ValueError('service manager does not match')
    return managers[0][1]


def run(argv, *, timeout):
    return subprocess.run(argv, timeout=timeout, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def as_service_user(*argv):
    return ['/usr/sbin/runuser', '-u', NAME, '--', *argv]


def demo_state(path, user):
    def private_directory(directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != user.pw_uid or info.st_mode & 0o077:
            raise ValueError('not a private service directory')

    private_directory(path.parent)
    try:
        private_directory(path)
    except FileNotFoundError:
        if not run(as_service_user('/usr/bin/mkdir', '-m', '0700', '--', path), timeout=5):
            raise ValueError('could not create demo state directory')
        private_directory(path)


def public_config(current, demo):
    config = {key: current[key] for key in KEEP if key in current}
    config.update(
        finpred_root=current['finpred_root'], bind=current['bind'], port=current['port'],
        state_dir=str(demo), auth_required=False, enable_live=False, allow_llm=False,
        allowed_hosts=[], offer_hosts=[], daemon_autostart=False,
    )
    data = ''.join(f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in config.items())
    if tomllib.loads(data) != config:
        raise ValueError('invalid generated config')
    return config, data.encode()


def write_config(data, *, prefix, mode, gid):
    fd, name = tempfile.mkstemp(dir=ETC, prefix=prefix, suffix='.toml')
    path = Path(name)
    try:
        with os.fdopen(fd, 'wb') as target:
            os.fchown(target.fileno(), 0, gid)
            os.fchmod(target.fileno(), mode)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def endpoint(config):
    # -I excludes the script directory; import only the sibling shipped in
    # the allowlisted patch archive, not a module from the login environment.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from show_endpoint import existing_endpoint
    finally:
        sys.path.pop(0)
    return existing_endpoint(config, LOGS)


def local_probe(port, mode):
    try:
        return run([sys.executable, '-I', str(Path(__file__).with_name('probe.py')),
                    mode, str(port)], timeout=10)
    except subprocess.TimeoutExpired:
        return False


def wait_local(port, mode):
    deadline = time.monotonic() + 45
    while True:
        if local_probe(port, mode):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


def validate_existing(config, port, demo):
    if (type(config.get('port')) is not int or config['port'] != port
            or config.get('finpred_root') != str(BASE / 'finpred')
            or config.get('bind') != '127.0.0.1'
            or type(config.get('auth_required', True)) is not bool):
        raise ValueError('not a matching deployment')
    previous_state = Path(config['state_dir'])
    if not previous_state.is_absolute():
        raise ValueError('invalid existing state path')
    if config.get('auth_required', True):
        previous_state, demo = previous_state.resolve(), demo.resolve()
        if previous_state.is_relative_to(demo) or demo.is_relative_to(previous_state):
            raise ValueError('public demo state would overlap private state')


def apply_patch(port, expected_init, expected_domain):
    path = ETC / 'config.toml'
    demo = STATE / 'public-demo'
    try:
        original, info = read_config(path)
        current = tomllib.loads(original.decode())
        validate_existing(current, port, demo)
        restart = service_command(expected_init)
        user = pwd.getpwnam(NAME)
    except FAILURES:
        raise PatchError(54) from None
    try:
        url = endpoint(current)
        if expected_domain != '-' and url != f'https://{expected_domain}/mcp':
            raise ValueError('existing domain does not match')
    except ENDPOINT_FAILURES:
        raise PatchError(55) from None
    candidate = None
    try:
        new_config, data = public_config(current, demo)
        demo_state(demo, user)
        if current == new_config and local_probe(port, '--local-demo'):
            return url
        candidate = write_config(data, prefix='.config-patch-', mode=0o640, gid=user.pw_gid)
        validate = ('from pathlib import Path; import sys; from yieldcraft_mcp.config import load; '
                    'sys.exit(load(Path(sys.argv[1])).auth_required is not False)')
        if not run(as_service_user(BASE / 'venv/bin/python', '-I', '-c', validate, candidate), timeout=15):
            raise ValueError('installed addon does not accept public demo config')
        write_config(original, prefix='config.pre-patch-', mode=0o600, gid=0)
    except FAILURES:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        raise PatchError(56) from None

    try:
        os.replace(candidate, path)
        if not run(restart, timeout=60) or not wait_local(port, '--local-demo'):
            raise ValueError('public demo startup failed')
    except FAILURES:
        try:
            restored = write_config(original, prefix='.config-restore-', mode=stat.S_IMODE(info.st_mode),
                                    gid=info.st_gid)
            try:
                os.replace(restored, path)
            finally:
                restored.unlink(missing_ok=True)
            if not run(restart, timeout=60) or not wait_local(port, '--local-ready'):
                raise ValueError('could not verify restored service')
        except FAILURES:
            raise PatchError(58) from None
        raise PatchError(57) from None
    finally:
        candidate.unlink(missing_ok=True)
    return url


def main(argv):
    if (os.geteuid() != 0 or len(argv) != 3 or not re.fullmatch(r'[1-9][0-9]{0,4}', argv[0])
            or int(argv[0]) > 65535):
        return 54
    try:
        fd = os.open(ETC, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return 54
    try:
        if not trusted(os.fstat(fd)):
            return 54
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 59
        port, expected_init, expected_domain = argv
        print('MCP_CANDIDATE_URL=' + apply_patch(int(port), expected_init, expected_domain))
    except PatchError as error:
        return error.code
    finally:
        os.close(fd)
    return 0


def interrupted(*_):
    raise InterruptedError('patch interrupted')


if __name__ == '__main__':
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    sys.exit(main(sys.argv[1:]))
