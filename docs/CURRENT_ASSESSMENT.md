# FinPRED implementation assessment and remaining gates

Based on `master` `34b2f89d9dae9b52bb47e453bbe01a44d36064bc`, 2026-11-23.

## Pre-patch source and CI checkpoint

The immediate predecessor `fadcd470` has a green GitHub Actions workflow
(run `45206909673`). The latest `34b2f89d` CI was in progress when assessed;
its README replacement is corrected in this patch.
It includes the main On1x C11 build and integration, standalone native-store
CTest, package consumers, Dragnet public feeds and offline source dispatcher.
The source also includes:

- a typed, bounded `automat.financial-graph@1` and in-memory artifact/replay
  engine, plus an independent legacy fixed Yieldcraft runner;
- Ottomat 6 financial-graph lowering with compiled native parity tests;
- SDK callable protocol with code/policy pins, port types, effect/mode checks,
  bounded work and trusted static handler injection;
- Eurostat-derived guest-night projections and two pure forecast models
  with chronological walk-forward test fixtures and frozen graph replay;
- existing hospitality pricing run v1/v2 replay, terminal and optional GUI
  Poindexter, offline Dragnet sources, and a standalone native store candidate.

This is a functional local-first financial analysis MVP. The green base CI
does not demonstrate production readiness, third-party isolation, or a
fully admitted durable storage backend.

## Forecast scoring and replay

`forecast_baselines.score.evaluate` adds a **post-issuance score contract**
with explicit original training and later scoring cutoffs. It re-executes
the original pinned forecast and compares frozen bytes, reprojects a later
actuals source snapshot, and emits one typed score or explicit unknown.
This fills a reproducible evaluation primitive missing from the pre-patch
On1x runtime; existing Python accuracy checks remain independent oracles.

The compiled `make forecast-score-test` gate now also exercises
`analysis.guest-nights-evaluation@1`: an in-memory manifest binding the
host-selected evidence, code and policy pins, and score bytes. Replay checks
the expected ID and both outputs without touching a store. See
[the contract and verification commands](FORECAST_SCORING.md). This does not
report a new hosted CI result.

## Remaining highest-value implementation gates

1. **P0—Confirm hosted CI** with the pinned compiler and mandatory scoring,
   evaluation and Dragnet conformance steps.
2. **P1—Evaluation-run publication**: connect the manifest to a trusted
   catalog and write-once score artifact publication under reviewed storage
   semantics. Do not add scoring to the existing pricing `finpred-run@1/@2`
   format.
3. **P1—Holdout aggregation**: scored/unknown coverage, exact MAE/bias and
   overflow-safe MSE/RMSE. Preserve train/validation/holdout separation and
   prevent selection on the final holdout.
4. **P1—More generic data planes**: legal licensed/public feeds, source
   catalog/revision selection, multiple units and geographies, FX research
   without promoting reference quotes to executable prices.
5. **P1—Pluggable runtime**: consolidate separate SDK/Dragnet registries,
   narrow trusted host invocation and explicit authority; untrusted code
   requires separately reviewed process isolation.
6. **P1—Filesystem safety**: independent KernelBind storage review,
   directory-relative no-follow publication, sync failure semantics,
   power-loss/remount validation before claiming durable commits.
7. **P2—Prediction**: calibrated intervals, missing-data diagnostics, model
   comparison and backtesting against independent economic outcomes.
8. **P2—Actions and operations**: immutable intent/approval/audit protocol,
   idempotent authorized worker execution; no strategy-driven implicit
   trading, booking or price publication.

Always preserve the synthetic acceptance recommendations of EUR 171 and
EUR 160 per night and all historical run IDs/digests. A digest is an integrity
identity, not proof that a provider authored an observation.
