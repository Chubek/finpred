#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
finpred_build_env "$ROOT"
mulib=$(realpath -m -- "${MULIB_ROOT:-$ROOT/third_party/mulib}")
libstone="$mulib/on1x/third_party/libstone"
out=$(finpred_mulib_build_dir "$ROOT")
cmake=${CMAKE:-cmake}
cc=${CC:-clang}
cxx=${CXX:-clang++}

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
[ -f "$libstone/scripts/asdl.pl" ] && [ -f "$libstone/cornerstone/Aurocks/CMakeLists.txt" ] ||
  die "Missing LibStone generators at $libstone; see INSTALL.md"
for compiler in "$cc" "$cxx"; do
  case $("$compiler" --version 2>/dev/null | sed -n '1p') in
    *'clang version '*) ;;
    *) die "The pinned compiler build requires Clang and Clang++; set CC=clang CXX=clang++" ;;
  esac
done

# FFIHandler on the pinned MuLIB revision needs a build-host Cephyr shared
# library even when consumers only use the On1x C11 backend.
if [ -z "${CEPHYR_LIBRARY:-}" ]; then
  cephyr="$out/cephyr-host"
  cephyr_src="$libstone/cornerstone/Cephyr"
  runtime="$cephyr/native-runtime"
  # The LibStone pin replaced Aurocks with the native generator used by
  # on1xc, but Cephyr's qld subproject still uses the old Perl CLI. Recover
  # the exact upstream generator blob in the build tree, not in LibStone.
  mkdir -p -- "$cephyr"
  qld_aurocks="$cephyr/aurocks-qld.pl"
  qld_stage=$(mktemp "$qld_aurocks.XXXXXXXX")
  trap 'rm -f -- "$qld_stage"' EXIT
  git -C "$libstone" cat-file blob cbf0cddc364ca1a48d55d51abc5107d71b1b16a9 >"$qld_stage" ||
    die "Missing historical Aurocks generator in LibStone; use a full checkout or set CEPHYR_LIBRARY"
  if ! cmp -s "$qld_stage" "$qld_aurocks"; then
    mv -fT -- "$qld_stage" "$qld_aurocks"
  fi
  # Cephyr uses its own freestanding headers and runtime, so Clang can
  # cross-compile these packages without a target sysroot or GCC.
  for tuple in AMD64:x86_64-linux-gnu AArch64:aarch64-linux-gnu RISCV64IM:riscv64-linux-gnu; do
    arch=${tuple%%:*}
    target=${tuple#*:}
    if [ ! -f "$runtime/$arch/crt0.o" ] || [ ! -f "$runtime/$arch/libc.a" ]; then
      CC="$cc" AR="${LLVM_AR:-llvm-ar}" CEPHYR_LIBC_TARGET="$target" \
        CEPHYR_LIBC_TARGET_OPTION="--target=$target" CEPHYR_LIBC_CFLAGS='-fno-pic -fno-pie' \
        sh "$cephyr_src/stdlib/build.sh" "$runtime/$arch"
    fi
  done
  "$cmake" -S "$libstone/cornerstone/Cephyr" -B "$cephyr" \
    -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
    -DCEPHYR_BUILD_TESTS=OFF -DCEPHYR_INSTALL_PYTHON=OFF \
    -DYELLOWSTONE_LDSCRIPT_AUROCKS="$qld_aurocks" \
    -DCEPHYR_PREBUILT_RUNTIME_ROOT="$runtime"
  "$cmake" --build "$cephyr" --parallel "${MULIB_JOBS:-4}" --target cephyr_compiler
  CEPHYR_LIBRARY="$cephyr/libcephyr.so"
fi
[ -f "$CEPHYR_LIBRARY" ] || die "Missing build-host Cephyr shared library: $CEPHYR_LIBRARY"
CEPHYR_LIBRARY=$(realpath -- "$CEPHYR_LIBRARY")
"$cmake" -S "$mulib/on1x" -B "$out" \
  -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
  -DCMAKE_PROJECT_libchomsky3_INCLUDE="$ROOT/bin/chomsky3-clang.cmake" \
  -DBUILD_TESTING=ON -DON1X_REQUIRE_LIBSTONE=ON \
  -DON1X_BUILD_NATIVE_PPX=ON -DON1X_BUILD_GRAMMAREMBED=ON \
  -DON1X_LIBSTONE_ROOT="$libstone" -DON1X_STDFFI_CEPHYR_LIBRARY="$CEPHYR_LIBRARY"
"$cmake" --build "$out" --parallel "${MULIB_JOBS:-4}" \
  --target on1xc on1x_ppx_GrammarEmbed
