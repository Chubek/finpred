# Six-workstream integration audit

The integration starts from FinPRED `85b8a0b4f74880bcea09266885044da26ecf51d3`.
Each workstream used a separate Git worktree. The integrated code and test
checkpoint is `f90885d9685b8183e4766fb23aa2f9369ee53f8e`. The MuLIB
`91d459e29a4ee1fc433b3ca7a9868dd1f47bb641` and nested LibStone
`a307d550936a10b6c58b752e56d7e475c794926e` pins and historical fixture bytes
were not changed. The [integration requirements](INTEGRATION_REQUIREMENTS.md)
describe the shared ownership and trust boundaries.

| Workstream | Integrated | Still open |
| --- | --- | --- |
| Engineering | Fixed a scratch-path-dependent GrammarEmbed wire limit without relaxing the bound. Added hash-locked schema validation, deterministic versioned Linux CLI bundles with relocation/replay checks, seeded differential and malformed-input cases, and a non-gating performance benchmark. | Fresh hosted verification, independently rebuilt compiler reproducibility, broader fuzzing/performance infrastructure, and macOS/Windows/other platform qualification. |
| Demand | Four observational On1x fits with exposure-normalized booking outcomes, pre-price strata, cancellation maturity, identification diagnostics, bounded interpolation, temporal holdout and typed exact-replay evidence. | Censored and unavailable demand, separate covariates for competitor context/seasonality/lead time, fitted hierarchical variance, calibrated predictive intervals and independent validation on eligible first-party data. |
| Forecasting | A revision-aware guest-night On1x API, three point models, exact rational errors, and pinned issuance/scoring replay. Two separate ECB data diagnostics reproduce results offline and include a negative result. | Additional time-series types, Holt-Winters, ARIMA, robust regression, configurable ensembles, nested horizon-specific selection, probability forecasts and calibrated intervals, probabilistic metrics, live release-vintage studies, and integration of the new library into the CLI and stores. |
| Runtime and SDK | Pure typed graph composition, host descriptor drift checks, bounded native/Ottomat replay bundles, and C/Python typed-port compatibility. | One execution runtime for all legacy routes, reusable Ottomat source subgraphs, automatic executable/dependency/model provenance for every operation, and general C/Python execution APIs. |
| Optimization and workbench | Stress analysis on the existing experimental demand output, coupled two-night robust inventory decisions, explicit nominal/fixed/hold comparisons, independent exact oracles, and editable Poindexter CSV import. | Calibrated uncertainty propagation, multi-category inventory and cancellation state, persistent cube caching, verified scenario workbench visualizations, and defensible observed-policy backtests. |
| Security, storage and evidence | Stronger offline supervisor constraints, a mandatory real sandbox probe with diagnostics, and scoped offline feed grants with frozen byte validation. KernelBind admission remained fail-closed; native contract, historical bytes and process-death tests remain separate from the CLI. | Hosted Security diagnosis, production plugin admission and identity management, native CLI store admission and power-loss/remount verification, expanded live provider controls/catalogs and offline human authorization. External financial execution remains disabled. |

The observational demand panel is intentionally not an optimizer input:
its outcome is an estimated kept rate under observed assignments, not
independent decision evidence. The stress tool accepts the existing
experimental snapshot and separately supplied assumptions. Guest-night
forecast counts are not booking probabilities. An integration test caught
Dragnet's historical source-closure pin changing when the graph work edited
the shared callable implementation. The graph now performs its specialized
descriptor checks locally and dispatches through the unchanged SDK using the
checked descriptor. The original Dragnet closure and policy digests pass
without modifying their expectations. The legacy forecast code subject
uses the v1 host's explicit module closure, so adding unlinked vintage
libraries cannot re-pin an older forecast. The compiler suite now
pins the v1 source subject from the base revision using fixed test compiler
bytes. A forecast and score issued by the base CLI also replayed byte-for-byte
with the integrated same-toolchain CLI. Neither empirical ECB study
validates commercial uplift, and the
[public hospitality data assessment](../research/HOSPITALITY_DATA.md) explains
why bookings-only records were not used to fit conversion demand.

## Hosted and local evidence

The [hosted run at the base revision](https://github.com/Chubek/finpred/actions/runs/45479500972)
gave these results:

| Job | Hosted base |
| --- | --- |
| Compiler | Failed at `make test-compiler`; upstream GrammarEmbed/stdlib integration passed |
| Pricing | Passed |
| Forecasting | Passed |
| Plugins | Passed |
| Storage | Passed |
| Security | Failed at `make test-security` |

Detailed hosted logs required authentication. The same Compiler step failed
locally with a deep `TMPDIR`: the merged GrammarEmbed response
exceeded the 4 MiB transport budget due to repeated absolute source spans.
The fix stages source in a shallow directory and normalizes staged response
locations; it leaves the upstream wire limits intact. The final Compiler
suite passed with Clang 22 and with the extracted Ubuntu GCC 13.3.0 driver
and host system libraries, which is not a full Ubuntu GitHub runner
reproduction. The real
bubblewrap probe passed on the local Linux host, including with that GCC
driver. The hosted Security root cause remains unconfirmed; the workflow
now preflights the actual sandbox without changing runner security policy
or bypassing the full job. No new hosted run was triggered.

Local `make test` passed all six suites, including the private X11 test,
historical pricing/Dragnet checks, and the real offline worker, with 3/3
native store and 3/3 viewport tests. After the forecast subject fix,
the Compiler and Forecasting suites and the release gate also passed,
and the base CLI archives replayed with the new binary.

Other passing checks on Linux x86-64: upstream GrammarEmbed bridge,
GrammarEmbed and stdlib project CTests (3/3); native store CTests with Clang
ASan/UBSan (3/3 on a live Btrfs mount); workflow lint; all 30 checked-in
Draft 2020-12 schemas; and relocatable release conformance (two matching
archives, malformed archive rejection, historical price and cube IDs, and
forecast replay). Run `python3 tests/check_cli_release.py` on a committed
checkout with the two pinned source checkouts. See
[INSTALL](../INSTALL.md) and [coverage](../tests/COVERAGE.md) for test
prerequisites.

`python3 tests/benchmark_price_backtest.py --repeat 5` produced medians of
4.32 ms and 15.15 ms for the 64/256-observation naive cases, and 4.72 ms and
33.93 ms for ensemble. These are local elapsed times for one Linux x86-64
host (Core i7-11700K, GCC 16.2.1), include CLI startup, and do not establish
a performance improvement or cross-host target.
