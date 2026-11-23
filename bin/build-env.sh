# Sourced by build scripts (not runtime launchers).
finpred_build_env() {
  TMPDIR=$(realpath -m -- "${TMPDIR:-$1/build/tmp}") || return
  mkdir -p -- "$TMPDIR" || return
  # Build tools import modules from the MuLIB source checkout.
  export TMPDIR PYTHONDONTWRITEBYTECODE=1
}
