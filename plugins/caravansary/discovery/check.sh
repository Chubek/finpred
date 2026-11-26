#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
export CC=clang CXX=clang++
export TMPDIR="$root/build/caravansary/W3/tmp"
export FINPRED_BUILD_DIR="$root/build/caravansary/W3/out"
mkdir -p -- "$TMPDIR" "$FINPRED_BUILD_DIR"
on1xc=${ON1XC:-"$root/build/caravansary/toolchain/on1xc"}
mulib=${MULIB_ROOT:-"$root/third_party/mulib"}
out="$FINPRED_BUILD_DIR/discovery-check"
python3 "$mulib/on1x/tools/on1x-build.py" "$root/plugins/caravansary/discovery/check.on1x" \
  --backend c11 --cc "$CC" --on1xc "$on1xc" --mulib-root "$mulib" \
  -I "$root" --extra-c "$root/plugins/caravansary/planning/host.c" \
  --extra-c "$root/plugins/caravansary/stdlib/geo/geodesy.c" --cflag=-lcrypto --cflag=-lm -o "$out"
"$out"
for invalid in latitude coordinate provider_error verify_excluded verify_duplicate_provider; do
  if "$out" "$invalid" >"$TMPDIR/discovery-$invalid.log" 2>&1; then
    printf '%s\n' "unexpected success: $invalid" >&2
    exit 1
  fi
done
grep -q 'outside WGS84 bounds' "$TMPDIR/discovery-latitude.log"
grep -q 'both latitude and longitude' "$TMPDIR/discovery-coordinate.log"
grep -q 'not a successful provider-observation' "$TMPDIR/discovery-provider_error.log"
grep -q 'eligible candidate' "$TMPDIR/discovery-verify_excluded.log"
grep -q 'multiple verified links to one property and provider' "$TMPDIR/discovery-verify_duplicate_provider.log"
