#!/bin/sh
# The raw Elvi kernel links only into the offline decoder, not into On1x.
set -eu
if [ "$#" -gt 1 ]; then echo "usage: $0 [OUTPUT_DIRECTORY]" >&2; exit 2; fi
pkg=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$pkg/../.." && pwd)
mulib=$(realpath "${MULIB_ROOT:-$root/third_party/mulib}")
compiler=$(realpath "${ON1XC:-$root/build/mulib/on1x/on1xc}")
out=$(realpath -m -- "${1:-$root/build/dragnet-crossref}")
mkdir -p -- "$out"
. "$root/bin/build-env.sh"
finpred_build_env "$root"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
  -isystem "$mulib/include" "$pkg/crossref_capture.c" -Wl,--gc-sections -lm \
  -o "$out/dragnet-crossref-capture"
python3 "$mulib/on1x/tools/on1x-build.py" "$pkg/source/crossref_host.on1x" \
  --backend c11 --on1xc "$compiler" --mulib-root "$mulib" \
  -I "$pkg/source" -I "$root/source" -o "$out/dragnet-crossref-import"
