# Point-in-time forecast scoring: one complete analysis-only vertical slice

## Scope and provenance

Baseline: `Chubek/finpred` `34b2f89d9dae9b52bb47e453bbe01a44d36064bc`
(2026-11-23). This patch **adds** scoring of immutable guest-night baseline
forecasts; it does not claim a universal backtesting framework, a validated
model of financial return, trading capability, or native storage admission.

The repository already implements `forecast_baselines.model` with two pure
baseline models and a separate financial graph consumer for simultaneous
issuance-time forecasts. The new `forecast_baselines.score.evaluate` operates
**after issuance**, rather than pretending that observed actuals were
available when the model ran.

## Data flow

```text
Earlier as-of/issued time                     Later scoring time

 training raw snapshot --BLAKE3--> project      actuals raw snapshot --BLAKE3--> project
            |                     |                    |                     |
            |                  train cutoff            |                 scoring cutoff
            v                     v                    v                     v
     pinned Model.call       recompute bytes       verified actuals    target-month lookup
            |                     |                    |                     |
            +---- compare ---- frozen forecast         +----------+----------+
                              exact bytes                         |
                                  +--------------------------------+
                                                   |
                                          analysis-only score
                                      signed / absolute rational
```

The two snapshots can have different update/ingestion times. The release
for a training window must have been ingested no later than the training
cutoff; the actuals release must have been ingested no later than the scoring
cutoff, with all target-month observations published. The scoring cutoff must
occur after issuance and at or after the target month's end. No data from the
later scoring release enters the earlier model invocation.

## Source and callable API

```text
forecast_baselines.score.evaluate(
    model, training_raw, training_parent, forecast_request,
    frozen_forecast, actual_raw, actual_parent,
    training_cutoff, scoring_cutoff, model_code_digest
) -> Score { status, state, bytes }
```

The source is under `plugins/forecast_baselines/source/forecast_baselines/`.
The independent host is `tests/forecast_score_consumer/main.on1x`.

`training_parent` and `actual_parent` are *host-selected* BLAKE3 digests of
the exact raw snapshot bytes. `model_code_digest` identifies the exact
model-code subject chosen by the linking host, **not** a developer signature.
The frozen forecast is re-executed and compared byte for byte. The scorer
rejects mismatched expected forecast bytes rather than trust their own JSON
metadata. It does not fetch files, open sockets, mutate a store, or authorize
an action. Binding to a trusted upstream capture/authorization subsystem is a
separate integration task.

Nonzero status codes are:

| Code | Meaning |
|---|---|
| 1 | Unknown model handler or invalid model/code identity |
| 2 | Invalid, mismatched or too-late training snapshot |
| 3 | Pinned model request/invocation or output invalid |
| 4 | Invalid, mismatched or too-late scoring snapshot |
| 5 | Invalid issuance/score chronology, or scoring before month end |
| 6 | Archived forecast differs from deterministic model replay |

A successful result has `status=0` and `state=1` (scored) or `state=4`
(unknown); an unknown result cannot be treated as an error of zero.

## Output contract

Schema: `plugins/forecast_baselines/contracts/analysis.guest-nights-score@1.schema.json`.
Output always carries `model`, `code_digest`, `policy_digest`, forecast/training/
actual projection identities, original raw actual parent, issuance and two
cutoffs, target month and an explicit `state`/`reason`. For a `scored` result
it includes the realized nonnegative count, exact rational estimate, signed
error `estimate - actual` and its absolute value. Unknown observations or
insufficient training evidence yield `unknown` with null actual/estimate/error
fields so they cannot silently lower reported MAE.

At most one calendar month is scored per call; the identity of the produced
score is the BLAKE3 digest of its entire canonical serialized bytes. A
future immutable run manifest must also bind its input roots, model pin and
scoring policy; this module alone is not a durable store.

## Verification

```sh
make mulib
python3 tests/check_forecast_scores.py
make forecast-score-test
make test
```

The compiled consumer verifies two models × three origins (six scores),
repeated exact-byte outputs, strict JSON schema, independent Python `Fraction`
arithmetic, explicit zero/unknown distinctions, a reduced-denominator
fractional-error case, and rejection of changed forecast bytes, invalid
parents, wrong model, early scoring and late actuals. It asserts no file
creation under an isolated `FINPRED_HOME`.

For schema/oracle-only checks (not a compiled claim):

```sh
python3 tests/check_forecast_scores.py --oracle-only
```

## Deliberately open gates

- Integrate forecast scoring into a trusted, versioned *evaluation-run*
  writer, with explicit scoring artifact lineage and read-only replay.
- Aggregate per-origin scores into a backtest with scored/unknown counts,
  MAE, signed bias and optionally overflow-safe RMSE/MSE. Never select models
  on holdout accuracy and then report that same holdout as unbiased.
- Generalize beyond Eurostat EU27 guest-night data and the current fixed
  three-row snapshot shape; support different training/economic periods.
- Admit new provider profiles only with source authorization, schema checks,
  collection rights and independent provider authenticity evidence.
- Add calibrated prediction intervals and comparisons to stronger baselines.
- Do not alter frozen `finpred-run@1/@2` readers, prices, or IDs.

## Validation record

This patch was authored without a local MuLIB/LibStone checkout or compiled
`on1xc` in the packaging environment. Python syntax and JSON Schema can be
checked independently; **On1x compilation and compiled integration must pass
in the pinned CI workflow before claiming this new feature is verified.**
See `PATCH_VALIDATION.md` in the bundle for exact checks run.
