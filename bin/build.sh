#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$MULIB_ROOT/build/on1x/on1xc"}
if [ ! -f "$MULIB_ROOT/on1x/tools/on1x-project.py" ]; then
  echo "Missing MuLIB at $MULIB_ROOT (set MULIB_ROOT or populate third_party/mulib)" >&2
  exit 2
fi
if [ ! -x "$ON1XC" ]; then
  echo "Missing compiled On1x compiler at $ON1XC (set ON1XC)" >&2
  exit 2
fi
cd "$ROOT"
# Compose the host and selected built-in packages in a disposable project;
# canonical plugin sources stay under plugins/.
out=$(realpath -m -- "${FINPRED_BUILD_DIR:-$ROOT/target/dev}")
mkdir -p "$(dirname -- "$out")"
work=$(mktemp -d "${TMPDIR:-/tmp}/finpred-project.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
cp "$ROOT/On1xfile" "$work/"
cp -R "$ROOT/source" "$work/source"
mkdir -p "$work/source/plugins" "$work/plugins/poindexter"
cp -R "$ROOT/plugins/yieldcraft" "$ROOT/plugins/scalar_diagnostics" "$work/source/plugins/"
cp -R "$ROOT/plugins/poindexter/On1xfile" "$ROOT/plugins/poindexter/src" "$work/plugins/poindexter/"
python3 "$ROOT/bin/on1x_grammar.py" "$work/on1xc" "$ON1XC" "$MULIB_ROOT"
python3 "$MULIB_ROOT/on1x/tools/on1x-project.py" build "$work" \
  --on1xc "$work/on1xc" --mulib-root "$MULIB_ROOT" --output-dir "$out"
