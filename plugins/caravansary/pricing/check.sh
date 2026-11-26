#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
if [ -z "${ON1XC:-}" ] || [ ! -x "$ON1XC" ]; then
  echo 'usage: ON1XC=/absolute/path/to/pinned/on1xc sh plugins/caravansary/pricing/check.sh' >&2
  exit 2
fi
export CC=clang CXX=clang++
export TMPDIR="$ROOT/build/caravansary/W4/tmp"
export FINPRED_BUILD_DIR=build/caravansary/W4/out
mkdir -p -- "$TMPDIR" "$ROOT/$FINPRED_BUILD_DIR"
stage=$(mktemp -- "$ROOT/$FINPRED_BUILD_DIR/pricing-check.XXXXXXXX")
trap 'rm -f -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" "$ROOT/plugins/caravansary/pricing/check.on1x" \
  --backend c11 --cc "$CC" --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
  --cflag=-DON1X_DATA_MAX_TEXT=33554432u --cflag=-DON1X_DATA_MAX_POOL=268435456u \
  --cflag=-DON1X_DATA_MAX_NODES=2097152u \
  --extra-c "$ROOT/plugins/caravansary/planning/host.c" --cflag=-lcrypto \
  -I "$ROOT" -I "$ROOT/plugins/caravansary" -o "$stage"
cd "$ROOT"
"$stage"
