# Point-in-time forecast scoring and evaluation replay

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

## Evaluation manifest (`analysis.guest-nights-evaluation@1`)

`forecast_baselines.evaluation.evaluate(linked, selection, roots, frozen)`
assembles one in-memory evaluation. `linked` identifies the model and scoring
code subjects from trusted runtime configuration; `selection` supplies the
expected code pins, model, and the original training and scoring cutoffs.
`roots` holds the four expected BLAKE3 IDs and `frozen` supplies the exact
bytes: the two canonical Dragnet snapshots (not raw provider payloads), the
request, and the issued forecast. The host selects these inputs independently
of any archive. The code subject digests are host claims about the linked
build, not self-measured executable identities or signatures.

The evaluator checks bounds and hashes before invoking the scorer. Success
returns the unchanged score artifact and a compact LF-terminated JSON
manifest. The manifest binds all four root digests, both cutoffs, the model
and scoring code and policy pins, and the score digest and state. The run ID is
`blake3:<hex>` over the exact manifest bytes, including the final LF.
See the [manifest schema](../plugins/forecast_baselines/contracts/analysis.guest-nights-evaluation@1.schema.json).

`replay(linked, selection, roots, frozen, archive)` also takes the expected
run ID from a trusted lookup and the archived manifest and score bytes. It
checks the manifest against that ID, recomputes from the same frozen evidence,
and accepts only if both archived outputs match byte-for-byte. It does not
derive roots, code identities, or cutoffs from archive JSON. Replay does not
fetch missing evidence or write or repair a store. A new actuals release or a
different scoring cutoff requires a new evaluation.

Evaluation status codes are `1` for an unsupported model or mismatched code
identity, `2` for invalid root bytes or digests, `3` for scoring failure,
`4` for a manifest mismatch, and `5` for a score mismatch. All failures
return no ID, manifest, or score. Successful `unknown` results replay just
like scored results.

## Final holdout report (`analysis.guest-nights-holdout@1`)

```text
forecast_baselines.holdout.aggregate(linked, plan, entry_at) -> Report { status, id, bytes }
```

This pure callable reports coverage and errors for **one preselected model**
over a contiguous window of 1–24 monthly targets. The trusted host supplies
the model and code pins, last validation target (`validation_through`),
selection freeze time, inclusive first and last holdout targets, and one
scoring cutoff for the whole report. The freeze time must be at or after the
end of the last validation month and no later than the start of the first
holdout target month. Allow a gap after validation if its observations were
not yet available. The scoring cutoff must be at or after the end of the last
target month.

The host must freeze the model, evaluation window, and evidence-selection
policy without using final holdout outcomes. The freeze timestamp is a
trusted assertion, not proof of the model-selection process. This API does
not select or rank models, perform validation, certify the host's selection
history, or turn a re-selected model's reused holdout into an independent
test. Each origin keeps its own original training cutoff; an earlier
holdout observation may enter a later origin's **rolling training** only if
visible at that origin's training cutoff. Validation target scores cannot
enter the aggregate.

For each month offset, the trusted, read-only `entry_at` lookup over frozen
data supplies the original
training cutoff, expected root digests and evaluation ID, frozen inputs, and
archived evaluation manifest and score bytes. The host obtains expected
identities from trusted state, not by rehashing submitted archive bytes. The
aggregator requires the expected target for each offset and reruns evaluation
replay; missing entries, duplicate or misplaced months, and tampered
evidence fail the whole report. An explicit replayed `unknown` counts toward
coverage; it is not the same as a missing evaluation and contributes neither
an error nor a zero.

The [report schema](../plugins/forecast_baselines/contracts/analysis.guest-nights-holdout@1.schema.json)
records the plan and policy pins, ordered evaluation IDs and per-month
states, `expected`, `scored`, `unknown`, and reduced exact rational `mae`
and `bias` in guest-nights. Bias uses `estimate − actual`. Both means divide
by `scored`, and both are null if `scored=0`. Coverage counts sum to the
window length. The report ID is BLAKE3 over the compact JSON bytes including
the final LF. Recomputing from the same trusted inputs gives identical
bytes. No catalog, writer, CLI, action authorization, or historical format
change is introduced.

