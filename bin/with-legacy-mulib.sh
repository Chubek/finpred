#!/bin/sh
# Some unchanged plugin build entry points still expect MuLIB's old include/
# spelling. Give only those commands a disposable view of the same sources.
set -eu
[ "$#" -gt 0 ] || { echo "Usage: $0 COMMAND [ARG ...]" >&2; exit 2; }
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sdk=$(realpath -m -- "${MULIB_ROOT:-$root/third_party/mulib}")
if [ -d "$sdk/include" ] || [ ! -d "$sdk/kernels" ]; then
  export MULIB_ROOT="$sdk"
  exec "$@"
fi
. "$root/bin/build-env.sh"
finpred_build_env "$root"
view=$(mktemp -d -- "$TMPDIR/mulib-legacy.XXXXXXXX")
trap 'rm -rf -- "$view"' EXIT
trap 'exit 1' HUP INT TERM
for entry in "$sdk"/*; do
  ln -s -- "$entry" "$view/"
done
ln -s -- "$sdk/kernels" "$view/include"
export MULIB_ROOT="$view"
"$@"
