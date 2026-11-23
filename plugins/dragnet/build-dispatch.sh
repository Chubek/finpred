#!/bin/sh
# Build one independently executable, offline, statically linked Source host.
# Based on the existing frozen CSV On1xfile build staging (no symlinks).
set -eu
if [ "$#" -ne 1 ]; then echo "usage: $0 OUTPUT_DIRECTORY" >&2; exit 2; fi
pkg=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$pkg/../.." && pwd)
. "$root/bin/build-env.sh"
mulib=$(realpath "${MULIB_ROOT:-$root/third_party/mulib}")
compiler=$(realpath "${ON1XC:-$(finpred_mulib_build_dir "$root")/on1xc}")
out=$(realpath -m -- "$1")
finpred_build_env "$root"
work=$(mktemp -d "$TMPDIR/dragnet-dispatch.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$work/source/plugins"
cp -R "$pkg/source/." "$work/source/"  # includes the new registry and host
cp -R "$root/plugins/yieldcraft" "$work/source/plugins/"
for dep in core algorithms sdk; do
  mkdir "$work/source/$dep"
  cp "$root/source/$dep/On1xfile.m" "$root/source/$dep/"*.on1x "$work/source/$dep/"
done
cat > "$work/On1xfile" <<'MANIFEST'
on1xfile 1
kind executable
name "dragnet-source-dispatch"
directory "source"
target "dragnet-source-dispatch" "source/dispatch_host.on1x"
backend c11
MANIFEST
# The existing frozen CSV build intentionally declares one module only.
# Declare additional pure modules in this disposable build, not in its manifest.
cat > "$work/source/On1xfile.m" <<'MANIFEST'
on1xfile 1
source "dispatch_host.on1x"
MANIFEST
cat > "$work/source/dragnet/On1xfile.m" <<'MANIFEST'
on1xfile 1
library "frozen_csv.on1x"
library "frozen_crossref.on1x"
library "public_feeds.on1x"
library "source_registry.on1x"
MANIFEST
python3 "$mulib/on1x/tools/on1x-project.py" build "$work" --offline \
  --on1xc "$compiler" --mulib-root "$mulib" --output-dir "$out"
