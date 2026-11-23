# AGENTS.md — FinPRED implementation handoff

This file is the operating brief for any coding agent working in this repository.
Read it **before changing code**. Treat this project as a partially implemented
On1x application, not as a finished or production-ready FinPRED system.

## 1. Mission and non-negotiable scope

Finish FinPRED as specified in `docs/USER_SPECIFICATION.md`, using **MuLIB's
On1x** for application semantics, algorithms, orchestration and strategy
control. Assume the MuLIB checkout lives at `third_party/mulib/` (or at
`$MULIB_ROOT`). Preserve the local-first, auditable architecture:

```text
observe -> normalize -> analyze -> predict/optimize -> decide -> act -> evaluate

local CSV/authorized source -> validated typed contracts -> as-of snapshot
    -> bounded whole-stay matching -> one comparable per property
    -> quantile and lead-time curve -> shortcut -> independent guardrails
    -> recommendation + trace + immutable run record -> replay
```

A **prediction is not a recommendation**; a **recommendation is not permission
for an external action**. Until an independently authorized, audited action
gateway exists, all recommendation paths must have **no external side effects**.

Deliver a **working vertical slice before broadening the product**. Do not
replace the On1x application with Python/C/Rust, claim an unreviewed MuLIB
header is a safe `import kernel`, or add simulated network/publishing results.
Python here is only a fixture oracle, build aid and test harness.

## 2. Sources of truth, in order

1. `docs/USER_SPECIFICATION.md`: requested architecture, contracts, phases,
   acceptance criteria and known KernelBind limitations. In particular,
   sections 2, 5, 8–12 and the “first release target” are binding requirements.
2. Current **actual On1x compiler, stdlib and MuLIB headers** under
   `third_party/mulib/` at the revision you checked out. Inspect signatures;
   do not assume examples or APIs have remained unchanged.
3. Current source and tests in this repository. `docs/IMPLEMENTATION.md` and
   `README.md` describe **intent and claimed design**, not proof of execution.
4. Current, reviewed upstream On1x documentation (`on1x/README.md`,
   `on1x/stdlib/on1xfile/README.md`, `on1x/docs/modules.md`,
   `on1x/KERNEL_DIRECT_USAGE.md`, `on1x/docs/kernel-numerics.md`).

The upstream version inspected when this package was created was MuLIB
`Chubek/mulib` `master` at
`49de89acbc97efbee493d6b28d02c8f64ed4f725` (2026-11-23). Prefer this
commit for reproducible initial verification. If working against another
revision, record the SHA and any API divergences in `docs/IMPLEMENTATION.md`.
The MuLIB checkout is **not packaged**; do not vendor it into the handoff ZIP.

## 3. Current repository inventory

| Path | Responsibility / actual MVP state |
| --- | --- |
| `On1xfile`, `source/On1xfile.m`, nested `On1xfile.m` | C11-backend executable project and module declarations |
| `source/main.on1x`, `source/cli/app.on1x` | Entry point, environment-driven CLI, run, selftest, trace, replay |
| `source/core/{csv,date,money,contracts,format,serialize}.on1x` | Bounded CSV parsing, civil date/UTC checks, exact cents, domain records, JSON serialization |
| `source/yieldcraft/{matcher,strategy}.on1x` | Bounded exact-room matching, property distribution, percentile recommendation, pricing guardrails |
| `source/algorithms/quantile.on1x` | Type-7 quantile in integer minor units; linear/quadratic percentile curves |
| `source/automat/graph.on1x` | **Fixed seven-node** typed/acyclic plan, not a generic scheduler |
| `source/ottmat/ottmat.on1x` | Exact eight-line declaration checker, not a full parser/type/effect checker |
| `source/sdk/sdk.on1x` | Closed built-in strategy allowlist, not a C ABI/plugin host or sandbox |
| `source/store/artifacts.on1x` | BLAKE3-addressed local text objects and run manifests; **single-writer, non-atomic** |
| `contracts/*.schema.json` | Four versioned JSON Schema 2020-12 envelopes, not proof of complete runtime schema validation |
| `strategies/yieldcraft.ottmat` | One constrained declarative strategy |
| `fixtures/` | Frozen EUR 171/night and multi-room EUR 160/night scenarios, plus invalid input |
| `tests/` | Python fixture oracle, source hygiene check, shell runtime integration script |
| `plugins/`, `native/` | Preparatory descriptors/notes; **no operational generic plugin loading** |
| `bin/build.sh`, `bin/finpred`, `tests/run.sh` | Build wrapper, launcher, runtime integration checks |

Do not describe stubs or uncompiled source as “implemented and verified.”

### Confirmed evidence as of the handoff

