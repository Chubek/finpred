# Sourced by the CLI build, launcher, and integration suite.
# A relative output directory is always relative to the FinPRED root.
finpred_cli_output_dir() {
  case ${FINPRED_BUILD_DIR:-} in
    /*) realpath -m -- "$FINPRED_BUILD_DIR" ;;
    *) realpath -m -- "$1/${FINPRED_BUILD_DIR:-build/dev}" ;;
  esac
}

finpred_cli_executable() {
  if [ -n "${FINPRED_EXE:-}" ]; then
    case $FINPRED_EXE in
      /*) printf '%s\n' "$FINPRED_EXE" ;;
      *) printf '%s\n' "$1/$FINPRED_EXE" ;;
    esac
  else
    cli_dir=$(finpred_cli_output_dir "$1") || return
    printf '%s/finpred\n' "$cli_dir"
  fi
}

finpred_dragnet_output_dir() {
  case ${FINPRED_DRAGNET_BUILD_DIR:-} in
    /*) realpath -m -- "$FINPRED_DRAGNET_BUILD_DIR" ;;
    *) realpath -m -- "$1/${FINPRED_DRAGNET_BUILD_DIR:-build/dragnet}" ;;
  esac
}
