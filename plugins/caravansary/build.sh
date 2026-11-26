#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
CC=${CC:-clang}
CXX=${CXX:-clang++}
for compiler in "$CC" "$CXX"; do
  case $("$compiler" --version 2>/dev/null | sed -n '1p') in
    *'clang version '*) ;;
    *) echo 'caravansary: building requires Clang and Clang++' >&2; exit 2 ;;
  esac
done
export CC CXX
if [ ! -x "$ON1XC" ]; then
  echo 'caravansary: missing On1x compiler; run make mulib or set ON1XC' >&2
  exit 2
fi
finpred_build_env "$ROOT"
out=$(finpred_cli_output_dir "$ROOT")/finpred-caravansary
entry=main
if [ "$#" -gt 1 ]; then
  echo 'caravansary: expected at most one build mode' >&2
  exit 2
fi
case ${1:-} in
  '') ;;
  --all)
    sh "$0"
    sh "$0" --market
    FINPRED_BUILD_DIR=$(finpred_cli_output_dir "$ROOT")
    export FINPRED_BUILD_DIR
    exec sh "$ROOT/plugins/caravansary/jobs/build.sh" ;;
  --market) exec sh "$ROOT/plugins/caravansary/market_cli/build.sh" ;;
  --check-frontend) entry=frontend/tests/main ;;
  --check-programming) entry=examples/programming/main ;;
  --check-planning) entry=planning/check ;;
  --check-coverage) entry=coverage/check ;;
  --check-credentials) entry=check_credentials ;;
  --check-booking) entry=check_booking ;;
  --check-review) entry=check_review ;;
  --check-metrics) entry=metrics/test_transform ;;
  *) echo 'caravansary: unrecognized build mode' >&2; exit 2 ;;
esac
case "$entry" in
  frontend/tests/main|examples/programming/main) set -- ;;
  metrics/test_transform) set -- --stdppx checks ;;
  planning/check|coverage/check|check_credentials|check_review)
    set -- --extra-c "$ROOT/plugins/caravansary/planning/host.c" --cflag=-lcrypto ;;
  *) set -- --extra-c "$ROOT/plugins/caravansary/planning/host.c" --cflag=-lcrypto \
            --extra-c "$ROOT/plugins/caravansary/booking_transport.c" --cflag=-lcurl ;;
esac
mkdir -p -- "$(dirname -- "$out")"
stage=$(mktemp -- "${out}.XXXXXXXX")
trap 'rm -f -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" "$ROOT/plugins/caravansary/$entry.on1x" \
  --backend c11 --cc "$CC" --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
  --cflag=-DON1X_DATA_MAX_TEXT=33554432u --cflag=-DON1X_DATA_MAX_POOL=268435456u \
  --cflag=-DON1X_DATA_MAX_NODES=2097152u \
  -I "$ROOT" -I "$ROOT/plugins/caravansary" -o "$stage" "$@"
if [ "$entry" = main ]; then
  mv -fT -- "$stage" "$out"
else
  (cd "$ROOT" && "$stage")
fi