- `python3 tests/check_fixtures.py` **passed**: `17100` minor units for
  the main fixture and `16000` for the multi-room oracle.
- `python3 tests/validate_static.py` **passed**: 15 On1x modules, four schemas.
- **No successful On1x build, native executable run, or integration test** is
  recorded. This environment had no `third_party/mulib` checkout, no `on1xc`.
- `bin/build.sh` currently fails with “Missing MuLIB ...”. This is an
  **environment blocker**, not a demonstration that the source compiles.
- KernelBind safe admission / independent signed production review is **not
  established**. Current stdlib adapters for arrays, files and digests involve
  raw native bridges.

## 4. First task: build the source for real

In the FinPRED root, install or select MuLIB and its On1x toolchain. A possible
local bootstrap, after obtaining the pinned MuLIB checkout, is:

```sh
# Only if third_party/mulib is not populated yet:
git clone https://github.com/Chubek/mulib.git third_party/mulib
git -C third_party/mulib checkout 49de89acbc97efbee493d6b28d02c8f64ed4f725
git -C third_party/mulib submodule update --init on1x/third_party/libstone

cmake -S third_party/mulib/on1x -B third_party/mulib/build/on1x -DBUILD_TESTING=ON
cmake --build third_party/mulib/build/on1x --parallel 4
./bin/build.sh
python3 tests/check_fixtures.py
python3 tests/validate_static.py
./tests/run.sh
```

Existing operators can instead set `MULIB_ROOT` and/or `ON1XC`. The wrapper
expects an On1xfile build artifact at `target/dev/finpred` by default; the
launcher honors `FINPRED_EXE` if the build publishes elsewhere.

**Diagnose actual compiler errors and runtime failures**; fix them minimally
in On1x, keeping exact semantics. Inspect and run the upstream small examples
when syntax, imports, nominal records, loops, array handle lifetimes or
stdlib function names differ. Never silence a compiler error by replacing
On1x computation with an unrelated application-only C shim.

Save a verification log in `docs/IMPLEMENTATION.md` containing the exact
MuLIB SHA, On1x compiler version/path, OS/compiler/ABI, commands, exit codes,
fixture outputs, warnings, and any failed or skipped gates. Do not claim
success until the executable **actually** builds and runs.

### CLI and environment contract

```sh
./bin/finpred selftest
./bin/finpred run
./bin/finpred replay <64-character-run-id>
./tests/run.sh
```

Runtime configuration is via `FINPRED_SCENARIO`, `FINPRED_OFFERS`,
`FINPRED_VALUATION`, `FINPRED_STRATEGY`, `FINPRED_HOME`, and the launcher-provided
`FINPRED_MODE` / `FINPRED_RUN_ID`. Defaults are the frozen fixture files,
`strategies/yieldcraft.ottmat`, and `.finpred/`. Do **not** treat setting
`FINPRED_MODE=execution` as an authorization grant; it must be denied.

## 5. Semantics that MUST remain invariant

- **Money:** signed i64 minor units (EUR **cents**); no floating-point money.
  Validate nonnegative bounds; check overflow *before* addition/multiplication.
  Scenario/valuation prices are nightly; offer totals + taxes + fees are
  **guest-payable whole-stay** amounts. Divide by the number of **civil** nights
  with specified half-up rounding, not timezone-dependent elapsed hours.
- **Dates/time:** valid Gregorian civil dates (currently 1970–2399); exact UTC
  timestamps; distinguish `observed_at`, `ingested_at`, economic valid
  intervals, and `decision_at`. Replay must never consume later observations.
  Fail closed on missingness, stale, nonbookable, invalid or incomparable offers.
- **Matching:** one row = one explicitly observed room inventory unit; never
  reuse a room. Respect adult, child and total capacities; select a feasible
  whole-stay bundle, bounded by search budget/room count. Keep **one cheapest
  feasible bundle per independent property**, with rejection/infeasibility
  diagnostics. Do not invent child policies or availability.
- **Statistics:** currently Hyndman–Fan type 7 (`h=(n−1)p`), interpolation
  rounded half-up to whole-stay cents, then rounded half-up to nightly cents.
  `target_bps=0` means lead-time curve; linear/quadratic curves start at
  P40 and reach P75 at 90 days. The P40 shortcut applies only when its saving
  versus intended is **strictly less** than the declared threshold.
- **Guardrails:** apply the hard intersection of floor, cap and maximum
  movement from previous price, **after** shortcut selection. Empty
  intersection is an error, not an optimistic recommendation.
- **Evidence:** at least three feasible independent properties, plus the
  scenario's stricter `min_properties` requirement. Insufficient evidence
  must yield an explicit failure, not a fabricated point estimate.
