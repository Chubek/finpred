# FinPRED — Financial prediction and decision research in On1x

[![Verify FinPRED (master)](https://github.com/Chubek/finpred/actions/workflows/verify.yml/badge.svg?branch=master)](https://github.com/Chubek/finpred/actions/workflows/verify.yml?query=branch%3Amaster)

FinPRED is a **local-first**, contract-driven analysis system built primarily
in [MuLIB's On1x language](https://github.com/Chubek/mulib). Its currently
usable pricing application is **Yieldcraft**, which recommends nightly EUR
prices for frozen accommodation scenarios. The CLI also runs read-only scalar
analysis. The codebase provides separate compiled interfaces for typed
financial graphs, reproducible data sources and point-in-time guest-night
forecasting, plus Poindexter views of verified market-positioning runs.

**A recommendation is not an authorization to trade, book, publish or modify
a third-party price.** There is no enabled live action gateway.

## Yieldcraft: demand-based pricing and market positioning

Yieldcraft's primary objective is to choose the feasible nightly price `p`
that maximizes expected contribution, `(p - c) × D(p | x)`, where `c` is the
marginal cost and `D(p | x)` is expected demand at that price under the
relevant market conditions `x`. Competitor quotes can describe the market
or inform a demand model, but they cannot by themselves identify willingness
to pay or the contribution-maximizing price.

```sh
./bin/yieldcraft --demand fixtures/demand_contribution.csv  # synthetic example
./bin/yieldcraft --market-positioning                       # secondary strategy
```

The primary strategy requires a point-in-time demand snapshot and marginal
cost. It evaluates only prices with demand estimates that also satisfy
the guardrails, and never falls back to competitor positioning. See
[strategy selection](strategies/README.md) for the input format and replay.

The secondary market-positioning strategy still matches independent
properties and applies percentiles and guardrails. Its frozen fixture
outcomes are:

| Scenario | Recommendation | CLI reason |
|---|---:|---|
| Five feasible independent properties | **EUR 171/night** | `lower_percentile_shortcut` |
| Multi-room, three feasible independent properties | **EUR 160/night** | `guardrail_adjustment` |

These are deterministic positioning decisions, **not** demand predictions
or guarantees of financial performance. Both report `published=false`.
Contribution runs use `finpred-run@3`; existing `finpred-run@1` and
`finpred-run@2` archives keep their recorded bytes and identities.
The optional [`bin/yieldcraft-demand`](docs/YIELDCRAFT_DEMAND.md) estimator
can build a demand grid from frozen first-party price experiments. It does
not infer demand from competitor offers or claim empirical uplift.
The [finite-inventory planner](docs/YIELDCRAFT_INVENTORY.md) is a separate
On1x API for explicitly supplied net-sale probabilities over multiple periods.

## Build and verify

The supported verification target is Linux x86-64 with a pinned MuLIB source
checkout and the nested LibStone revision. Use the recorded dependency pins
and build instructions in [INSTALL.md](INSTALL.md):

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
make mulib           # builds the local On1x compiler + GrammarEmbed
make                 # builds build/dev/finpred
./bin/finpred selftest
make test            # full suite; see INSTALL.md for verification dependencies
make dragnet-search-test  # current offline Dragnet search and handoff
make dragnet-test    # restored frozen CSV, Crossref, public feeds and dispatcher
make native-test     # isolated C store review target
```

See the [coverage notes](tests/COVERAGE.md) for the Dragnet compatibility gates
and `make forecast-score-test` for a separate
[forecast scoring and evaluation replay](docs/FORECAST_SCORING.md) check.
[Verify FinPRED](.github/workflows/verify.yml) is the sole Actions workflow:
it has independent compiler, pricing, forecasting, plugins, storage and security
jobs on Ubuntu 24.04. It does not publish or deploy. The badge reflects
hosted workflow status on `master`, not verification of a local checkout.

## Architecture and entry points

| Component | Source and purpose |
|---|---|
| **Yieldcraft** | [`strategies/`](strategies/) and [`plugins/yieldcraft/`](plugins/yieldcraft/) — expected-contribution pricing and secondary market positioning |
| **Automat** | [`source/automat/`](source/automat/) — fixed legacy recommendation runner, scalar DAG, general bounded typed financial DAG and immutable in-memory artifacts |
| **Ottomat** | [`source/ottomat/`](source/ottomat/) — legacy and scalar strategy grammars; v6 lowers to the typed financial graph, with no strategy-owned authority |
| **SDK** | [`source/sdk/`](source/sdk/) — trusted, statically linked versioned handler descriptors, callable ports and capability checks |
| **Core price prediction** | [`source/core/price_prediction.c`](source/core/price_prediction.c) — MuLIB-backed forecasts from frozen price histories via [`finpred price-predict`](GUIDE.md#predict-prices-from-a-history) |
| **Dragnet** | [`plugins/dragnet/`](plugins/dragnet/) — Elvi web acquisition, optional GPT analysis, and offline capture handoff to plugins and core consumers |
| **Forecast baselines** | [`plugins/forecast_baselines/`](plugins/forecast_baselines/) — moving-average and seasonal-naive monthly guest-night models; later actuals are used only to score issued forecasts |
| **Poindexter** | [`plugins/poindexter/`](plugins/poindexter/) — verified market-positioning and contribution sheets, terminal spreadsheet and optional ImmGTK X11 frontend |
| **Artifact store** | [`source/store/`](source/store/) — versioned immutable object/run evidence in a private cooperative store |
| **Native store candidate** | [`native/`](native/) — standalone security review target; **not** the CLI's admitted durable backend |

Core engines own validation, evaluation, and artifact semantics. Applications
bind optional packages through explicit host interfaces; strategy files cannot
load packages or grant capabilities.

The legacy runner supports archived market-positioning runs. Scalar analysis
prints a result without saving a run, and the typed financial graph is a
library interface. See [strategy selection](strategies/README.md) for pricing
inputs. The secondary competitor-based path can use CSV inputs, run Dragnet
once, or use a verified frozen capture.
For exact party-specific quote matching across multiple frozen stays and
strategies, see the separate [competitor pricing cube](docs/COMPETITOR_CUBE.md).
The `finpred forecast` commands issue, score, aggregate and replay guest-night
forecasts from an immutable release catalog in a separate local store.
See the [forecast workflow](GUIDE.md#run-point-in-time-forecasts).
Use [`finpred price-backtest`](docs/PRICE_BACKTEST.md) for a separate
horizon-specific diagnostic on ordered price series, not revision-aware evidence.
The [ECB FX exercise](research/ecb-fx/README.md) is empirical but single-vintage;
it is not a hospitality demand or pricing validation.

## Start here

1. [Install and verify](INSTALL.md) — pin the compiler and execute the tests.
2. [Operator guide](GUIDE.md) — run, replay, explain and inspect frozen evidence.
3. [Implementation and acceptance record](docs/IMPLEMENTATION.md#acceptance-record)
   and [test coverage](tests/COVERAGE.md) — historical results and the checks
   that produced them. See the [engineering audit](docs/ENGINEERING_AUDIT.md)
   for the pre-change baseline and acceptance boundaries.
4. [Algorithm Automat](source/automat/README.md) and
   [Ottomat](source/ottomat/README.md) — typed graph semantics, frontend and replay.
5. [Plugin developer guide](PLUGIN.md) and
   [Dragnet's shared capture contract](plugins/dragnet/README.md#shared-handoff-to-plugins-and-core-code).
6. [Point-in-time forecasting](plugins/forecast_baselines/README.md) and
   [forecast scoring](docs/FORECAST_SCORING.md).
7. [Poindexter workbench](plugins/poindexter/workbench/README.md) or
   [optional GUI](plugins/poindexter/gui/README.md).
8. [Native storage admission decision](native/STORE_ADMISSION.md) and
   [optional offline worker](docs/OFFLINE_WORKER.md) — separate storage and
   process trust boundaries.
9. [Product and future milestones](docs/USER_SPECIFICATION.md) — design
   objectives, not evidence that every listed capability exists today.

## Security and reproducibility boundaries

- Source conformance tests use frozen fixtures and loopback HTTP, not live
  providers. Live polling is separate, explicit opt-in and subject to provider
  terms.
- An ECB reference rate is **not** an executable FX quote; Eurostat aggregate
  guest nights are **not** property-level inventory or pricing comparables.
- Algorithm and plugin metadata are not authority tokens. Existing linked
  packages are trusted code; the optional isolated worker is not attached to them.
- Run and source BLAKE3 digests provide byte integrity, **not** provider
  authenticity or signatures.
- The CLI store assumes cooperating publishers and trusted directories. The
  standalone native store is a review candidate, not an admitted On1x
  backend. Neither its C tests nor the CI badge establish power-loss
  durability or hostile-filesystem confinement for the CLI.
- Do not rewrite stored run identities, mutate old fixtures, or enable
  external actions when adding a strategy, model or plugin.
