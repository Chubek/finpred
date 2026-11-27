#!/bin/sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/../../.." && pwd)
. "$root/bin/build-env.sh"
mulib=${MULIB_ROOT:-"$root/third_party/mulib"}
on1xc=${ON1XC:-"$(finpred_mulib_build_dir "$root")/on1xc"}
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
trap 'rm -f -- "$work/parser.py" "$work/tables.on1x" "$work/.on1xfmt"; rmdir -- "$work"' EXIT
trap 'exit 1' HUP INT TERM

perl "$mulib/on1x/third_party/libstone/cornerstone/LLSynth/scripts/llsynth.pl" \
  --mode=analyze -T python3 --driver-mode=library \
  -o "$work/parser.py" "$here/CaravanScript.llsynth"
python3 "$mulib/on1x/stdlib/llsynth/pack_tables.py" "$work/parser.py" >"$work/tables.on1x"
cp "$root/.on1xfmt" "$work/.on1xfmt"
"$on1xc" fmt "$work/tables.on1x" --inplace
if [ "$mode" = --check ]; then
  cmp "$work/tables.on1x" "$here/tables.on1x"
else
  cp "$work/tables.on1x" "$here/tables.on1x"
fi
