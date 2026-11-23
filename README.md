# FinPRED — Financial prediction and decision research in On1x

FinPRED is a **local-first**, contract-driven analysis system built primarily
in [MuLIB's On1x language](https://github.com/Chubek/mulib). Its currently
usable application is **Yieldcraft**, which recommends nightly EUR prices for
frozen accommodation scenarios. The codebase also has a typed financial
Algorithm Automat, a versioned Ottomat frontend, a static callable SDK,
reproducible Dragnet sources, analysis-only guest-night forecasting baselines,
and Poindexter spreadsheet frontends.

**A recommendation is not an authorization to trade, book, publish or modify
a third-party price.** There is no enabled live action gateway.

## Proven synthetic pricing outcomes

| Scenario | Recommendation | Reason |
|---|---:|---|
| Default, five feasible independent properties | **EUR 171/night** | P40 shortcut below P50 |
| Multi-room, three feasible independent properties | **EUR 160/night** | Floor guardrail adjustment |

These are deterministic decisions based on frozen comparables, **not**
trained demand forecasts or guarantees of financial performance. Historical
`finpred-run@1` archives are replay-only; the active Yieldcraft writer uses
`finpred-run@2`. Preserve their recorded bytes and identities.

## Build and verify

The supported verification target is Linux x86-64 with a pinned MuLIB source
checkout and the nested LibStone revision. Use the recorded dependency pins
and build instructions in [INSTALL.md](INSTALL.md):

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
make mulib           # builds the local On1x compiler + GrammarEmbed
make                 # builds FinPRED's C11-backed On1x CLI
./bin/finpred selftest
make test            # application, package, source, model conformance suites
make native-test     # isolated C store review target
```

`make test` also runs the compiled Dragnet tests and the new
[forecast-scoring](docs/FORECAST_SCORING.md) conformance suite. Refer to the
[CI workflow](.github/workflows/verify.yml) and
[test coverage index](tests/COVERAGE.md) for negative cases and actual
verification outcomes. A successful standalone C test does **not** imply
that its native API has been independently admitted into On1x KernelBind.

## Architecture and entry points

| Component | Source and purpose |
|---|---|
| **Yieldcraft** | [`plugins/yieldcraft/`](plugins/yieldcraft/) — exact multiroom matching, percentile decision, guardrails |
| **Automat** | [`source/automat/`](source/automat/) — fixed legacy recommendation runner, scalar DAG, general bounded typed financial DAG and immutable in-memory artifacts |
| **Ottomat** | [`source/ottomat/`](source/ottomat/) — versioned strategy grammar, typed financial lowering, no strategy-owned effects |
| **SDK** | [`source/sdk/`](source/sdk/) — trusted, statically linked versioned handler descriptors, callable ports and capability checks |
| **Dragnet** | [`plugins/dragnet/`](plugins/dragnet/) — frozen CSV, Crossref evidence, ECB/Eurostat snapshot acquisition and offline Source dispatch |
| **Forecast baselines** | [`plugins/forecast_baselines/`](plugins/forecast_baselines/) — moving-average/seasonal-naive monthly guest-night research and post-issuance scores |
| **Poindexter** | [`plugins/poindexter/`](plugins/poindexter/) — verified-run projection, terminal spreadsheet and optional ImmGTK X11 frontend |
| **Artifact store** | [`source/store/`](source/store/) — versioned immutable object/run evidence in a private cooperative store |
| **Native store candidate** | [`native/`](native/) — standalone security review target; **not** the CLI's admitted durable backend |

The financial graph is tested through independent compiled On1x consumers.
The CLI still distinguishes legacy persisted pricing runs from read-only
scalar analysis (`./bin/finpred run --engine scalar`). Do **not** assume the
new financial graph has already replaced the legacy persisted-run protocol.

## Start here

1. [Install and verify](INSTALL.md) — pin the compiler and execute the tests.
2. [Operator guide](GUIDE.md) — run, replay, explain and inspect frozen evidence.
3. [Implementation and acceptance record](docs/IMPLEMENTATION.md) — see
   implemented interfaces and the limits of their recorded tests.
4. [Algorithm Automat](source/automat/README.md) and
   [Ottomat](source/ottomat/README.md) — typed graph semantics, frontend and replay.
5. [Plugin developer guide](PLUGIN.md) and
   [Dragnet Source dispatch](plugins/dragnet/SOURCE_DISPATCH.md).
6. [Point-in-time forecasting](plugins/forecast_baselines/README.md) and
   [forecast scoring](docs/FORECAST_SCORING.md).
7. [Poindexter workbench](plugins/poindexter/workbench/README.md) or
   [optional GUI](plugins/poindexter/gui/README.md).
8. [Native storage admission decision](native/STORE_ADMISSION.md) — review
   the missing host/KernelBind primitives before stronger durability claims.
9. [Product and future milestones](docs/USER_SPECIFICATION.md) — design
   objectives, not evidence that every listed capability exists today.

## Security and reproducibility boundaries

- All normal build/test acquisitions are synthetic or offline fixture based;
  external polling is explicit opt-in and subject to provider terms.
- An ECB reference rate is **not** an executable FX quote; Eurostat aggregate
  guest nights are **not** property-level inventory or pricing comparables.
- Algorithm and plugin metadata are not authority tokens. Untrusted plugins
  require a reviewed worker isolation boundary, not merely a static descriptor.
- Run and source BLAKE3 digests provide byte integrity, **not** provider
  authenticity or signatures.
- The private store currently supports cooperating publishers. Power-loss
  durability and hostile-filesystem confinement are separate release gates.
- Do not rewrite stored v1/v2 run identities, mutate old fixtures, or enable
  external actions when adding a strategy, model or plugin.
