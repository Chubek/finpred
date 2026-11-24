# FinPRED engineering audit

## Read-only baseline

Inspected FinPRED `0ee376ce9cbf687092e4acb0d512fd74866c1668` before editing
tracked files. The working tree and the two dependency checkouts were clean.
The recorded MuLIB pin was `91d459e29a4ee1fc433b3ca7a9868dd1f47bb641`; it
pinned LibStone `a307d550936a10b6c58b752e56d7e475c794926e`. The supported
checkout path initializes those two gitlinks explicitly: recursive submodule
discovery fails below LibStone on a retired path without a mapping.

The audit covered project/module manifests, the staged C11 build, compiler and
GrammarEmbed, native C companions, contracts and fixtures, the CLI and package
boundaries, the full local/CI test inventory, and the operator, implementation,
and historical validation records. The baseline included 108 tracked On1x
implementation/interface files, 18 JSON Schemas, and 53 `check_*.py` tests.
Static package checks covered only the main `source/` modules and top-level
contract schemas; all 18 schema documents passed a separate Draft 2020-12
schema check.

### Baseline verification (Linux x86-64, GCC 16.2.1)

| Gate | Result before changes |
|---|---|
| App, cube and forecast build | Passed using the existing local pinned-toolchain build; application output isolated from the default build |
| Static package check and independent pricing oracles | Passed; 17100, 16000, 18000 and 17001 EUR minor units |
| Elvi search, handoff and offline network tracing | Passed; EUR 171/160 and exact v2 IDs preserved |
| `tests/run.sh` and legacy `make dragnet-test` | Both stopped at the missing `plugins/dragnet/plugin.json`; the former reached the installed SDK check |
| Competitor cube | Passed; 24 exhaustive-oracle cases, maximum-size batch, traced replay |
| Forecast CLI and score/holdout gates | Passed separately; point-in-time revisions and exact replay; holdout MSE/RMSE not implemented there |
| Price prediction | Passed all six existing model cases |
| Standalone native store and viewport | 2/2 and 3/3 CTests passed respectively; these are not CLI admission or power-loss results |
| TUI admission | Negative kernel-import probes passed; no TUI kernel admitted |

No live provider, hosted GitHub Actions, external financial action or power-loss
test was part of the baseline. No historical fixture was changed.

## Findings and acceptance boundaries

| Requests | Baseline finding and remaining acceptance boundary |
|---|---|
| 2, 21 | `b84e928` removed frozen CSV, Crossref, ECB/Eurostat and the offline source dispatcher. The replacement Elvi host is a distinct acquisition path with separate network, offer, and LLM-egress permissions. The removed adapters are recoverable from Git, but must work with the current compiler and SDK without pretending hashes are provider signatures. Provider authorization, systematic release cataloging and live rate-limit behavior require separate evidence. |
| 3, 28, 29 | The workflow ran the compiler and most application checks in one job. An early failure preempted unrelated gates. The source pins do not by themselves prove a reproducible release, and the root On1xfile is not a replacement for the staged multi-host build. Native C and On1x tests, Python oracles and external platform coverage are separate layers. |
| 4–9 | The versioned typed financial graph already uses injected host resolution and invocation, with named ports, work limits and exact replay. Ottomat v6 lowers to that graph. The legacy fixed runner, scalar DAG and contribution path remain distinct. The callable protocol, C/On1x metadata catalogs and application registry have different roles; no single compatibility check authorizes an invocation. Money/time and byte codecs are still partly domain-specific. |
| 10–12, 16–18 | The original contribution strategy consumes a frozen own-demand price grid and optimizes one decision. It does not fit the grid from bookings or verify upstream experiment validity. An estimator needs exposures, offers not purchased, availability/censoring, cancellation maturity, price variation and a defensible sampling design. Inventory coupling, opportunity costs, interval propagation and robust multi-period decisions require new inputs and replay contracts. |
| 13–16, 20 | MuLIB-backed price baselines and deterministic ensembles are not calibrated distributions; dispersion across members is not a prediction interval. Guest-night issuance, scoring and holdout replay have point-in-time vintages, but a host-declared selection freeze does not certify independent model selection. An ordinal price series cannot prove revision-time eligibility. No lawful property-level historical dataset or independent outcomes were supplied, so no empirical uplift or calibration claim is supportable. |
| 19 | The competitor cube has exact bounded matching, in-batch reuse, multiple cells/policies, and byte-exact replay. It does not persist an incremental dependency cache across batches. Competitor quotes describe guest-payable market positioning, not own willingness to pay. |
| 22, 23 | Historical pricing and scalar format versions bind different bytes and identities. Some analysis tooling is read-only and many code/policy identifiers are declared or source-level rather than exact executable attestations. New evidence must use separately versioned contracts; do not rewrite fixtures, golden archive bytes, or an old lineage fragment to modernize it. |
| 24–26 | The live store assumes a private namespace and cooperating writers. The standalone native candidate uses directory-relative no-follow operations and sync, but lacks admission as an On1x store and power-loss evidence. Static registry checks are not OS isolation. No caller can turn a recommendation, manifest, digest or mode string into authority to act. |
| 27 | Poindexter replays before projecting market-positioning runs; editable workbook cells are then only a working copy. Contribution, full forecasting/uncertainty visualization and general scenario analysis are not equivalent to the existing pricing worksheet. |

