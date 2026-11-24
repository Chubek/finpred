#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
finpred_build_env "$ROOT"
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
out=${1:-"$(finpred_dragnet_output_dir "$ROOT")"}
mkdir -p "$out"
out=$(realpath "$out")
pkg-config --atleast-version=7.85 libcurl
# Embed the selected checkout's exact provider bytes; runtime cwd/environment
# cannot substitute a different provider host or selector.
python3 - "$MULIB_ROOT" "$out/providers.on1x" "$ROOT" "$ON1XC" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
lines = []
subject = hashlib.sha256()
for name in ("Google", "Bing"):
    source = (root / f"library/elvis/{name}.elvs").read_text()
    if "$" in source:
        raise SystemExit("unexpected On1x interpolation in provider")
    lines.append(f"fn {name.lower()}() -> string {{ return {json.dumps(source)}; }}\n")
    subject.update(name.encode() + b"\0" + source.encode() + b"\0")
repo = Path(sys.argv[3])
for path in (
    repo / "plugins/dragnet/source/main.on1x",
    repo / "plugins/dragnet/source/hospitality.on1x",
    repo / "plugins/dragnet/native/kernels.c",
    repo / "plugins/dragnet/build.sh",
    repo / "source/core/contracts.on1x",
    repo / "source/core/csv.on1x",
    repo / "source/core/date.on1x",
    repo / "source/core/money.on1x",
    repo / "source/core/format.on1x",
    repo / "source/core/dragnet_wire.on1x",
    Path(sys.argv[4]),
):
    subject.update(hashlib.sha256(path.read_bytes()).digest())
# Source headers and standard library affect native/runtime semantics too.
for parent, pattern in ((root / "include", "*.h"), (root / "on1x/stdlib", "*.on1x"),
                        (root / "on1x/runtime", "*")):
    for path in sorted(parent.rglob(pattern)):
        if path.is_file():
            subject.update(str(path.relative_to(root)).encode() + b"\0")
            subject.update(hashlib.sha256(path.read_bytes()).digest())
identity = f"dragnet.search@1:sha256:{subject.hexdigest()}"
lines.append(f'fn identity() -> string {{ return "{identity}"; }}\n')
Path(sys.argv[2]).write_text("".join(lines))
PY
# The explicit extra-C boundary is a trusted application adapter, not a
# self-signed KernelBind profile. Do not expose it to untrusted plugins.
set --
for flag in $(pkg-config --cflags --libs libcurl); do
  set -- "$@" "--cflag=$flag"
done
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" \
  "$ROOT/plugins/dragnet/source/main.on1x" --backend c11 --cc "${CC:-cc}" \
  --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" -I "$ROOT/source" -I "$out" \
  --extra-c "$ROOT/plugins/dragnet/native/kernels.c" \
  "--cflag=-I$MULIB_ROOT/include" --cflag=-lm "$@" -o "$out/dragnet"
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" \
  "$ROOT/plugins/dragnet/source/consumer_main.on1x" --backend c11 --cc "${CC:-cc}" \
  --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" -I "$ROOT/source" -I "$ROOT" \
  -o "$out/finpred-dragnet"
