#!/usr/bin/env bash
# Optional build: no GTK, X11 server, or On1x compiler needed at this step.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
root=$(cd -- "$here/../../.." && pwd)
mulib=${MULIB_ROOT:-"$root/third_party/mulib"}
exe=${POINDEXTER_GUI_EXE:-"$root/build/poindexter/poindexter-gui"}
[[ -r "$mulib/include/mulib-immgtk-native.h" ]] || {
  echo 'Poindexter GUI: set MULIB_ROOT to the pinned MuLIB checkout' >&2
  exit 2
}
pkg-config --print-errors --exists x11
. "$root/bin/build-env.sh"
finpred_build_env "$root"
read -r -a flags <<< "$(pkg-config --cflags --libs x11)"
mkdir -p -- "$(dirname -- "$exe")"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror \
  -I"$mulib/include" "$here/main.c" "$here/worksheet.c" \
  -o "$exe" "${flags[@]}" -lm
printf 'Built %s (default worksheet worker: %s/poindexter-grid)\n' "$exe" "$(dirname -- "$exe")"
