"""Pass a private, host-provisioned root descriptor to the C consumer."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

def copy_v1(root):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    files = json.loads((fixtures / "replay_v1.json").read_bytes())["files"]
    src, dst = root / "src", root / "dst"
    src.mkdir(mode=0o700)
    dst.mkdir(mode=0o700)
    keys = []
    for name in sorted(files):  # artifacts, then manifests
        match = re.fullmatch(r"(artifacts/blake3-|runs/)([0-9a-f]{64})\.txt", name)
        if not match:
            raise ValueError(name)
        keys.append(name[0] + match[2])
        path = src / name
        path.parent.mkdir(exist_ok=True, mode=0o700)
        path.write_bytes(files[name].encode("ascii"))
    a = os.open(src, os.O_RDONLY | os.O_DIRECTORY)
    b = os.open(dst, os.O_RDONLY | os.O_DIRECTORY)
    try:
        subprocess.run([sys.argv[1], "copy", str(a), str(b), *keys],
                       pass_fds=(a, b), check=True, timeout=30)
    finally:
        os.close(a)
        os.close(b)
    copied = {str(p.relative_to(dst)): p.read_bytes().decode("ascii")
              for p in dst.rglob("*") if p.is_file()}
    if copied != files:
        raise ValueError("native store did not preserve the archived v1 tree")
    print(f"native_store_v1_ok=true files={len(files)}")


with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="store-test-") as tmp:
    if sys.argv[2:] == ["copy-v1"]:
        copy_v1(Path(tmp))
    else:
        fd = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
        try:
            subprocess.run([sys.argv[1], str(fd)], pass_fds=(fd,), check=True, timeout=30)
        finally:
            os.close(fd)
