#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)
cd "$ROOT"
MULIB_ROOT=$ROOT/third_party/mulib
STD=$MULIB_ROOT/on1x/stdlib
ON1XC=${ON1XC:-"$ROOT/build/caravansary/toolchain/on1xc"}
CC=clang
CXX=clang++
TMPDIR=$ROOT/build/caravansary/W2/tmp
FINPRED_BUILD_DIR=build/caravansary/W2/out
export CC CXX TMPDIR FINPRED_BUILD_DIR
if [ ! -x "$ON1XC" ]; then
    echo 'providers: set ON1XC to the pinned Clang-built On1x compiler' >&2
    exit 2
fi
mkdir -p -- "$TMPDIR" "$FINPRED_BUILD_DIR"
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" \
    "$ROOT/plugins/caravansary/examples/providers/check.on1x" \
    --backend c11 --cc clang --on1xc "$ON1XC" --stdlib "$STD" --mulib-root "$MULIB_ROOT" \
    -I "$ROOT" -I "$MULIB_ROOT/kernels" \
    --cflag=-D_POSIX_C_SOURCE=200809L --cflag=-pthread --cflag=-ldl --cflag=-lm --cflag=-lcrypto \
    --extra-c "$STD/html/runtime.c" --extra-c "$STD/elvi/runtime.c" --extra-c "$STD/elvi/bridge.c" \
    --extra-c "$ROOT/plugins/caravansary/stdlib/provider/kernels.c" \
    --extra-c "$ROOT/plugins/caravansary/planning/host.c" \
    -o "$FINPRED_BUILD_DIR/provider-check"
"$FINPRED_BUILD_DIR/provider-check"
