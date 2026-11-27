#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
if [ ! -f "$MULIB_ROOT/on1x/tools/on1x-build.py" ] || [ ! -f "$MULIB_ROOT/on1x/tools/on1x-project.py" ]; then
  echo "Missing MuLIB at $MULIB_ROOT (set MULIB_ROOT or populate third_party/mulib)" >&2
  exit 2
fi
if [ ! -x "$ON1XC" ]; then
  echo "Missing compiled On1x compiler at $ON1XC (run 'make mulib' or set ON1XC)" >&2
  exit 2
fi
MULIB_ROOT=$(realpath -- "$MULIB_ROOT")
ON1XC=$(realpath -- "$ON1XC")
finpred_build_env "$ROOT"
cd "$ROOT"
cc=${CC:-cc}
case "$cc" in
  /*) ;;
  */*) cc="$ROOT/$cc" ;;
esac
# Compose the host and selected built-in packages in a disposable project;
# canonical plugin sources stay under plugins/.
out=$(finpred_cli_output_dir "$ROOT")
mkdir -p "$(dirname -- "$out")"
# On1x v1 canonicalizes paths before it serializes the PPX input. Keep this
# source stage shallow and separate from the C/tool scratch (still TMPDIR).
stage=$(realpath -m -- "${FINPRED_STAGE_PARENT:-$ROOT/build}")
mkdir -p -- "$stage"
work=$(mktemp -d "$stage/p.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
cp -R "$ROOT/source" "$work/source"
cp -R "$ROOT/strategies/yieldcraft" "$work/source/"
mkdir -p "$work/source/plugins" "$work/plugins/poindexter"
cp -R "$ROOT/plugins/yieldcraft" "$ROOT/plugins/scalar_diagnostics" "$work/source/plugins/"
mkdir -p "$work/source/plugins/dragnet"
cp "$ROOT/plugins/dragnet/On1xfile.m" "$ROOT"/plugins/dragnet/*.on1x \
  "$work/source/plugins/dragnet/"
cp -R "$ROOT/plugins/poindexter/On1xfile" "$ROOT/plugins/poindexter/src" "$work/plugins/poindexter/"
python3 "$ROOT/bin/on1x_grammar.py" "$work/on1xc" "$ON1XC" "$MULIB_ROOT"
# The direct builder supports a trusted, statically linked C11 companion and
# resolves the MuLIB implementation closure from the pinned manifest.
# The GrammarEmbed adapter normalizes staged source spans to be relative
# to this cwd, which also lets the C driver remap its compilation directory.
(
  cd "$work"
  python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" source/main.on1x \
    --backend c11 --cc "$cc" --on1xc "$work/on1xc" --mulib-root "$MULIB_ROOT" \
    -I source -I plugins/poindexter \
    --extra-c source/core/price_prediction.c \
    --extra-c source/core/price_prediction_on1x.c \
    --mulib price-forecast --mulib price-ensemble --mulib histprice \
    --cflag=-lm --cflag=-g --debug-build-root "$work" -o "$out/finpred"
)

# The cube host uses its own package and shared helpers, with no Ottomat PPX.
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" "$work/source/plugins/yieldcraft/cube_main.on1x" \
  --backend c11 --cc "${CC:-cc}" --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
  -I "$work/source" -o "$out/finpred-cube"

cp -R "$ROOT/plugins/forecast_baselines/source/forecast_baselines" "$work/source/"
cat >"$work/source/forecast_baselines/On1xfile.m" <<'EOF'
on1xfile 1
library "model.on1x"
library "score.on1x"
library "evaluation.on1x"
library "holdout.on1x"
EOF
# Fingerprint the linked analysis source closure and compiler. Stable paths
# and hashes keep temporary checkout locations out of archived identities.
printf 'library "forecast_identity.on1x"\n' >>"$work/source/cli/On1xfile.m"
subject=$(python3 "$ROOT/bin/forecast-subject.py" "$work/source" "$ON1XC")
printf 'fn source_subject() -> string { return "finpred-forecast-code@1:sha256:%s"; }\n' \
  "$subject" >"$work/source/cli/forecast_identity.on1x"
# The forecast host has its own entry point and doesn't need GrammarEmbed.
# Keep the legacy generation replaceable by existing installs.
cp "$ROOT/plugins/forecast_baselines/forecast_main.on1x" "$work/source/"
rm "$work/source/main.on1x"
printf 'on1xfile 1\nsource "forecast_main.on1x"\n' >"$work/source/On1xfile.m"
cat >"$work/On1xfile" <<'EOF_FORECAST'
on1xfile 1
kind executable
name "finpred-forecast"
directory "source"
target "finpred-forecast" "source/forecast_main.on1x"
backend c11
EOF_FORECAST
python3 "$MULIB_ROOT/on1x/tools/on1x-project.py" build "$work" \
  --cc "${CC:-cc}" --target finpred-forecast --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" --output-dir "${out}-forecast"

# Static graph inspection is a separate host. Add its build-time compiler
# identity only after the other hosts have been linked.
printf 'library "graph_check.on1x"\nlibrary "graph_identity.on1x"\n' >>"$work/source/cli/On1xfile.m"
compiler_hash=$(sha256sum <"$ON1XC")
printf 'fn compiler_id() -> string { return "sha256:%s"; }\n' "${compiler_hash%% *}" \
  >"$work/source/cli/graph_identity.on1x"
(
  cd "$work"
  python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" source/cli/graph_main.on1x \
    --backend c11 --cc "$cc" --on1xc "$work/on1xc" --mulib-root "$MULIB_ROOT" \
    -I source --extra-c source/cli/graph_input.c \
    --cflag=-g --debug-build-root "$work" -o "$out/finpred-graph"
)
