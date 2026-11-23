#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
finpred_build_env "$ROOT"
mulib=$(realpath -m -- "${MULIB_ROOT:-$ROOT/third_party/mulib}")
libstone="$mulib/on1x/third_party/libstone"
out=$(finpred_mulib_build_dir "$ROOT")
cmake=${CMAKE:-cmake}

die() {
  printf '%s\n' "$*" >&2
  exit 2
}

# Do not let Git discover the enclosing repository when a submodule is absent.
check_pin() {
  checkout=$1 expected=$2
  top=$(git -C "$checkout" rev-parse --show-toplevel 2>/dev/null) || top=
  [ "$top" = "$checkout" ] || die "Missing Git checkout at $checkout; see INSTALL.md"
  actual=$(git -C "$checkout" rev-parse HEAD)
  [ -n "$expected" ] && [ "$actual" = "$expected" ] ||
    die "Submodule pin mismatch at $checkout: expected ${expected:-missing}, got $actual; see INSTALL.md"
}

if [ "$mulib" = "$(realpath -m -- "$ROOT/third_party/mulib")" ]; then
  expected=$(git -C "$ROOT" ls-tree HEAD -- third_party/mulib | awk '$1 == "160000" {print $3}')
  check_pin "$mulib" "$expected"
fi
[ -f "$mulib/on1x/CMakeLists.txt" ] || die "Missing MuLIB at $mulib; see INSTALL.md"
expected=$(git -C "$mulib" ls-tree HEAD -- on1x/third_party/libstone | awk '$1 == "160000" {print $3}')
check_pin "$libstone" "$expected"
[ -f "$libstone/scripts/asdl.pl" ] && [ -f "$libstone/scripts/aurocks.pl" ] ||
  die "Missing LibStone generators at $libstone; see INSTALL.md"

"$cmake" -S "$mulib/on1x" -B "$out" \
  -DBUILD_TESTING=ON -DON1X_REQUIRE_LIBSTONE=ON \
  -DON1X_BUILD_NATIVE_PPX=ON -DON1X_BUILD_GRAMMAREMBED=ON \
  -DON1X_LIBSTONE_ROOT="$libstone"
"$cmake" --build "$out" --parallel "${MULIB_JOBS:-4}" \
  --target on1xc on1x_ppx_GrammarEmbed
