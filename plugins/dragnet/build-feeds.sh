#!/bin/sh
# Standalone executables only; none are linked into the FinPRED CLI.
set -eu
if [ "$#" -gt 1 ]; then echo "usage: $0 [OUTPUT_DIRECTORY]" >&2; exit 2; fi
pkg=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$pkg/../.." && pwd)
mulib=$(realpath "${MULIB_ROOT:-$root/third_party/mulib}")
compiler=$(realpath "${ON1XC:-$root/build/mulib/on1x/on1xc}")
out=$(realpath -m -- "${1:-$root/build/dragnet-feeds}")
mkdir -p -- "$out"
. "$root/bin/build-env.sh"
finpred_build_env "$root"
flags=$(pkg-config --cflags libxml-2.0 jansson)
libs=$(pkg-config --libs libxml-2.0 jansson)
# Intentional flag splitting for pkg-config's argument lists.
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -pedantic -ffunction-sections \
  -fdata-sections -isystem "$mulib/include" $flags "$pkg/feed_decode.c" \
  -Wl,--gc-sections -lm $libs -o "$out/dragnet-feed-decode"
flags=$(pkg-config --cflags 'libcurl >= 7.85.0')
libs=$(pkg-config --libs libcurl)
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -pedantic $flags \
  "$pkg/feed_fetch.c" $libs -o "$out/dragnet-feed-fetch"
if [ "${DRAGNET_BUILD_LOOPBACK_FIXTURE:-0}" = 1 ]; then
  "${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -pedantic -DDRAGNET_LOOPBACK_TEST \
    $flags "$pkg/feed_fetch.c" $libs -o "$out/dragnet-feed-fetch-loopback-fixture"
fi
python3 "$mulib/on1x/tools/on1x-build.py" "$pkg/source/feed_host.on1x" \
  --backend c11 --on1xc "$compiler" --mulib-root "$mulib" \
  -I "$pkg/source" -I "$root/source" -o "$out/dragnet-feed-normalize"
