#!/bin/sh
# Stage the plugin with the repository's own core modules: On1xfile does not
# admit parent traversal or symlinks in its declared inputs.
set -eu
if [ "$#" -gt 1 ]; then echo "usage: $0 [OUTPUT_DIRECTORY]" >&2; exit 2; fi
pkg=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$pkg/../.." && pwd)
mulib=$(realpath "${MULIB_ROOT:-$root/third_party/mulib}")
compiler=$(realpath "${ON1XC:-$root/build/mulib/on1x/on1xc}")
out=$(realpath -m -- "${1:-$root/build/dragnet}")
. "$root/bin/build-env.sh"
finpred_build_env "$root"
work=$(mktemp -d "$TMPDIR/dragnet-project.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
cp "$pkg/On1xfile" "$work/"
cp -R "$pkg/source" "$work/source"
mkdir -p "$work/source/plugins"
cp -R "$root/plugins/yieldcraft" "$work/source/plugins/"
for dep in core algorithms sdk; do
  mkdir "$work/source/$dep"
  cp "$root/source/$dep/On1xfile.m" "$root/source/$dep/"*.on1x "$work/source/$dep/"
done
python3 "$mulib/on1x/tools/on1x-project.py" build "$work" --offline \
  --on1xc "$compiler" --mulib-root "$mulib" --output-dir "$out"