The [historical validation record](../VALIDATION.md) is preserved separately.

## What this implementation batch delivered, and what remains

| Requests | Delivered here | Not yet delivered |
|---|---|---|
| 1–3 | Read-only audit and baseline; restored CSV, Crossref, public-feed and dispatcher compatibility alongside Elvi search; six independent CI jobs and local selectors | Hosted execution of the new workflow |
| 4–9 | On1x product semantics; bounded C helpers and Python oracles. Stricter engine dependency guard, empty-unknown typed output handling, binding-checked Ottomat v6 execution, and an additive [contribution adapter](../strategies/yieldcraft/CONTRIBUTION_DAG.md) for the financial DAG | Full fixed/scalar/contribution CLI unification; one SDK registry and ABI for executable handlers; broader Ottomat composition, typed codecs and reusable money/units/time/identifier APIs |
| 10–12, 17 | [Replayable randomized exposure fit](YIELDCRAFT_DEMAND.md) with complete outcomes/cancellation follow-up and an existing optimizer handoff; no competitor prices used as own-demand evidence | Constant-elasticity, log-linear, regularized and hierarchical fits; observational identifiability diagnostics, censored-inventory estimation, seasonality and external covariates |
| 13–16 | [Matched rolling price folds](PRICE_BACKTEST.md), exact MAE, MSE, WAPE and bias, overflow-safe RMSE and explicit coverage | New MuLIB Holt-Winters/ARIMA, robust and probabilistic kernels and configurable ensembles; leakage-safe model selection across revision vintages, calibrated intervals, pinball loss and uncertainty propagation |
| 18, 19 | [Finite-stock planner](YIELDCRAFT_INVENTORY.md) with period-specific prices, opportunity cost, terminal value and an exhaustive oracle | Cancellation state transitions, robust optimization and configurable objectives; incremental cross-run caching and scenario/sensitivity extensions to the competitor cube |
| 20, 21 | [Official ECB single-vintage empirical diagnostic](../research/ecb-fx/README.md); restored Dragnet acquisition/replay checks and private spool admission | Empirical property-level outcomes and ex-ante vintages; expanded provider authentication, rate-limit policy and source revision catalogs |
| 22–24 | Historical replay and bytes preserved; separate demand evidence and format. Native process-death, contention and recovery conformance | Automatic artifact/executable capture for every analysis output; independently reviewed native On1x admission and filesystem power-loss/remount tests |
| 25, 26 | [Linux offline process supervisor](OFFLINE_WORKER.md) for bounded isolated calls; [human-approval design](ACTION_AUTHORIZATION.md) with no gateway or executor enabled | Integrating and admitting a general untrusted extension path; authenticated approvals and durable effect reconciliation |
| 27 | Poindexter displays/imports a verified v3 contribution sheet without changing v1/v2 sheet bytes | Forecast/uncertainty visualization and full scenario/evidence workbench |
| 28–30 | Relocatable C SDK and Python metadata binding; pinned toolchain; same-host build reproducibility check; exact/exhaustive oracles and rejection/regression tests | Cross-platform release/install qualification, compiler reproducibility across independent toolchain builds, broader fuzz and performance gates |

### Local post-change verification

- Rebuilt `on1xc` and GrammarEmbed from the Git pins. The upstream standard
  library project, GrammarEmbed bridge and GrammarEmbed integration tests
  passed; the latter needed its additional reference and LuaEmbed targets.
- A clean-output local `make test` passed all six FinPRED suites, including
  both Dragnet generations, the private Xvfb frontend, the native CTests
  (3/3 store and 3/3 viewport), and the offline worker probe. The sandbox
  probe also passed independently with Clang and GCC.
- The application, cube and forecast executables were byte-identical across
  two scratch/output layouts with the same host/toolchain. Both archived v1
  replays, pinned v2 run/output identities and the v3 contribution replays
  passed. No existing fixture or MuLIB/LibStone Git pin was changed.
- `actionlint`, Draft 2020-12 schema checks and `git diff --check` passed.
  Hosted CI, other platforms, and power-loss durability were not verified.
