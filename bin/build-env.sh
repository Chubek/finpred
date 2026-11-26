# Sourced by build scripts.
finpred_build_env() {
  TMPDIR=$(realpath -m -- "${TMPDIR:-$1/build/tmp}") || return
  mkdir -p -- "$TMPDIR" || return
  # Build tools import modules from the MuLIB source checkout.
  export TMPDIR PYTHONDONTWRITEBYTECODE=1
}

finpred_mulib_build_dir() {
  case ${FINPRED_MULIB_BUILD_DIR:-} in
    /*) realpath -m -- "$FINPRED_MULIB_BUILD_DIR" ;;
    *) realpath -m -- "$1/${FINPRED_MULIB_BUILD_DIR:-build/mulib/on1x}" ;;
  esac
}
