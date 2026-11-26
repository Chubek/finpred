#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)
plugin=$ROOT/plugins/caravansary
example=$plugin/examples/joe-litty-rooms
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
case "$#:${1:-}" in
  0:)
    reuse_market=false
    FINPRED_BUILD_DIR=${FINPRED_BUILD_DIR:-build/caravansary/W7/out}
    ;;
  1:--reuse-market) reuse_market=true ;;
  *)
    echo 'Usage: check.sh [--reuse-market]' >&2
    exit 2
    ;;
esac
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
TMPDIR=${TMPDIR:-"$ROOT/build/caravansary/W7/tmp"}
export MULIB_ROOT ON1XC TMPDIR FINPRED_BUILD_DIR
CC=clang CXX=clang++
export CC CXX
finpred_build_env "$ROOT"
if [ ! -x "$ON1XC" ]; then
  echo 'Joe Litty Rooms check: set ON1XC to the built pinned On1x compiler' >&2
  exit 2
fi
if "$reuse_market" && [ ! -x "$(finpred_cli_output_dir "$ROOT")/finpred-caravansary-market" ]; then
  echo 'Joe Litty Rooms check: --reuse-market requires a deployed market CLI in the selected build directory' >&2
  exit 2
fi
work=$(mktemp -d "$TMPDIR/joe-litty-rooms.XXXXXXXX")
trap 'rm -f -- "$work/parse" "$work/config.json" "$work/deny.json" "$work/result" "$work/error"; rmdir -- "$work"' EXIT
trap 'exit 1' HUP INT TERM

python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" "$example/check.on1x" \
  --backend c11 --cc "$CC" --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
  -I "$ROOT" -I "$plugin" -o "$work/parse"
(cd "$ROOT" && "$work/parse") > "$work/config.json"
python3 -I - "$work/config.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as parsed:
    config = json.load(parsed)
assert config["target"] == {
    "id": "joe-litty-rooms-reference",
    "name": "Joe Litty Rooms",
    "address": "Via Giovanni Giolitti 255, 00185 Rome, Italy",
    "type": "unverified",
    "latitude": "41.90",
    "longitude": "12.48",
    "currency": "EUR",
}
assert config["target_sources"]["booking_profile_reference"] == {
    "kind": "fixture",
    "fixture": "unbound-profile-reference",
    "extractor": "frozen",
    "profile_url": "https://www.booking.com/hotel/it/joe-litty-rooms.html",
}
assert config["discovery"]["sources"] == ["unbound_candidates"]
assert config["pricing"] == {"currency": "EUR", "floor_minor": 1, "ceiling_minor": 2}
assert "schedule" not in config
PY

if ! "$reuse_market"; then
  sh "$plugin/market_cli/build.sh"
fi
printf '%s\n' '{"kind":"caravansary.host-grants@1","grants":[]}' > "$work/deny.json"
if "$ROOT/bin/caravansary" scrape "$example/reference.caf" \
  --source booking_profile_reference --input-root "$example" --input-root "$work" \
  --host-grants "$work/deny.json" --as-of 2026-11-26T00:00:00Z \
  > "$work/result" 2> "$work/error"; then
  echo 'Joe Litty Rooms check: ungranted profile unexpectedly succeeded' >&2
  exit 1
fi
if [ -s "$work/result" ] ||
  ! grep -Fq 'no host grant for selected market source and operation: booking_profile_reference (scrape)' "$work/error"; then
  cat "$work/error" >&2
  echo 'Joe Litty Rooms check: expected a host-grant denial with no result' >&2
  exit 1
fi
printf '%s\n' 'Joe Litty Rooms: parsed offline; ungranted profile rejected.'
