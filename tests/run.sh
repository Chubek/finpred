#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/bin/build-env.sh"
. "$ROOT/bin/paths.sh"
finpred_build_env "$ROOT"
cd "$ROOT"
unset FINPRED_ENGINE FINPRED_DEMAND FINPRED_MODE FINPRED_RUN_ID
FINPRED_EXE=$(finpred_cli_executable "$ROOT")
export FINPRED_EXE
exe=$FINPRED_EXE

checks() {
  for check in "$@"; do
    python3 "tests/check_$check.py"
  done
}

caravansary_checks() {
  sh plugins/caravansary/frontend/generate-tables.sh --check
  sh plugins/caravansary/build.sh
  for module in frontend programming planning coverage credentials booking metrics; do
    sh plugins/caravansary/build.sh "--check-$module"
  done
  python3 tests/caravansary_on1x.py
  for check in tests/check_caravansary*.py; do
    python3 "$check"
  done
}

caravansary_market_checks() {
  on1xc=${ON1XC:-"$(finpred_mulib_build_dir "$ROOT")/on1xc"}
  out=$(finpred_cli_output_dir "$ROOT")
  export ON1XC="$on1xc" CC=clang CXX=clang++
  sh plugins/caravansary/build.sh --market
  sh plugins/caravansary/build.sh --joe-litty
  sh plugins/caravansary/build.sh --check-review
  sh plugins/caravansary/examples/providers/check.sh
  sh plugins/caravansary/discovery/check.sh
  sh plugins/caravansary/pricing/check.sh
  FINPRED_BUILD_DIR="$out" sh plugins/caravansary/jobs/build.sh
  python3 tests/caravansary_market.py --with-jobs
  python3 tests/caravansary_joe_litty.py
  sh plugins/caravansary/examples/joe-litty-rooms/check.sh --reuse-market
  python3 plugins/caravansary/jobs/test_jobs.py "$out/finpred-caravansary-jobs" \
    --market "$out/finpred-caravansary-market"
}

require_tools() {
  for tool in "$@"; do
    if ! command -v "$tool" >/dev/null; then
      echo "$suite verification requires $tool" >&2
      exit 2
    fi
  done
}

fixture_home() {
  work=$(mktemp -d "$TMPDIR/finpred-test.XXXXXXXX")
  trap 'rm -rf -- "$work"' EXIT
  trap 'exit 1' HUP INT TERM
  FINPRED_HOME="$work/main"
  FINPRED_SCENARIO="$ROOT/fixtures/scenario.csv"
  FINPRED_OFFERS="$ROOT/fixtures/offers.csv"
  FINPRED_VALUATION="$ROOT/fixtures/valuation.csv"
  FINPRED_STRATEGY="$ROOT/strategies/yieldcraft.ottomat"
  export FINPRED_HOME FINPRED_VALUATION FINPRED_STRATEGY FINPRED_SCENARIO FINPRED_OFFERS
}

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
  if [ "$suite" != storage ]; then
    return
  fi
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

fixture_runs() {
  check_fixture '' 17100 lower_percentile_shortcut 5 2 0
  main_id=$id
  # Pin pre-profile v2 identities as well as economic outcomes: the run ID
  # covers all input lineage; the manifest output hashes cover JSON and trace.
  if [ "$suite" = storage ]; then
    [ "$id:$rd:$tr" = '28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db:5099f766659506292edb848dc8e8376cce99dfae60b9bc8d495d03792d6461ee:4503a57102a1ea380b9e94ac5b3fe5f9c17e3ac44c12c1ab049e60a4d4a75822' ]
    cp "$work/run" "$work/main-summary"
  fi
  check_fixture '_multiroom' 16000 guardrail_adjustment 3 0 1
  multi_id=$id
  [ "$multi_id" != "$main_id" ]
  if [ "$suite" = storage ]; then
    [ "$id:$rd:$tr" = '7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b:1f10e792e433fc59fc6ec49cf100922b7ce543c0c440b01551b4e2e32806f2ea:67f5051fb3613d4011c431a5ab343022ada824a428ad8ca3f1cc8358035dba86' ]
    python3 tests/check_explain_cli.py "$FINPRED_HOME" "$main_id"
    python3 tests/check_evidence_cli.py "$FINPRED_HOME" "$main_id" "$multi_id"
    python3 tests/check_store.py "$FINPRED_HOME" "$work/main-summary" "$work/run"
  fi

  check_fixture '_asof' 18000 target_percentile 3 4 0
  if [ "$suite" = storage ]; then
    [ "$id:$rd:$tr" = '353d3ec6bd8750df4e4ed70535ef476373d5e20cab386a3d86c33b6a69203a22:bbd2adcba1d540104ff11028f853f558d8831507fe722afac23615225dbd7d63:a47608ae867ebad0b8e7cdb7c13862fb42e17e2de75be7c746c7c6cf2e6ada2a' ]
  fi
  bin/finpred evidence "$id" >"$work/evidence"
  for row in 1,301,1,eligible 2,302,1,eligible 3,303,1,eligible \
      4,304,1,future_observed 5,305,1,future_ingested 6,306,1,stale 7,307,1,validity_mismatch; do
    grep -Fxq "row=$row" "$work/evidence"
  done
  grep -Fxq 'sample=3,3,adequate' "$work/evidence"

  FINPRED_VALUATION="$ROOT/fixtures/valuation_leap_day.csv"
  check_fixture '_leap_day' 17001 target_percentile 3 0 1
  if [ "$suite" = storage ]; then
    [ "$id:$rd:$tr" = '3755e6e9e88a56b510eeb68eb0cfd2ef165ec0b0aecc53018f67921a53e3aa98:931178dfaabfb4be329e1f07f14cdc8535fc28793a0ccfb2648e5c093e2efcb2:5511938de9f790c1a05d66a07280fe9cd9ae089290635af5b0ef166912eb598c' ]
  fi
  grep -Fxq 'nights=2' "$trace_file"
  bin/finpred evidence "$id" >"$work/evidence"
  grep -Fxq 'bundle=403,34001,2' "$work/evidence"
  grep -Fxq 'property=404,no_feasible_bundle,1,1' "$work/evidence"
  FINPRED_VALUATION="$ROOT/fixtures/valuation.csv"
}

