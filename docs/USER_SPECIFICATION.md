# FinPRED: Design and Implementation in MuLIB's On1x

**Status:** Implementation design, not a claim of a finished FinPRED system  
**Date:** 23 November 2026  
**Primary sources:** *FinPRED Workbook*, edition 0.1 (20 November 2026); [MuLIB](https://github.com/Chubek/mulib), including its `on1x/` and `include/` trees.

## 1. Decision in one paragraph

**Implement FinPRED primarily in On1x.** Use MuLIB's header-only C11 kernels for numerical methods, storage primitives, networking, matching, parsing, and platform services. Keep **MuLIB contracts** as the data plane; implement the **Algorithm Automat** as an On1x control plane; make **Ottmat** a smaller, typed strategy DSL that lowers to the same execution graph as native On1x strategies. Expose extensions through a capability-controlled **FinPRED SDK**, with an On1x API, a versioned C ABI, and optional sandboxed Lua. Start with **Yieldcraft accommodation pricing**, not a broad suite of unvalidated financial models.

The intended lifecycle is:

```text
observe -> normalize -> analyze -> predict/optimize -> decide -> act -> evaluate
```

Each step can produce a separately recorded artifact. In particular, a prediction is not a recommendation, and a recommendation is not permission to take an external action.

## 2. Product boundaries

The FinPRED Workbook defines eleven primary concepts:

| Concept | Meaning in FinPRED |
|---|---|
| Observation | A source value or event observed at a specified time. |
| Contract | Data plus type, semantics, units, timestamps, and provenance. |
| Dataset | A collection of typed observations or contracts. |
| Scenario | An explicit question: dates, parties, currency, constraints, etc. |
| Transformation | A versioned conversion between validated contracts. |
| Model | An estimator or forecasting relationship. |
| Algorithm | A reusable computation such as quantile or room allocation. |
| Strategy | A composition of algorithms, policies, rules, and guardrails. |
| Decision | A recommendation with a reproducible explanation. |
| Action | A separately authorized external side effect. |
| Run | A versioned record linking inputs, execution, outputs, and trace. |

**Rules:** preserve units; make missingness explicit; distinguish `observed_at`, `ingested_at`, and economic validity; store parent artifacts and immutable digests; prohibit look-ahead during replay; and fail with `insufficient_evidence` rather than manufacturing a confident answer from inadequate data.

## 3. Overall architecture

```text
        FinPRED experiences (On1x)
       CLI | TUI | GUI | Poindexter
                   |
              FinPRED SDK
        On1x API | C ABI | Lua host
                   |
       +-----------+-----------+
       |                       |
  DATA PLANE               CONTROL PLANE
  On1x + MuLIB             On1x Automat
  contracts / schemas      typed execution DAG
  normalization            Ottmat graph lowering
  units / provenance       policies / scheduling
  artifact storage         decisions / replay
       |                       |
       +-----------+-----------+
                   |
        FinPRED runtime foundation
      permissions | audit | persistence
       plugin isolation | host services
                   |
            MuLIB C11 kernels
```

### Responsibilities

- **Core (`source/core/`):** identity, semantic money and quantities, time, diagnostics, provenance, typed results.
- **Data plane (`source/store/`):** schema validation, ingestion, immutable artifacts, dataset references, point-in-time reads, migrations.
- **Automat (`source/automat/`):** graph building, type checking of edges, deterministic execution, bounded retries, status transitions, trace, replay.
- **Ottmat (`source/ottmat/`):** parser, type/effect checker, lowering to the Automat graph. It should **not** duplicate On1x's general programming features.
- **SDK (`source/sdk/`):** extension descriptors, capability grants, C ABI adapters, isolated plugin workers, compatibility checks.
- **Plugins (`plugins/`):** Dragnet (data acquisition), Yieldcraft (accommodation pricing), Poindexter (accounting/spreadsheets), future financial domains.
- **Experience layer (`source/cli/`, etc.):** operator-facing tools without privileged shortcuts around the SDK or action gateway.

The first deployment should be **local-first**: one application, local metadata database, content-addressed artifact directory, and a deterministic fixed graph. Service and distributed modes are later concerns.

## 4. What MuLIB already offers

MuLIB currently contains headers relevant to the FinPRED design. They are **building blocks**, not evidence that FinPRED's complete integration is ready.

| Need | Existing header(s) under `include/` | FinPRED usage |
|---|---|---|
| Contracts and artifacts | `mulib-contract.h`, `mulib-artifact.h`, `mulib-datum.h` | Envelopes, content identity, lineage primitives |
| Exact monetary amounts | `mulib-money.h`, `mulib-fxrate.h` | Minor-unit arithmetic, explicit FX conversion |
| Market price statistics | `mulib-statsproc.h`, `mulib-statsprice.h` | Quantiles, descriptive and robust statistics |
| Dynamic price policy | `mulib-pricecurve.h`, `mulib-competprice.h` | Lead-time percentile curve, competitor-based pricing |
| Price optimization | `mulib-priceopt.h` | Optimizing over a declared demand model / candidate prices |
| Accommodation matching | `mulib-staymatch.h` | Bounded multi-room, whole-stay allocation |
| Forecasting and testing | `mulib-histprice.h`, `mulib-backtest.h` | Baseline forecasts and holdout scoring |
| Market feeds | `mulib-marketquote.h`, `mulib-asof.h` | Checked quote snapshots and as-of semantics |
| Decision evidence | `mulib-decisiontrace.h`, `mulib-sha.h` | Structured traces and content digests |
| Ingestion | `mulib-csv.h`, `mulib-json.h`, `mulib-http.h`, `mulib-fetch.h`, `mulib-elvi-scrape.h` | File import, authorized connectors, extraction |
| Persistence / execution | `mulib-kvdb.h`, `mulib-dbtransaction.h`, `mulib-graph.h`, `mulib-cron.h` | Local storage and orchestration building blocks |
| Interfaces and extensions | `mulib-imtui.h`, `mulib-immgtk.h`, `mulib-mune.h` | TUI, GUI, controlled Lua behavior |

Especially useful implementation facts:

1. `mulib-staymatch.h` already has a bounded exact multi-room solver. Its constraints and search budget must surface as explicit diagnostics; the solver does not infer child-age policies or fetch availability.
2. `mulib-pricecurve.h` implements linear, power, exponential, and piecewise percentile curves. Place scheduling and business hysteresis **above** this numerical kernel.
3. `mulib-contract.h` validates an in-memory envelope and computes identities. A persistent schema registry, canonical JSON/YAML validation, immutable dataset store, migration rules, and trust policy still require implementation.
4. `mulib-decisiontrace.h` provides bounded events and encoding. Persisted and authenticated audit records, including full input digests and policy identities, belong in the application/runtime.
5. `mulib-competprice.h` uses floating-point prices; use exact minor-unit or fixed-scale arithmetic for money and carefully specified conversion at numerical boundaries.

## 5. On1x and KernelBind integration

On1x has a C11 backend, modules, `On1xfile` project tooling, standard-library facilities, and native KernelBind support. But **kernel discovery does not mean a header is callable or safely admitted**. The current bounded numerical profiles document reviewed calls for:

```on1x
import kernel mulib.histprice as History;
import kernel mulib.priceopt as Pricing;
```

Their available callable members are `History.ema`, `History.holt`, `Pricing.optimize`, and `Pricing.candidates`. These profiles require the documented native build configuration and **independent signed review**; no production approval is bundled. Other FinPRED kernels, including StayMatch, price curves, contracts, and storage, must not be presented as already admitted On1x imports.

### Proposed three-tier interoperability

1. **Reviewed direct KernelBind imports:** bounded numerical functions with supported scalar/record/snapshot-slice types.
2. **Small native shims/adapters:** more complex C structs, exact-money and matching APIs, error mapping, and data layouts until direct lowering is available.
3. **Host-owned capabilities:** database sessions, network fetches, filesystem access, worker lifecycle, and external actions exposed as controlled handles or RPC; do **not** give plugins raw arbitrary authority.

Do not bind a C pointer's lifetime to an ordinary On1x value without a documented owner/borrow rule. Do not confuse `unsafe` source syntax with a sandbox or permission grant.

## 6. Suggested repository layout

The existing On1x project manifest system can be used to build a **separate FinPRED repository** pinned to known MuLIB and On1x revisions:

```text
finpred/
  On1xfile
  source/
    core/              # contracts, money, date/time, errors
    store/             # registry, storage, lineage, snapshots
    automat/           # typed DAG, planner, scheduler, replay
    ottmat/            # lexer, parser, checker, graph compiler
    algorithms/        # policy adapters and numerical wrappers
    sdk/               # plugin registry, grants, host interface
    cli/               # import, validate, run, explain, replay
  interface/            # exported On1x module boundaries
  library/              # reusable, domain-neutral On1x libraries
  plugins/
    dragnet/            # source adapters
    yieldcraft/         # StayMatch and accommodation strategies
    poindexter/         # valuation/spreadsheet workspace
  native/               # C11 wrappers and reviewed bindings
  contracts/            # versioned JSON/YAML schemas
  strategies/           # Ottmat sources
  fixtures/             # frozen scenarios and observations
  tests/                # golden, replay, security, fuzz, integration
  docs/                 # ADRs, C ABI and execution contracts
```

Avoid hard-coding Yieldcraft-specific types into the general contract store or Automat scheduler. A future FX or securities plugin should reuse those layers unchanged.

## 7. On1x examples

**Status legend:** Examples A–C use syntax patterns present in the current On1x examples. They are illustrative adaptations, **not freshly compiled or executed for this document**. Example D demonstrates a **proposed FinPRED API**; its named modules and functions must be implemented.

### A. A small, pure pricing rule in On1x

This is a simplified **linear** percentile curve (`gamma = 1`) and the workbook's one-step monetary shortcut. It is deliberately not a replacement for the more general `mulib-pricecurve.h` power/piecewise behavior.

```on1x
# Percentiles are in [0, 1]. This example accepts days 0..90.
fn target_percentile(days_to_arrival: f64) -> f64
{
  assert(days_to_arrival >= 0.0 && days_to_arrival <= 90.0);
  return 0.40 + (0.75 - 0.40) * days_to_arrival / 90.0;
}

# All monetary values below are EUR cents, not floating-point euros.
fn choose_shortcut(
  current_cents: i64,
  lower_cents: i64,
  maximum_sacrifice_cents: i64
) -> i64
{
  assert(current_cents >= lower_cents);
  assert(lower_cents >= 0);
  assert(maximum_sacrifice_cents >= 0);

  if current_cents - lower_cents < maximum_sacrifice_cents
  {
    return lower_cents;
  }
  return current_cents;
}

fn apply_floor(candidate_cents: i64, floor_cents: i64) -> i64
{
  assert(candidate_cents >= 0 && floor_cents >= 0);
  if candidate_cents < floor_cents
  {
    return floor_cents;
  }
  return candidate_cents;
}

fn main()
{
  let candidate = choose_shortcut(17500, 17100, 500);
  let approved = apply_floor(candidate, 16000);

  assert(target_percentile(0.0) == 0.40);
  assert(approved == 17100);
  println(approved);  # 17100 cents (EUR 171.00)
}
```

The business rules remain at the On1x/strategy layer, while `mulib-pricecurve.h` and a declared quantile implementation supply the general numerical functions. In production, these calculations must operate on a typed `Money<EUR>` abstraction and generate decision-trace events.

### B. A forecast through the existing On1x numerical KernelBind profile

The following follows the structure of [`on1x/examples/kernel/forecast.on1x`](https://github.com/Chubek/mulib/blob/main/on1x/examples/kernel/forecast.on1x):

```on1x
import kernel mulib.histprice as History;

fn forecast(samples: slice<f64, 5>)
  -> History.Result<History.Forecast, History.Error>
{
  let ema = History.ema(samples, 0.0, 2)?;
  println(ema["point"]);
  return History.holt(samples, 0.5, 0.2, 1.0, 2);
}

fn main()
{
  let observed = array[99.0, 10.0, 12.0, 14.0, 99.0];
  match forecast(observed[1:4]) with
  {
    Ok(result) =>
    {
      println(result["point"]);
    },
    Err(_) =>
    {
      println(-1);
    }
  };
}
```

This is a **baseline numerical example**, not a validated forecasting methodology. A production run also needs model versioning, training/validation separation, as-of input eligibility, evaluation against holdouts, uncertainty representation, and output contracts.

### C. Price optimization through the existing numerical KernelBind profile

The struct/variant construction follows [`on1x/examples/kernel/pricing/main.on1x`](https://github.com/Chubek/mulib/blob/main/on1x/examples/kernel/pricing/main.on1x):

```on1x
import kernel mulib.priceopt as Pricing;

fn main()
{
  let profit = variant<Pricing.Objective>(Profit, record{});
  let linear = variant<Pricing.DemandKind>(Linear, record{});

  let model = record<Pricing.DemandModel>{
    kind: linear,
    scale: 20.0,
    shape: 1.0,
    reference: 0.0
  };

  let limits = record<Pricing.Constraints>{
    min_price: 6.0,
    max_price: 20.0,
    unit_cost: 4.0,
    min_unit_margin: 0.0,
    previous_price: 0.0,
    max_relative_change: 0.0,
    tick: 1.0
  };

  match Pricing.optimize(model, limits, profit) with
  {
    Ok(decision) =>
    {
      println(decision["price"]);
      println(decision["score"]);
    },
    Err(_) =>
    {
      println(-1);
    }
  };
}
```

`Pricing.optimize` is an optimizer over the **supplied** model and constraints. It does not prove that the demand model is correct. Obtain those inputs through versioned, evaluated contracts and apply independent business guardrails before recommending or executing anything.

### D. What a *future* FinPRED On1x strategy should look like

The following is **design pseudocode in an On1x-like notation**. `Finpred.*`, `Yieldcraft.*`, and their methods **do not exist merely because they are shown here**; the exact signatures and effects need to be implemented and validated.

```on1x
# DESIGN SKETCH -- NOT CURRENTLY A BUILDABLE FINPRED PROGRAM.
import finpred.contracts as Contracts;
import finpred.automat as Automat;
import finpred.market as Market;
import finpred.guardrails as Guardrails;
import yieldcraft.match as StayMatch;

fn recommend(scenario_ref, offers_ref, valuation_ref)
{
  let scenario = Contracts.load_validated(scenario_ref);
  let offers = Contracts.load_as_of(offers_ref, scenario.decision_time);
  let valuation = Contracts.load_validated(valuation_ref);

  let bundles = StayMatch.solve(offers, scenario);
  let comparables = Market.select_one_bundle_per_property(bundles);
  let distribution = Market.distribution(comparables);

  let percentile = Market.target_percentile(scenario.days_to_arrival);
  let candidate = Market.quantile(distribution, percentile);
  let final_price = Guardrails.apply(candidate, valuation, scenario);

  return Automat.record_recommendation(
    scenario, offers_ref, valuation_ref, percentile, final_price
  );
}
```

The intended implementation uses **typed references, explicit `Result`/error handling, and injected capabilities**; it does not hide network access or database writes inside an apparently pure function.

## 8. Contracts: what must be typed and stored

Start with exactly these four top-level kinds:

1. `hospitality.scenario@1`
2. `hospitality.offer@1`
3. `pricing.valuation@1`
4. `pricing.recommendation@1`

Their complete persisted envelopes should include `mulib` protocol version, kind, schema version, ID, provenance, observed/ingested/economic times, units, quality status, and validated payload. Large datasets should be referenced by immutable content-addressed objects rather than embedded wholesale in YAML.

An example **illustrative contract representation** (not a shipped canonical schema):

```yaml
mulib: '1.0'
kind: pricing.recommendation
schema_version: '1.0'
id: recommendation:sample-run:001
metadata:
  provenance:
    source_artifacts:
      - sha256:SCENARIO_DIGEST
      - sha256:OFFERS_DIGEST
    strategy: yieldcraft.percentile@1
  times:
    observed_at: '2026-11-20T10:00:00Z'
  units:
    currency: EUR
    price_basis: room_night
  quality:
    status: validated
    evidence: synthetic_fixture
data:
  price_minor: 17100
  intended_percentile: 0.50
  selected_percentile: 0.40
  reason: lower_percentile_shortcut
  published: false
```

The currency is EUR; the monetary decision is 17,100 **cents**, not 17,100 euros. Real schema validation must check denominators, exact number of nights, tax/fee scope, booking restrictions, freshness, and source comparability.

## 9. Yieldcraft: first complete vertical slice

The first supported question is: *For a specified arrival/departure date, party, accommodation constraints, and currency, what price does a versioned strategy recommend based on comparable, bookable competitors?*

**Deterministic pipeline:**

1. Import a frozen CSV/JSON dataset or one authorized external provider feed through Dragnet.
2. Validate raw observations and normalize them to canonical `hospitality.offer` contracts.
3. Resolve one exact-stay, feasible bundle per property using StayMatch; retain rejection reasons.
4. Compare on **final guest-payable whole-stay price**; divide by the exact number of nights to obtain effective nightly rates.
5. Construct a scenario-specific distribution and record the quantile convention and sample adequacy.
6. Calculate a target percentile based on lead time; optionally apply the one-step lower-percentile monetary shortcut.
7. Enforce an independently computed hard floor, price caps, maximum movement, and all other required constraints.
8. Produce a `pricing.recommendation` contract and detailed decision trace; **do not publish** in MVP mode.

For the workbook's synthetic test fixture, P50 = **EUR 175**, P40 = **EUR 171**, and the shortcut threshold is **EUR 5**. Since the difference is EUR 4, choose P40; with a hard floor of EUR 160, the final recommendation is **EUR 171/night** (assuming no other guardrail intervenes). This is a strategy rule, not proof of optimal revenue.

**Fail rather than improvise:** reject stale or non-bookable offers, incompatible currencies/conditions, infeasible room combinations, and insufficient independent property samples. Do not silently mix estimated rates with observed bookable rates.

## 10. Algorithm Automat and Ottmat

The **Automat** is a versioned typed DAG, not a bag of callable functions. Node families should include `Input`, `Source`, `Transform`, `Algorithm`, `Model`, `Strategy`, `Gate`, `Action`, and `Output`. Validate edge schema compatibility before scheduling. For the first release, require an acyclic plan; iterative algorithms should run as explicit bounded nodes.

Recommended architecture:

```text
Ottmat source -----------+
                         v
On1x strategy API --> Typed Automat graph IR
                         |
               validate, version, plan
                         |
               On1x graph interpreter
                         |
                artifacts + trace
```

**Ottmat's job** is to declare dataflow, typed plugin invocations, decisions, and effects. It should reuse On1x/runtime facilities for computation and never directly grant I/O authority. A separate AOT lowering into On1x can be added later if profiling demonstrates a need. An Ottmat-authored strategy and an equivalent On1x-authored strategy must have consistent graph semantics and reproducible outputs.

Run modes must be explicit: `analysis`, `recommendation`, `simulation`, and tightly authorized `execution`. Switching a source flag must **not** be sufficient to grant execution permissions.

## 11. FinPRED SDK and plugin isolation

Plugin interface categories: **Source**, **ContractProvider**, **Transformer**, **Algorithm**, **Model**, **Strategy**, **Action**, and **View**. Each plugin must declare its SDK version, contract kinds/versions, dependencies, resource limits, and exact host permissions. A plugin package should be independently versioned and content-digested for replay.

- **On1x plugins:** the preferred way to implement typed application-level algorithms and strategies.
- **C11 plugins:** a stable versioned ABI with opaque handles, explicit lifetimes, status values, and host-owned resource access.
- **Lua plugins:** optional validators, derived fields, and other narrowly scoped contract behavior mediated through the Mune host. They must not inherit arbitrary filesystem/process/network authority.
- **Untrusted native plugins:** prefer out-of-process workers with OS-enforced isolation and a constrained IPC contract. An in-process C ABI alone is not a sandbox.

Separate the **data plane** from plugin **control planes**: plugins exchange immutable artifact references and validated outputs, not untyped shared global state. All publishing, brokerage, or other external actions must pass through a host-controlled authorization/audit gateway and be idempotency-protected when possible.

## 12. Implementation plan and acceptance gates

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0 — feasibility** | Ratify core contracts and units; verify On1x build and reviewed imports; set up fixtures and ADRs. | Validate an offer and compute civil-night counts correctly. |
| **1 — local engine** | Contract store, schemas, immutable refs, provenance, CSV/JSON import, fixed-graph runner, CLI. | Import and replay a dataset by artifact IDs, with precise errors. |
| **2 — Yieldcraft MVP** | StayMatch, comparable distribution, price curve, shortcut, guardrails, recommendation trace. | Produce and replay the worked EUR 171 recommendation and its explanation. |
| **3 — Automat / Ottmat / SDK** | Typed graph plan, strategy frontend, manifests, plugin host, at least one authorized Dragnet source. | A third-party plugin integrates without patching the core; previous runs remain replayable. |
| **4 — operational** | Durable state, scheduler, approvals, historical evaluation, observability and action reconciliation. | Recommendation mode is provably side-effect free; execution is gated and auditable. |
| **5 — broader domains** | FX/portfolio verticals and independently evaluated models; distribute only if needed. | A second vertical reuses core contracts, SDK, and Automat without hospitality-specific hacks. |

### Priority checklist

- **P0:** money/units; dates and valid-time semantics; contract schemas/registry; immutable persistence; reviewed kernel adapters; StayMatch comparison correctness; deterministic decision trace.
- **P1:** graph planner, time-safe replay, durable run records, SDK isolation, Ottmat semantics, authorized Dragnet connectors.
- **P2:** Poindexter/UI expansion, richer forecasting and uncertainty models, distributed workers, live external actions.

### Minimum tests

- Invalid schema, malformed input, unknown/missing/stale fields, and incompatible currencies.
- Integer overflow and conversion edge cases for money; positive whole-stay duration across DST changes.
- StayMatch child/adult allocation, room inventory reuse, matching node-budget exhaustion, property deduplication.
- Exact quantile convention, tie behavior, effective sample size, percentile shortcut threshold and guardrail precedence.
- Point-in-time replay (no future observations or model parameters), snapshot digest stability, trace reproducibility.
- Plugin capability denial, failed/partial runs, action idempotency, and proof that recommendation mode cannot publish.

**First release target:** one executable On1x strategy, four validated contract kinds, CSV import, one exact-stay matcher, a specified quantile implementation, two curve types, two guardrails, a human-readable trace, and a replayable local run. Prefer this complete vertical slice to a large catalog of unintegrated algorithms.

## 13. Useful source references

- FinPRED Workbook, edition 0.1: chapters **1–8** (platform, contracts, Automat, Ottmat, SDK), **9–12** (Yieldcraft and statistics), and **19–21** (roadmap, decisions, interface sketches).
- [MuLIB repository](https://github.com/Chubek/mulib)
- [On1x README](https://github.com/Chubek/mulib/blob/main/on1x/README.md)
- [KernelBind limitations](https://github.com/Chubek/mulib/blob/main/on1x/KERNEL_DIRECT_USAGE.md)
- [KernelBind numerical profiles](https://github.com/Chubek/mulib/blob/main/on1x/docs/kernel-numerics.md)
- [On1x forecasting example](https://github.com/Chubek/mulib/blob/main/on1x/examples/kernel/forecast.on1x)
- [On1x pricing example](https://github.com/Chubek/mulib/blob/main/on1x/examples/kernel/pricing/main.on1x)

> **Implementation principle:** Put semantics and orchestration in On1x, put bounded low-level computation in MuLIB, and put privileged actions behind an independently enforced host boundary. The first important result is not a sophisticated forecast: it is a **correct, explainable, reproducible decision**.