The baseline scores have denominators of 1 or 3 and a magnitude of at most
999,999,999,999 guest-nights. Summing exact thirds gives absolute and signed
sums bounded by `24 × 2,999,999,999,997 = 71,999,999,999,928`, with a mean
denominator of at most 72 before reduction. These bounds fit signed i64.
**MSE and RMSE are deliberately deferred**: even one allowed squared error
can exceed i64, and an exact MSE would not generally have a rational square
root. The report emits neither approximations nor placeholder values.

Status codes: `1` invalid plan or pins, `2` missing or incorrect month/request,
`3` failed evaluation replay, `4` unexpected replayed score encoding or
report hash failure. A failed report has no ID or bytes.

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

The same consumer checks canonical manifests and exact replay in separate
processes for six scored evaluations and one unknown. It rejects 20 invalid
inputs, including rehashed manifests with wrong parents or policy and a
forged score whose digest was substituted into a rehashed manifest.

The holdout checks use a Python `Fraction` oracle for eight compiled reports:
the two preselected baselines, fractional and mixed-sign errors, partial and
all-unknown coverage, exact zero and signed cancellation, and a 24-month
near-limit case. Twenty-two rejection cases cover split chronology, missing and
duplicate targets, window limits, pin/cutoff mismatches, and tampered archives.
Successful reports are schema-validated and compared byte-for-byte across
independent invocations.

For schema/oracle-only checks (not a compiled claim):

```sh
python3 tests/check_forecast_scores.py --oracle-only
```

## Deliberately open gates

- Integrate the in-memory manifest with a trusted host catalog and a
  write-once evaluation store. No writer or CLI command exists for this format.
- Add a trusted selection/plan catalog if the host must prove model selection
  preceded holdout access. Design checked wider accumulation for exact MSE
  and explicit precision/rounding rules for RMSE before adding either metric.
- Generalize beyond Eurostat EU27 guest-night data and the current fixed
  three-row snapshot shape; support different training/economic periods.
- Admit new provider profiles only with source authorization, schema checks,
  collection rights and independent provider authenticity evidence.
- Add calibrated prediction intervals and comparisons to stronger baselines.
- Do not alter frozen `finpred-run@1/@2` readers, prices, or IDs.

## Validation record

The original bundle's `PATCH_*` files record packaging-time checks and are
archival. The compiled gate is `make forecast-score-test`, also called by
`make test` and CI. Local success is not evidence of a hosted CI result,
provider compatibility, or native storage admission.

Local verification on the worktree based on `82ba6467a31ecfce15aaa8b1bb065743d750d378`
(Linux x86-64) used MuLIB `574e487fbbb184281518250989061cff842daeac`,
LibStone `4c35077601899944594737559534aafd9014f330`, and rebuilt `on1xc`
(SHA-256 `cd80def82acc24ff6a96f71fd7dddf551f214e880e830123c3bf7985f1449d23`).
`make mulib`, `env -u TMPDIR make test`, and `make native-test` exited 0.
The forecast gate also passed with an explicit private `TMPDIR`. The March
moving-average fixture produced:

| Artifact | BLAKE3 |
|---|---|
| Evaluation manifest | `a82d4b998cb03f86214dbbdfcc61bbad9f7be2b078725e18682d8d431e9f7410` |
| Score (unchanged) | `3c02c80c3c46fef5257b5a6a67c6c4719f73630243e3bcabe9642d10a2e48af9` |

The full suite also passed the offline Dragnet feed and dispatcher gates,
both v1 archive replays, and the pinned v2 recommendation and trace digests
for EUR 171/night and EUR 160/night.