storage_integrity() {
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
}

security_denials() {
FINPRED_HOME="$work/denied"
expect_failure 'insufficient_evidence' env FINPRED_SCENARIO="$ROOT/fixtures/scenario_asof_early.csv" \
    FINPRED_OFFERS="$ROOT/fixtures/offers_asof.csv" bin/finpred run
if grep -Eq '^(run_id|recommendation_minor|published)=' "$work/failure" || [ -e "$FINPRED_HOME" ]; then
  echo 'early as-of fixture emitted or wrote a result' >&2
  exit 1
fi
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
}

dragnet_legacy() {
  checks dragnet_frozen_csv dragnet_elvi crossref_replay dragnet_public_feeds dragnet_dispatch
}

if [ "$#" -gt 1 ]; then
  echo 'usage: tests/run.sh [compiler|pricing|forecasting|plugins|storage|security]' >&2
  exit 2
fi
suite=${1-all}
case "$suite" in
  all)
    result=0
    for group in compiler pricing forecasting plugins storage security; do
      if ! "$ROOT/tests/run.sh" "$group"; then
        echo "verification suite failed: $group" >&2
        result=1
      fi
    done
    [ "$result" -eq 0 ] || exit "$result"
    echo 'on1x_integration_ok=true'
    ;;
  compiler)
    python3 tests/validate_static.py
    checks build_paths on1x_features environ_argv ottomat_plan reproducible_build
    ;;
  pricing)
    require_tools strace
    checks fixtures price_prediction price_backtest price_properties ecb_yield_study \
      yieldcraft_contribution yieldcraft_demand yieldcraft_demand_panel \
      yieldcraft_inventory yieldcraft_coupled_inventory yieldcraft_risk_contribution \
      contribution_dag competitor_cube fixed_runner hospitality_adapters \
      financial_graph ottomat_financial pricing_cli profiles_cli
    fixture_home
    bin/finpred selftest >"$work/selftest"
    grep -Fx 'selftest_ok=true' "$work/selftest"
    fixture_runs
    ;;
  forecasting)
    checks fx_reference forecast_baselines forecast_cli forecast_graph forecast_scores forecast_vintages
    ;;
  plugins)
    caravansary_checks
    caravansary_market_checks
    require_tools strace
    checks sdk sdk_packages python_sdk sdk_data1 plugin_registry engines_cli scalar_registry \
      scalar_diagnostics_package yieldcraft_package dragnet_search
    dragnet_legacy
    checks dragnet_offline_evidence
    ./bin/poindexter --build
    checks poindexter_cli poindexter_package poindexter_workbench poindexter_tty
    require_tools xvfb-run Xvfb xauth
    checks poindexter_gui
    ;;
  storage)
    checks dag_replay scalar_manifest yieldcraft_formats write_failure store_publication_status
    fixture_home
    fixture_runs
    python3 tests/validate_runtime_json.py "$FINPRED_HOME"
    storage_integrity
    ;;
  security)
    python3 tests/check_cli_environ.py "$exe"
    checks dag ingestion_cli ottomat_scalar scalar_memo scalar_selection
    python3 tests/check_tui_kernel_admission.py --expect-dynlib-syntax
    fixture_home
    security_denials
    checks offline_worker
    ;;
  dragnet-legacy) dragnet_legacy ;;
  dragnet-search) checks dragnet_search ;;
  forecast-score) checks forecast_scores ;;
  caravansary) caravansary_checks ;;
  caravansary-market) caravansary_market_checks ;;
  *)
    echo "Unknown verification suite: $suite" >&2
    exit 2
    ;;
esac