- **Replay:** artifacts/parents/strategy/graph and policy identities must
  be frozen, digest-checked, reproducible and as-of safe. Changing any input
  or strategy content must change identity or cause an integrity failure.
- **Effects:** `run` produces a recommendation with `published=false`;
  replay must **never publish or mutate**. Only a host-controlled, separately
  authorized/audited gateway may ever perform actions.
- **Bounded execution:** existing MVP limits include 512 offer rows,
  2 MiB input files, 10 accepted room offers/property, 4 selected rooms,
  8 adults/8 children and at most 1,000,000 inspected subsets. If raised,
  document memory/time/overflow implications and test finite budgets.

The current CSV reader intentionally accepts only exact unquoted ASCII
columns. Adding general CSV/JSON ingestion must be a **versioned, tested**
expansion, not a silent change to canonical input semantics.

## 6. Ordered work queue

Work in small, independently testable changes. The **next agent starts at P0**;
do not jump to speculative features before it passes.

### P0 — compile and verify the existing first release (blocking)

1. Populate the pinned toolchain; build through the **real** On1xfile driver.
2. Repair type/import/borrow/ownership/FFI build failures without replacing
   On1x logic. Validate every `On1xfile.m` and import against the actual loader.
3. Execute `selftest`, two fixture runs, invalid-scenario rejection and
   `execution` denial. Run replay with actual stored snapshots.
4. Validate generated JSON against **all four** schemas using a test tool;
   audit serialization for escaping, exact data types, provenance and units.
5. Test the digest paths and corruption detection; ensure no hidden writes on
   replay. Record emitted artifacts and trace details in the verification log.

**Exit gate:** a compiled On1x binary passes `tests/run.sh`, all emitted
JSON validates, and failures are explicit. If this cannot be achieved, commit
the smallest reproducible failure and document it honestly.

### P1 — harden the local engine and evidence chain

1. Add table-driven **positive and negative tests** for bad headers/field
   counts, malformed dates/timestamps, currency or unit mismatches, stale and
   future observations, invalid validity windows, duplicate inventory,
   excessive rows, missingness, bounds, and currency-specific rounding.
2. Add overflow boundaries, Type-7 ties and endpoints, exact shortcut
   threshold equality, empty guardrail intersections, one-property-vs-many-room
   bias, exhausted matching budget, child occupancy, DST-crossing stays.
3. Make artifact publication **crash-atomic**, idempotent and safe from
   concurrent writers; guard directories/path traversal/symlinks and verify
   full run manifest integrity. Add an integrity/corruption regression suite.
4. Distinguish immutable normalized contracts from raw source files;
   validate envelopes at persistence boundaries, record parent artifact IDs,
   model/strategy/quantile/guardrail versions and source provenance.
5. Add a documented migration policy, run status/diagnostics and
   deterministic error categories (especially `insufficient_evidence`).

**Exit gate:** reproducible point-in-time `run`/`replay` by immutable IDs,
including corruption/failed-run cases, independent property sampling and a
security-tested local store. No network or external actions yet.

### P2 — complete and independently test Yieldcraft MVP

1. Verify numerical and matching parity with applicable MuLIB kernels where
   APIs and **independent admission** permit. If not admitted, retain bounded
   pure On1x implementations and explicitly document the difference.
2. Add property-level rejection explanations, explicit allocation witnesses,
   deterministic tie-breaking, full-stay tax/fee comparability and input
   sample adequacy diagnostics; compare against a separately implemented oracle.
3. Ensure linear/quadratic percentile curves, shortcut and all guardrails
   are configurable, versioned, traceable, and tested against pinned fixtures.
4. Introduce a concrete fixed-graph runner rather than merely declaring node
   metadata, while retaining exact intermediate output contracts.

**Exit gate:** fixture A yields `recommendation_minor=17100`,
`reason=lower_percentile_shortcut`, `published=false`; fixture B yields
`recommendation_minor=16000`, `reason=guardrail_adjustment`, and both replay
byte-for-byte. Failure tests never publish or make up prices.

### P3 — genuine Automat, Ottmat and SDK (not current stubs)

1. Design a typed, versioned **acyclic DAG IR** with Input, Source,
   Transform, Algorithm, Model, Strategy, Gate, Action, Output; validate
   edges, dependency types, effects, scheduler bounds and deterministic order.
   Add run modes `analysis`, `recommendation`, `simulation`, `execution` with
   authorization orthogonal to mode selection.
2. Implement Ottmat lexer/parser/type+effect checker and lowering to **the
   same DAG IR** as native On1x strategies. Do not implement a second execution
   engine or a full general-purpose language; equivalence tests are required.
