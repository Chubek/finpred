#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$ROOT/tests/check_fixtures.py"
cd "$ROOT"
"$ROOT/bin/finpred" selftest
OUT=$("$ROOT/bin/finpred" run)
printf '%s\n' "$OUT"
printf '%s\n' "$OUT" | grep -Fx 'recommendation_minor=17100'
printf '%s\n' "$OUT" | grep -Fx 'reason=lower_percentile_shortcut'
printf '%s\n' "$OUT" | grep -Fx 'published=false'
RUN_ID=$(printf '%s\n' "$OUT" | sed -n 's/^run_id=//p')
[ "${#RUN_ID}" -eq 64 ]
"$ROOT/bin/finpred" replay "$RUN_ID" | grep -Fx 'replay_ok=true'
MULTI=$(FINPRED_SCENARIO="$ROOT/fixtures/scenario_multiroom.csv" \
  FINPRED_OFFERS="$ROOT/fixtures/offers_multiroom.csv" "$ROOT/bin/finpred" run)
printf '%s\n' "$MULTI" | grep -Fx 'recommendation_minor=16000'
printf '%s\n' "$MULTI" | grep -Fx 'reason=guardrail_adjustment' 
# Run is an immutable/idempotent local operation on exactly the same inputs.
OUT2=$("$ROOT/bin/finpred" run)
[ "$OUT" = "$OUT2" ]
# Reject invalid scenario and unauthorized execution mode.
if FINPRED_SCENARIO="$ROOT/fixtures/invalid_scenario.csv" "$ROOT/bin/finpred" run >/dev/null 2>&1; then
  echo 'invalid scenario unexpectedly accepted' >&2
  exit 1
fi
if FINPRED_MODE=execution "$ROOT/target/dev/finpred" >/dev/null 2>&1; then
  echo 'execution mode unexpectedly accepted' >&2
  exit 1
fi
echo 'on1x_integration_ok=true'
