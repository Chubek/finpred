#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
here="$ROOT/plugins/caravansary/jobs"
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
stdlib="$MULIB_ROOT/on1x/stdlib"
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
export CC=clang CXX=clang++
export FINPRED_BUILD_DIR=${FINPRED_BUILD_DIR:-build/caravansary/W5/out}
export TMPDIR=${TMPDIR:-"$ROOT/build/caravansary/W5/tmp"}
finpred_build_env "$ROOT"
out=$(finpred_cli_output_dir "$ROOT")
mkdir -p -- "$out"
stage=$(mktemp -d -- "$out/.jobs-build.XXXXXXXX")
trap 'rm -f -- "$stage/main" "$stage/runner" "$stage/market_runner"; rmdir -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM

build() {
    "$CC" -std=c11 -Wall -Wextra -Wpedantic -Werror -O2 \
        -I "$MULIB_ROOT/kernels" -I "$stdlib" \
        "$here/state.c" "$here/market.c" "$here/kernels.c" "$stdlib/kron/runtime.c" "$stdlib/daemon/supervisor.c" \
        "$stdlib/http/probe/context.c" "$stdlib/http/probe/supervised.c" \
        "$here/$1.c" -lcrypto -pthread -ldl -lm -o "$stage/$1"
}
build main
build runner
build market_runner

# Serial deploy; the runner's named ABI must remain immutable at this filename.
exec 9>"$out/.jobs-build.lock"
flock -x 9
mv -fT -- "$stage/runner" "$out/finpred-caravansary-jobs-runner-v1"
mv -fT -- "$stage/market_runner" "$out/finpred-caravansary-jobs-runner-market-v1"
mv -fT -- "$stage/main" "$out/finpred-caravansary-jobs"
