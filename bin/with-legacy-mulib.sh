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
  case "${entry##*/}" in
    # The upstream manifest loader requires these paths to be inside its
    # selected root. Preserve its confinement check with real snapshot data.
    MANIFEST.yaml|kernels|manual) cp -a --reflink=auto -- "$entry" "$view/" ;;
    *) ln -s -- "$entry" "$view/" ;;
  esac
done
ln -s -- kernels "$view/include"
export MULIB_ROOT="$view"
"$@"
