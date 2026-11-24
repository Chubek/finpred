#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
MULIB_ROOT=${MULIB_ROOT:-"$ROOT/third_party/mulib"}
ON1XC=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
if [ ! -f "$MULIB_ROOT/on1x/tools/on1x-project.py" ]; then
  echo "Missing MuLIB at $MULIB_ROOT (set MULIB_ROOT or populate third_party/mulib)" >&2
  exit 2
fi
if [ ! -x "$ON1XC" ]; then
  echo "Missing compiled On1x compiler at $ON1XC (run 'make mulib' or set ON1XC)" >&2
  exit 2
fi
finpred_build_env "$ROOT"
cd "$ROOT"
# Compose the host and selected built-in packages in a disposable project;
# canonical plugin sources stay under plugins/.
out=$(finpred_cli_output_dir "$ROOT")
mkdir -p "$(dirname -- "$out")"
work=$(mktemp -d "$TMPDIR/finpred-project.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
cp "$ROOT/On1xfile" "$work/"
cp -R "$ROOT/source" "$work/source"
mkdir -p "$work/source/plugins" "$work/plugins/poindexter"
cp -R "$ROOT/plugins/yieldcraft" "$ROOT/plugins/scalar_diagnostics" "$work/source/plugins/"
cp -R "$ROOT/plugins/poindexter/On1xfile" "$ROOT/plugins/poindexter/src" "$work/plugins/poindexter/"
python3 "$ROOT/bin/on1x_grammar.py" "$work/on1xc" "$ON1XC" "$MULIB_ROOT"
python3 "$MULIB_ROOT/on1x/tools/on1x-project.py" build "$work" \
  --cc "${CC:-cc}" --on1xc "$work/on1xc" --mulib-root "$MULIB_ROOT" --output-dir "$out"

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
compiler_hash=$(sha256sum <"$ON1XC")
source_hashes=$(cd "$work/source" && sha256sum forecast_baselines/*.on1x \
  core/date.on1x core/feed_snapshot.on1x core/format.on1x core/guest_nights.on1x sdk/callable.on1x)
subject=$(printf '%s\n' "$compiler_hash" "$source_hashes" | sha256sum)
printf 'fn source_subject() -> string { return "finpred-forecast-code@1:sha256:%s"; }\n' \
  "${subject%% *}" >"$work/source/cli/forecast_identity.on1x"
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
