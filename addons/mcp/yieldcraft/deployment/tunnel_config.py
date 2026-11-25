#!/usr/bin/env python3
"""Check a preprovisioned cloudflared config as the tunnel service account."""
import os
import stat
import sys
from pathlib import Path

import yaml


def read_private(path, limit=1_048_576):
    if not path.is_absolute():
        path = Path.cwd() / path
    # Check the parent tree as well as the file: enclosing writable directories
    # could let another account replace an otherwise private config or credential.
    parent = path.parent
    for directory in (parent, *parent.parents):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or info.st_mode & 0o022):
            raise ValueError('untrusted directory')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or info.st_mode & 0o037 or (info.st_mode & 0o040 and info.st_gid != os.getegid())):
            raise ValueError('untrusted or shared file')
        data = f.read(limit + 1)
        if len(data) > limit:
            raise ValueError('file exceeds size bound')
        return data


def validate_config(path):
    # Inspect only the top-level scalar keys cloudflared consumes. Reject
    # duplicate/merge keys and do not produce a second copy of the YAML on disk.
    node = yaml.compose(read_private(path), Loader=yaml.SafeLoader)
    if not isinstance(node, yaml.MappingNode):
        raise ValueError('expected named tunnel configuration mapping')
    keys = set()
    for key, value in node.value:
        if key.tag != 'tag:yaml.org,2002:str' or key.value in keys:
            raise ValueError('unsupported or duplicate config key')
        keys.add(key.value)
        if key.value in ('credentials-file', 'cred-file', 'token-file', 'origincert'):
            if value.tag != 'tag:yaml.org,2002:str' or not value.value:
                raise ValueError('expected credential file path')
            read_private(Path(value.value).expanduser())


def main(argv):
    try:
        if len(argv) != 1:
            raise ValueError('expected tunnel config path')
        validate_config(Path(argv[0]))
        return 0
    except (OSError, RuntimeError, ValueError, yaml.YAMLError):
        print('Named tunnel requires a private config and credential files readable by the service account',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
