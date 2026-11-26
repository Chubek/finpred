#!/bin/sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/../../.." && pwd)
mulib=${MULIB_ROOT:-"$root/third_party/mulib"}
mode=${1:-write}
case "$mode" in
  write|--check) ;;
  *) echo "usage: sh generate-tables.sh [--check]" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "usage: sh generate-tables.sh [--check]" >&2
  exit 2
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/caravansary-grammar.XXXXXXXX")
trap 'rm -f -- "$work/parser.py" "$work/tables.on1x"; rmdir -- "$work"' EXIT
trap 'exit 1' HUP INT TERM

perl "$mulib/on1x/third_party/libstone/cornerstone/LLSynth/scripts/llsynth.pl" \
  --mode=analyze -T python3 --driver-mode=library \
  -o "$work/parser.py" "$here/CaravanScript.llsynth"
python3 "$mulib/on1x/stdlib/llsynth/pack_tables.py" "$work/parser.py" >"$work/tables.on1x"
if [ "$mode" = --check ]; then
  cmp "$work/tables.on1x" "$here/tables.on1x"
else
  cp "$work/tables.on1x" "$here/tables.on1x"
fi
