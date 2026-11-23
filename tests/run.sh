#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
finpred_build_env "$ROOT"
cd "$ROOT"
unset FINPRED_ENGINE
FINPRED_EXE=$(finpred_cli_executable "$ROOT")
export FINPRED_EXE
python3 tests/validate_static.py
python3 tests/check_on1x_features.py
python3 tests/check_fixtures.py
python3 tests/check_sdk.py
python3 tests/check_sdk_packages.py
python3 tests/check_sdk_data1.py
python3 tests/check_forecast_baselines.py
python3 tests/check_plugin_registry.py
python3 tests/check_fixed_runner.py
python3 tests/check_hospitality_adapters.py
python3 tests/check_financial_graph.py
python3 tests/check_ottomat_financial.py
python3 tests/check_forecast_graph.py
python3 tests/check_dag.py
python3 tests/check_dag_replay.py
python3 tests/check_scalar_manifest.py
python3 tests/check_scalar_memo.py
python3 tests/check_ottomat_plan.py
python3 tests/check_ottomat_scalar.py
python3 tests/check_scalar_selection.py
python3 tests/check_scalar_registry.py
python3 tests/check_scalar_diagnostics_package.py
work=$(mktemp -d "$TMPDIR/finpred-test.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 1' HUP INT TERM
exe=$FINPRED_EXE
python3 tests/check_engines_cli.py
unset FINPRED_MODE FINPRED_RUN_ID
FINPRED_HOME="$work/main"
FINPRED_VALUATION="$ROOT/fixtures/valuation.csv"
FINPRED_STRATEGY="$ROOT/strategies/yieldcraft.ottomat"
export FINPRED_HOME FINPRED_VALUATION FINPRED_STRATEGY FINPRED_SCENARIO FINPRED_OFFERS

# Ignore access times: reading the files may legitimately update those.
# Inodes and ctime/mtime catch same-byte rewrites and replacement as well.
snapshot() {
  python3 - "$FINPRED_HOME" <<'PY'
import hashlib, sys
from pathlib import Path
root = Path(sys.argv[1])
for p in [root, *sorted(root.rglob("*"))]:
    st = p.lstat()
    print(p.relative_to(root), st.st_ino, st.st_mode, st.st_mtime_ns, st.st_ctime_ns,
          hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "-")
PY
}

expect_failure() {
  diagnostic=$1
  shift
  if "$@" >"$work/failure" 2>&1; then
    echo "unexpected success: $*" >&2
    exit 1
  fi
  if ! grep -Fq "$diagnostic" "$work/failure"; then
    cat "$work/failure" >&2
    echo "missing diagnostic: $diagnostic" >&2
    exit 1
  fi
}

check_fixture() {
  FINPRED_SCENARIO="$ROOT/fixtures/scenario$1.csv"
  FINPRED_OFFERS="$ROOT/fixtures/offers$1.csv"
  bin/finpred run >"$work/run"
  cat "$work/run"
  grep -Fxq "recommendation_minor=$2" "$work/run"
  grep -Fxq "reason=$3" "$work/run"
  grep -Fxq 'currency=EUR' "$work/run"
  grep -Fxq 'published=false' "$work/run"
  id=$(sed -n 's/^run_id=//p' "$work/run")
  printf '%s\n' "$id" | grep -Exq '[0-9a-f]{64}'
  trace_hash=$(sed -n 's/^trace_digest=//p' "$work/run")
  trace_file="$FINPRED_HOME/artifacts/blake3-$trace_hash.txt"
  grep -Fxq "recommended_nightly_minor=$2" "$trace_file"
  grep -Fxq "reason=$3" "$trace_file"
  grep -Fxq "independent_properties=$4" "$trace_file"
  grep -Fxq "rejected_offers=$5" "$trace_file"
  grep -Fxq "infeasible_properties=$6" "$trace_file"
  IFS=, read -r version sd od vd td rd tr <"$FINPRED_HOME/runs/$id.txt"
  [ "$version" = 'finpred-run@2' ]
  cmp "$FINPRED_SCENARIO" "$FINPRED_HOME/artifacts/blake3-$sd.txt"
  cmp "$FINPRED_OFFERS" "$FINPRED_HOME/artifacts/blake3-$od.txt"
  cmp "$FINPRED_VALUATION" "$FINPRED_HOME/artifacts/blake3-$vd.txt"
  cmp "$FINPRED_STRATEGY" "$FINPRED_HOME/artifacts/blake3-$td.txt"
  grep -Fxq "recommendation_digest=$rd" "$work/run"
  [ "$tr" = "$trace_hash" ]
  snapshot >"$work/before"
  FINPRED_SCENARIO="$work/absent" FINPRED_OFFERS="$work/absent" \
    FINPRED_VALUATION="$work/absent" FINPRED_STRATEGY="$work/absent" \
    bin/finpred replay "$id" >"$work/replay"
  grep -Fxq 'replay_ok=true' "$work/replay"
  sed '/^replay_ok=true$/d' "$work/replay" >"$work/summary"
  cmp "$work/run" "$work/summary"
  snapshot >"$work/after"
  cmp "$work/before" "$work/after"
  bin/finpred run >"$work/repeat"
  cmp "$work/run" "$work/repeat"
  snapshot >"$work/after"
  cmp "$work/before" "$work/after"
}

bin/finpred selftest >"$work/selftest"
grep -Fx 'selftest_ok=true' "$work/selftest"
check_fixture '' 17100 lower_percentile_shortcut 5 2 0
main_id=$id
# Pin pre-profile v2 identities as well as economic outcomes: the run ID
# covers all input lineage; the manifest output hashes cover JSON and trace.
[ "$id:$rd:$tr" = '28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db:5099f766659506292edb848dc8e8376cce99dfae60b9bc8d495d03792d6461ee:4503a57102a1ea380b9e94ac5b3fe5f9c17e3ac44c12c1ab049e60a4d4a75822' ]
cp "$work/run" "$work/main-summary"
check_fixture '_multiroom' 16000 guardrail_adjustment 3 0 1
multi_id=$id
[ "$id:$rd:$tr" = '7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b:1f10e792e433fc59fc6ec49cf100922b7ce543c0c440b01551b4e2e32806f2ea:67f5051fb3613d4011c431a5ab343022ada824a428ad8ca3f1cc8358035dba86' ]
[ "$multi_id" != "$main_id" ]
python3 "$ROOT/tests/validate_runtime_json.py" "$FINPRED_HOME"
python3 "$ROOT/tests/check_explain_cli.py" "$FINPRED_HOME" "$main_id"
python3 "$ROOT/tests/check_evidence_cli.py" "$FINPRED_HOME" "$main_id" "$multi_id"
python3 "$ROOT/tests/check_store.py" "$FINPRED_HOME" "$work/main-summary" "$work/run"
id=$main_id
FINPRED_SCENARIO="$ROOT/fixtures/scenario.csv"
FINPRED_OFFERS="$ROOT/fixtures/offers.csv"
manifest="$FINPRED_HOME/runs/$id.txt"
IFS=, read -r version scenario offers valuation strategy rec trace <"$manifest"
[ "$version" = 'finpred-run@2' ]
# Independently computed BLAKE3-256 of the frozen scenario.csv bytes.
[ "$scenario" = d29ce68748eef1b786027c59072d93e6606a39405b3af549c674c56c1899d735 ]
# Also corrupt a normalized observation the matcher rejected as stale.
rejected_offer=$(grep -Fl '"id":"property:106:room:1"' "$FINPRED_HOME"/artifacts/*.txt)
for object in "$FINPRED_HOME/artifacts/blake3-$scenario.txt" \
              "$FINPRED_HOME/artifacts/blake3-$offers.txt" \
              "$FINPRED_HOME/artifacts/blake3-$valuation.txt" \
              "$FINPRED_HOME/artifacts/blake3-$strategy.txt" \
              "$FINPRED_HOME/artifacts/blake3-$rec.txt" \
               "$FINPRED_HOME/artifacts/blake3-$trace.txt" \
               "$FINPRED_HOME/artifacts/blake3-$id.txt" "$rejected_offer"; do
  cp "$object" "$work/saved"
  printf '!' | dd of="$object" bs=1 conv=notrunc 2>/dev/null
  snapshot >"$work/before"
  expect_failure 'snapshot digest mismatch' bin/finpred replay "$id"
  if [ "$object" = "$FINPRED_HOME/artifacts/blake3-$scenario.txt" ]; then
    expect_failure 'immutable path conflict' bin/finpred run
  fi
  snapshot >"$work/after"
  cmp "$work/before" "$work/after"
  mv "$work/saved" "$object"
done
mv "$FINPRED_HOME/artifacts/blake3-$rec.txt" "$work/missing"
expect_failure 'missing snapshot' bin/finpred replay "$id"
[ ! -e "$FINPRED_HOME/artifacts/blake3-$rec.txt" ]
mv "$work/missing" "$FINPRED_HOME/artifacts/blake3-$rec.txt"
cp "$FINPRED_HOME/artifacts/blake3-$rec.txt" "$work/saved"
printf '\000suffix' >>"$FINPRED_HOME/artifacts/blake3-$rec.txt"
expect_failure 'NUL-free text ABI' bin/finpred replay "$id"
cp "$work/saved" "$FINPRED_HOME/artifacts/blake3-$rec.txt"
truncate -s 2097153 "$FINPRED_HOME/artifacts/blake3-$rec.txt"
expect_failure 'snapshot size outside digest profile' bin/finpred replay "$id"
mv "$work/saved" "$FINPRED_HOME/artifacts/blake3-$rec.txt"

# Checked-in valid artifacts under the wrong roles must not be accepted.
cp "$manifest" "$work/original-manifest"
printf '%s,%s,%s,%s,%s,%s,%s\n' "$version" "$scenario" "$offers" "$valuation" \
  "$strategy" "$trace" "$rec" >"$manifest"
expect_failure 'divergence' bin/finpred replay "$id"
sed 's/^finpred-run@2/finpred-run@9/' "$work/original-manifest" >"$manifest"
expect_failure 'unknown run format' bin/finpred replay "$id"
mv "$work/original-manifest" "$manifest"
bin/finpred replay "$id" >"$work/recovered"
sed '/^replay_ok=true$/d' "$work/recovered" >"$work/summary"
cmp "$work/main-summary" "$work/summary"

id=$multi_id
# An authentic manifest copied under the wrong identity must still fail.
cp "$FINPRED_HOME/runs/$id.txt" "$FINPRED_HOME/runs/$main_id.txt"
expect_failure 'divergence' bin/finpred replay "$main_id"
# Removing LF changes the stored bytes even though a CSV parser sees the same fields.
tr -d '\n' <"$FINPRED_HOME/runs/$id.txt" >"$work/edited"
mv "$work/edited" "$FINPRED_HOME/runs/$id.txt"
expect_failure 'malformed run manifest' bin/finpred replay "$id"

FINPRED_HOME="$work/denied"
expect_failure 'malformed identity' bin/finpred replay "$(printf '%064d' 0 | tr 0 /)"
expect_failure 'scenario: invalid' env FINPRED_SCENARIO="$ROOT/fixtures/invalid_scenario.csv" bin/finpred run
expect_failure 'capability denied' env FINPRED_MODE=execution bin/finpred run
expect_failure 'capability denied' env FINPRED_MODE=execution "$exe"
expect_failure 'invalid graph or incompatible strategy' env \
    FINPRED_STRATEGY="$ROOT/strategies/scalar-spread.ottomat" bin/finpred run
expect_failure 'invalid graph or incompatible strategy' env \
    FINPRED_STRATEGY="$ROOT/strategies/scalar-select.ottomat" bin/finpred run
expect_failure 'invalid graph or incompatible strategy' env \
    FINPRED_STRATEGY="$ROOT/strategies/scalar-midpoint.ottomat" bin/finpred run
[ ! -e "$FINPRED_HOME" ]
python3 "$ROOT/tests/check_pricing_cli.py"
python3 "$ROOT/tests/check_profiles_cli.py"
python3 "$ROOT/tests/check_yieldcraft_formats.py"
python3 "$ROOT/tests/check_ingestion_cli.py"
python3 "$ROOT/tests/check_poindexter_cli.py"
python3 "$ROOT/tests/check_write_failure.py"
python3 "$ROOT/tests/check_store_publication_status.py"
echo 'on1x_integration_ok=true'
