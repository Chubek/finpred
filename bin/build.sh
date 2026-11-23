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
exec python3 "$MULIB_ROOT/on1x/tools/on1x-project.py" build "$ROOT" \
  --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT"
