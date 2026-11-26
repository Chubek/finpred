#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
if [ "$#" -ne 0 ]; then
  echo 'caravansary-market: build takes no arguments' >&2
  exit 2
fi
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
if [ ! -x "$ON1XC" ]; then
  echo 'caravansary-market: missing On1x compiler; run make mulib or set ON1XC' >&2
  exit 2
fi
CC=clang CXX=clang++
export CC CXX
finpred_build_env "$ROOT"
plugin=$ROOT/plugins/caravansary
out=$(finpred_cli_output_dir "$ROOT")/finpred-caravansary-market
probe=$out-probe-v1
mkdir -p -- "$(dirname -- "$out")"
stage=$(mktemp -- "${out}.XXXXXXXX")
probe_stage=
trap 'rm -f -- "$stage" "${probe_stage:-$stage}"' EXIT
trap 'exit 1' HUP INT TERM
probe_stage=$(mktemp -- "${probe}.XXXXXXXX")

build_entry() {
  entry=$1
  shift
  python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" "$plugin/market_cli/$entry.on1x" \
    --backend c11 --cc "$CC" --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
    --cflag=-DON1X_DATA_MAX_TEXT=33554432u --cflag=-DON1X_DATA_MAX_POOL=268435456u \
    --cflag=-DON1X_DATA_MAX_NODES=2097152u \
    --cflag=-D_POSIX_C_SOURCE=200809L --cflag=-pthread --cflag=-ldl --cflag=-lm \
    -I "$ROOT" -I "$plugin" -I "$MULIB_ROOT/kernels" \
    --extra-c "$plugin/planning/host.c" --cflag=-lcrypto "$@"
}

build_entry main -o "$stage" \
  --extra-c "$plugin/stdlib/geo/geodesy.c" --extra-c "$plugin/market_cli/probe_bridge.c"
build_entry probe_main -o "$probe_stage" --extra-c "$plugin/market_cli/probe_input.c" \
  --extra-c "$MULIB_ROOT/on1x/stdlib/html/runtime.c" \
  --extra-c "$MULIB_ROOT/on1x/stdlib/elvi/runtime.c" \
  --extra-c "$MULIB_ROOT/on1x/stdlib/elvi/bridge.c" \
  --extra-c "$plugin/stdlib/provider/kernels.c"
mv -fT -- "$probe_stage" "$probe"
mv -fT -- "$stage" "$out"