3. Add versioned plugin descriptors, compatibility and dependency checks,
   declared contract kinds, resource limits and **host-granted capabilities**.
   Implement a stable versioned C ABI with opaque handles and explicit
   lifetime/error semantics, and isolated workers for untrusted native code.
4. Restrict optional Lua/Mune extensions to explicit host capabilities.
   No arbitrary FS/network/process authority and no implicit `unsafe` grant.
5. Introduce one authorized Dragnet data-source adapter with fixture/replay
   tests. An extension must integrate without patching FinPRED core.

**Exit gate:** a third-party extension runs with independently checked
capabilities; denied permissions and incompatible schemas fail; On1x/Ottmat
strategies produce equivalent plans/results; old runs remain replayable.

### P4 — operational capabilities, then broader domains

Implement durable scheduler/state, transactional metadata, authenticated audit,
approvals, idempotent host action gateway, action reconciliation, historic
holdout evaluation/forecast uncertainty and observability. After passing
recommendation side-effect tests and real authorization gates, expand to
Poindexter and FX/portfolio verticals **without putting hospitality logic
into the domain-neutral store/scheduler**. Distributed execution is optional
and should not precede a correct local system.

## 7. KernelBind, FFI and security rules

- MuLIB header availability **does not** imply a callable, reviewed On1x import.
  As inspected, bounded numerical profiles support `mulib.histprice` EMA/Holt
  and `mulib.priceopt` optimize/candidates, subject to the documented
  signed-review gate. Do **not** invent safe imports for StayMatch, Money,
  PriceCurve, Contract, storage, networking or arbitrary callbacks.
- Check `third_party/mulib/on1x/KERNEL_DIRECT_USAGE.md` and corresponding
  ExoML/ExoLib review/profiles before claiming a call safe. An `unsafe`
  block does not grant capabilities or prove memory safety.
- MuLIB uses header-only C11 kernels and one implementation translation unit.
  Reuse the canonical On1x/MuLIB build planner; avoid duplicate implementation
  macros or manually forged ABIs. C11 adapter code is permissible only where
  explicitly reviewed/documented—not a substitute for On1x application logic.
- Native handles must have clear owner/borrow/close lifetime rules. Do not
  store raw pointers in general On1x values; treat existing i64 array handles
  and standard-library raw bridges as trusted, limited resources needing tests.
- No automatic production trading, accommodation price publication, scraping
  without authorization, credential logging, hidden background process or
  plugin filesystem write. Keep `.finpred/` and secrets out of source control.

## 8. Test obligations for every change

At minimum, run and report (1) the Python oracle, (2) source/schema hygiene,
(3) On1x build, and (4) `tests/run.sh` **when toolchain is present**. Do not
merge a semantic change solely because Python passes. Add focused tests for
all changed behavior, including negative and determinism tests. Compare
outputs across clean re-runs and pinned compiler versions. A regression or
skipped test must be called out with its exact reason.

For repository consistency:

- Add/edit the declaring `On1xfile.m` when creating or renaming any `.on1x`.
- Keep versions in the contract schemas, strategy, graph, artifacts and trace
  synchronized. Existing published run formats cannot be rewritten silently.
- Preserve exact money units and the legacy frozen EUR 171 / EUR 160 fixtures.
  Add a new fixture for new semantics rather than mutating the oracle inputs.
- Prefer explicit typed `Result`/error flow and bounded allocation over traps
  where the compiler supports it. Do not swallow or auto-retry bad evidence.
- Update `README.md` and `docs/IMPLEMENTATION.md` with every new verified
  capability, changed command, limitation and actual test evidence.

## 9. Agent handoff protocol / definition of done

Work in priority order; scope one PR/commit to one coherent gate. Before
editing, inspect the relevant source and upstream API. After editing, leave
an actionable handoff describing:

1. Files changed and why; interfaces, schema/run versions and behavior changes.
2. Exact build/test commands and observed pass/fail counts; tools/SHA/ABI.
3. Remaining blockers, security caveats and the **next** specific gate.
4. Source and fixture evidence for any claimed numerical or replay behavior.

Never mark a phase complete based only on file existence or a static grep.
**“Done” for the first release means** a real On1x C11 build, working
validated local contract ingestion, exact-stay matching, a specified quantile,
two curves, two pricing guardrails (plus movement), human-readable trace,
immutable/replayable run, side-effect-free recommendation mode, and passing
negative/security tests. **“Done” for the full design** additionally requires
the P3/P4 acceptance gates above; otherwise describe the exact remaining
features as not implemented.

If blocked by missing MuLIB, compiler or review authority, do not fabricate
success or bypass admission. Complete safe source/tests/docs work, record the
blocker and exact reproduction steps, and stop at the appropriate gate.
