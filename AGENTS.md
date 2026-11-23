# AGENTS.md — Continue implementing FinPRED in On1x

> **Repository:** https://github.com/Chubek/finpred  
> **Base inspected:** `master` at `b1d6f027f99b3738148d416843bfa30bc9c51cb1` (2026-11-23)  
> **Upstream pinned by the repository's acceptance record:** MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`; LibStone `b5c962721a32df18b2fb22de136c1f2ef8b6390d`  
> **Audience:** autonomous or human coding agents making actual, tested changes.  
> **Status:** executable, tested *local Yieldcraft vertical slice*; **not** a complete general-purpose FinPRED platform.

This is an **implementation mandate**, not a request to produce another design document. Study the current code before changing it, make narrowly scoped, working improvements, run the relevant tests, and leave independently verifiable evidence. When working from a later commit, **re-inventory and reconcile this file first**; its snapshot is historical, not an assertion that current `master` remains identical.

## 0. Mission, architecture, and hard rules

FinPRED is a contract-driven financial observation, analysis, forecasting, optimization, decision, and controlled-action platform. Preserve this conceptual chain:

```text
observe -> normalize -> analyze -> predict/optimize -> decide -> act -> evaluate

  sources / Dragnet                 DATA PLANE: On1x + MuLIB
       |                   validated, versioned, as-of contracts
       v                               + immutable artifacts
  transformations -----------------------------+
                                                |
                                                v
                                     CONTROL PLANE: On1x Automat
                                     Ottomat -> typed execution DAG
                                     algorithms / rules / gates
                                                |
                                                v
                                    decision + trace + run manifest
                                                |
                         review / authorization / action gateway
                         (NOT CURRENTLY ENABLED BY THE CLI)
```

- **On1x is FinPRED's primary implementation language.** Keep application semantics, validators, domain algorithms, strategy logic, and the Automat in On1x. Use MuLIB C11 kernels for carefully scoped lower-level facilities and high-performance computations; use Python only for tests, tooling and independent reference oracles. Do not quietly replace the application with Python, C++ or Rust.
- **Maintain a domain-neutral core.** Keep hospitality rules under `source/yieldcraft/` and `plugins/yieldcraft/`, not inside a universal store, scheduler, SDK or contract envelope.
- **Contracts before computation.** Every decision input must identify its kind/version, units, source, observed/ingested/valid times, and immutable evidence. The program must separate an observation, forecast, recommendation, intent and executed action.
- **Recommendation is NEVER authorization.** All current built-in packages are pure/read-only except host-controlled local recording; `execution` remains denied. No live trade, price publication, booking, or outbound write is allowed by changing a strategy file or plugin descriptor.
- **Do not sacrifice replay for new features.** Existing v1 and v2 run IDs, bytes, digests, schema semantics and historical pricing results must remain readable without rewriting them.
- **No fabricated safety or completion claims.** A C header, `.on1x` module, JSON manifest, standalone C test, compiler-generated binding, signed test fixture or documentation entry is not itself proof of an admitted safe import or a working runtime capability.
- **Local first.** Do not start with distributed execution, model marketplaces, live scraping, automated trading or a broad UI rewrite. Complete the typed engine, safe native boundary and replay invariants first.

### Source precedence

1. `docs/USER_SPECIFICATION.md` — product scope, architectural intent and acceptance milestones; it is a **design**, not proof that code runs.
2. `docs/IMPLEMENTATION.md`, `docs/RUN_FORMAT.md`, `native/STORE_ADMISSION.md`, `source/store/README.md`, `PLUGIN.md`, `INSTALL.md` — current documented implementation, run compatibility, testing and known safety limits. Their claims must be verified by actual execution.
3. Actual source, headers, schemas, manifests, tests and the checked-out MuLIB/On1x toolchain. If they disagree with prose, record the discrepancy, correct code/tests or documentation appropriately, and do not silently change a persisted protocol.
4. Pinned MuLIB sources: `on1x/README.md`, `on1x/KERNEL_DIRECT_USAGE.md`, `on1x/docs/kernel-bind.md`, `on1x/docs/kernel-numerics.md`, `on1x/docs/kernel-review.md`, plus matching `include/mulib-*.h` and On1x standard-library modules.

If `docs/USER_SPECIFICATION.md` contains examples marked proposed, do not assume their modules or generic signatures already exist. Avoid speculative On1x syntax: copy *compilable forms* from the repository and add a compile/run fixture for new language constructs.

## 1. Actual checkpoint and inventory (do not regress)

The inspected repository has much more than its earliest scaffold. **The historical introductory inventory in the original `AGENTS.md` is stale**; use the following as the updated starting point and confirm it against `git status`/`git log`.

| Component / path | Verified-from-source current role | Not yet achieved |
|---|---|---|
| `On1xfile`, `source/*/On1xfile.m`, `bin/build.sh` | On1xfile C11 application build; Poindexter local library dependency | Fully portable, routinely CI-verified toolchains |
| `source/core/{csv,date,money,contracts,serialize}.on1x` | Strict bounded CSV, civil dates, EUR integer cents, as-of checks, four envelope serialization paths | General financial units, multi-currency/FX, universal schema registry |
| `contracts/{hospitality.scenario,hospitality.offer,pricing.valuation,pricing.recommendation}@1.schema.json` | Four versioned JSON Schema 2020-12 envelopes checked against fixture outputs | Complete runtime general-purpose schema validation/migration |
| `source/yieldcraft/{matcher,strategy}.on1x` | Exact bounded room-subset/occupancy matching, one cheapest eligible bundle/property, curve, shortcut, guardrails and evidence | Full hospitality policy semantics; probabilistic demand forecasting |
| `source/algorithms/quantile.on1x` | Integer-cent Type-7 quantile, linear/quadratic lead-time policy | General weighted distributions/statistical algorithm registry |
| `source/automat/{graph,runner}.on1x` | Validates/executes **one fixed seven-node** plan with effect and output checks | Arbitrary typed DAGs, node plugins, job scheduler, retry state |
| `source/ottomat/{tokens,ottomat}.on1x`; `strategies/*.ottomat` | Bounded `ottomat 1/2` fixed-graph parser/checker; default plus five named price profiles | Real general-purpose strategy grammar and graph lowering |
| `source/sdk/{packages,static_host}.on1x`, `source/sdk/sdk_v2.{c,h}` | Static metadata/compatibility checks across Dragnet, Yieldcraft, Poindexter; versioned C ABI | Dynamic discovery/loading, invocation, process isolation, enforcement of real usage budgets |
| `plugins/dragnet/` | Host-selected **offline frozen CSV** import and eligible offer JSONL output | Authorized network/remote adapters and streaming checkpoints |
| `plugins/yieldcraft/` | Standalone callable On1x strategy package; no store or publication authority | Fully dynamic plugin registration |
| `plugins/poindexter/` | Verified pricing-sheet CSV projection | General accounting contract types/valuation models |
| `plugins/poindexter/workbench/` | Separate On1x terminal spreadsheet with formulas, edits, scripting, persistence, import | General spreadsheet/accounting workbench; large/unbounded spreadsheets |
| `source/store/artifacts.on1x`, `docs/RUN_FORMAT.md` | BLAKE3 objects, v2 lineage + old v1 replay, cooperating-writer staged publication | Hostile-filesystem confinement and proven power-loss durability |
| `native/store.{c,h}`, `native/tests/`, `native/STORE_ADMISSION.md` | Standalone directory-relative C11 store candidate with local Linux tests | **Not** invoked by compiled FinPRED On1x CLI; no approved storage KernelBind profile |
| `tests/run.sh`, `tests/check_*.py`, `fixtures/` | Native CLI integration, independent oracle, corruption, profile, package, SDK, workbench and replay tests | A hosted CI pipeline and cross-platform/fault-model qualification |

### Golden results and compatibility anchors

Maintain these immutable **synthetic** acceptance outcomes (EUR **cents per night**):

- Default fixture: `17100`, `lower_percentile_shortcut`, 5 feasible independent properties, 2 rejected offers, `published=false`.
- Multi-room fixture: `16000`, `guardrail_adjustment`, 3 feasible properties, 1 infeasible property, `published=false`.
- Existing v1 and v2 run IDs, normalized artifacts, raw bytes, content digests and trace digests must remain stable under an unchanged versioned engine. `fixtures/replay_v1.json` contains archived original v1 data; keep it byte-preserving.
- V2 lineage includes raw and normalized parent artifacts (including *rejected* offer observations in source order), the seven graph nodes and versioned policy identities. An output's content-addressed fingerprint is an integrity identifier, **not** a signature or authenticated provenance.
- Five named policies (`value-p40`, `balanced-p55`, `premium-p75`, `lead-linear`, `lead-quadratic`) must continue producing their independently recorded fixture outputs. Unknown or malformed profile declarations must fail before a run is published.
- `replay`, `explain`, `evidence` and Poindexter projections must verify frozen runs without writing to the store. Test run-tree bytes, timestamps and inodes when asserting read-only behavior.

Do **not** change older run formats to make new features convenient. Introduce **new** graph/strategy/contract/run versions with explicit readers and migration rules where semantics change; keep original replay engines for prior versions.

## 2. Environment and mandatory first actions

At the beginning of every session:

1. Read `git status --short`, `git log -5 --oneline` and the current SHA. Preserve unrelated working tree changes. Resolve any conflict between this document and source inventory.
2. Confirm MuLIB/LibStone pins; if a newer toolchain is used, record both source SHAs and any changed callable profiles. Never upgrade them as an unrelated side effect.
3. Read the specific source, manifests, tests and architecture decisions for the chosen gate. Do not edit by filename-based guessing.
4. Reproduce the baseline build and tests **before** behavior changes when the toolchain is available; record failure modes and environment blockers. Existing tests may document previous success but do not replace running them on the working branch.
5. Declare a small change set, acceptance criteria, interfaces and immutable fixture coverage. Prefer one coherent PR/commit per gate.

Expected Linux x86-64 bootstrap, assuming the pinned MuLIB source exists:

```sh
export MULIB_ROOT="${MULIB_ROOT:-$PWD/third_party/mulib}"
git -C "$MULIB_ROOT" rev-parse HEAD
git -C "$MULIB_ROOT/on1x/third_party/libstone" rev-parse HEAD
cmake -S "$MULIB_ROOT/on1x" -B "$MULIB_ROOT/build/on1x" \
  -DBUILD_TESTING=ON -DON1X_REQUIRE_LIBSTONE=ON \
  -DON1X_LIBSTONE_ROOT="$MULIB_ROOT/on1x/third_party/libstone"
cmake --build "$MULIB_ROOT/build/on1x" --parallel 4 --target on1xc
./bin/build.sh
./bin/finpred selftest
python3 tests/check_fixtures.py
python3 tests/validate_static.py
./tests/run.sh
```

See `INSTALL.md` for `ON1XC`, `FINPRED_EXE`, `TMPDIR`, `jsonschema==4.26.0` and clean installation. If missing dependencies block execution, **do not mark integration passed**; finish permissible standalone code/tests/docs and record exact blockers and commands.

Native standalone store baseline:

```sh
cmake -S native -B build/native \
  -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
cmake --build build/native --parallel 4
ctest --test-dir build/native --output-on-failure
```

These native tests **do not** certify the On1x store or grant safe KernelBind admission.

### Existing callable On1x style (use as a compiler-checked reference)

This is the shape of the **existing**, statically linked Yieldcraft entry point documented in `PLUGIN.md`, not a proposed generic plugin API. It takes **already loaded CSV bytes**; host code owns file access, storage, artifact IDs and replay. Compile an independent consumer using the paths and flags in `plugins/yieldcraft/README.md` before relying on it:

```on1x
import plugins.yieldcraft.entry as Yieldcraft;

fn nightly_minor(scenario: string, offers: string, valuation: string) -> i64
{
  let r = Yieldcraft.recommend("recommendation",scenario,offers,valuation);
  return r["recommended_cents"];
}
```

The actual `source/automat/runner.on1x` currently returns an `Output` containing `Scenario`, `Valuation` and `Recommendation`; it does **not** dynamically dispatch arbitrary algorithm names. Do not write invented imports such as `import kernel mulib.staymatch` and call them safe unless upstream KernelBind independently supports and admits that exact signature.

## 3. Work queue: required order and measurable exit gates

Use the gates below, rather than spending effort on unrelated kernels, speculative models, or a large GUI rewrite. Tasks inside a gate can be split across independent workers; interfaces and version semantics must be agreed before parallel changes. If a gate depends on unavailable independent security review, **do not bypass it**: continue on the next independent gate with the unsafe capability disabled.

### Gate S0 — Freeze the baseline, automate its verification (highest leverage)

**Owner paths:** `tests/`, `bin/`, `INSTALL.md`, `docs/IMPLEMENTATION.md`, optionally `.github/workflows/`.

- Add a CI workflow that provisions the pinned MuLIB/LibStone toolchain (or uses a transparently pinned, checksum-verified build), compiles the On1x C11 executable, runs oracle/static/full integration checks, builds the native store, and runs its CTests.
- Cache only reproducible build intermediates; never cache `FINPRED_HOME` state as test evidence or introduce secret credentials to fixture tests.
- Run focused tests under separate clean temporary stores; publish concise machine-readable test summaries and artifact/run hashes to CI logs.
- Retain explicit unsupported-platform/skipped indicators rather than substituting an untested platform build.
- Add a source/test coverage index mapping each claimed feature to at least one positive and one negative compiled-execution test.

**Exit:** CI passes from a clean checkout; historical v1/v2 identities, five strategies, 17100/16000 results and the read-only replay assertions remain unchanged. Document exact pinned versions and every skipped gate.

### Gate S1 — Safely integrate the native store (security-critical, review-gated)

**Owner paths:** `native/store.{c,h}`, `native/STORE_ADMISSION.md`, `source/store/`, On1x upstream binding profile as necessary, `tests/check_store*.py`, `tests/check_write_failure.py`, `docs/RUN_FORMAT.md`.

The standalone candidate uses Linux directory-relative filesystem operations, no-replace installation and file/directory sync. **The CLI still uses the old On1x private-store path.** Complete the missing cross-language security contract, not merely a C shim that happens to link.

1. Specify a **sealed, typed On1x store handle** with explicit read-only/read-write grants, ownership, lifetime, `close`, and structured error outcomes. Paths and raw file descriptors are not application-level capabilities.
2. Work with upstream On1x/Exotract/ExoML KernelBind on a canonical profile: known headers, strict C types, native implementation-TU plan, reviewed adapters, correct record/handle/error lowering, and independently signed authorization. **No review key ships with FinPRED.** Do not label a standalone test or self-issued signature as production approval.
3. Preserve candidate host semantics: `openat2`-based confinement where supported, no-follow/no-cross-device constraints, owner/type validation, no-replace install, bounded I/O, content comparison on an existing name, and distinct uncertain-sync outcomes.
4. Migrate `source/store/artifacts.on1x` behind a narrow storage interface once the **compiled On1x** caller and review gate work. Reads/replay must not create, sync or repair directories. Publish every referenced object durably **before** the manifest. Never emit success for a possibly unsynced manifest.
5. Test adversarial symlink swaps, nonregular files, hardlink restrictions, directory traversal, 1-byte and max-size objects, short writes, `ENOSPC`, `EINTR`, file/dir sync failures, competing writers, failures just before and after install, and external sentinels. Separately test **real/simulated power loss plus remount** on each claimed filesystem; process `kill` is insufficient.
6. Recover from partial publishing only by documented idempotent reattempt and explicit status reconciliation. Never overwrite committed content or silently delete another writer's stage.

**Exit:** independently admitted/verified On1x storage profile; compiled FinPRED CLI uses it without a fallback to an unsafe path; all v1/v2 replays and fixed fixture digests unchanged; power-loss tests justify any durability claim. If approval is unavailable, keep `native/` as an isolated candidate and report **blocked**, not done.

### Gate P1 — Make the Algorithm Automat general, typed and deterministic

**Owner paths:** `source/automat/`, new `source/automat/*` modules and `On1xfile.m`, `tests/check_fixed_runner.py`, new graph tests.

**Current:** `graph.node(0..6)` and `runner.run(...)` execute one fixed chain. Preserve this **legacy plan** and its serialized version, and introduce a new graph-plan version alongside it.

Implement:

- A versioned `NodeDescriptor` with stable ID, owner plugin, input/output contract kinds (with versions), pure/read/record/action effect classification, declared resource budget, deterministic code/policy identity, and required host capability set.
- Graph representation with explicitly named ports and edges, typed edge validation, unique node/port IDs, no undeclared imports, graph input/output bindings, and explicit handling of optional/missing inputs.
- Deterministic **topological sort**, cycle rejection and dependency planning; stable tie-breaking (e.g. declaration order then ID); bounded nodes/edges/depth; no unbounded recursive dispatch.
- A registry of **statically linked, trusted On1x handlers first**. Do not conflate a manifest declaration with a callable handler. Support two truly independent registered pure algorithms and a transformation in a single graph as the first generic fixture.
- Run-state machine: `planned`, `validated`, `running`, `recommended`, `blocked`/`failed`, and explicitly gated future execution states. Model errors as typed outcomes, not synthetic prices or silent partial success.
- Immutable input snapshots, deterministic node memoization (only if input/policy/code version matches), resource accounting and parent references for each output.
- Effects and capabilities checked **at planning and immediately before invocation**. Do not grant `action` by trusting strategy source; do not dispatch an action in any MVP mode.

Suggested *conceptual* interface (not asserted to be implemented On1x syntax):

```text
Graph.validate(plan, registry, grants) -> Result<ValidatedPlan, PlanError>
Graph.toposort(validated) -> Result<OrderedNodes, CycleError>
Automat.run(validated, immutable_inputs, mode) -> Result<RunRef, RunError>
Automat.explain(run_id) -> DecisionTrace
```

**Exit:** two different registered On1x algorithms execute through a nontrivial typed DAG; invalid edges, unknown nodes, cycles, bad versions, resource overflow and action/effect escalation fail **before** any effect; same pinned inputs produce byte-identical node outputs/trace. All old Yieldcraft `fixed-graph@1` runs still replay under their original semantics.

### Gate P2 — Extend Ottomat as a *strategy DSL*, not a second systems language

**Owner paths:** `source/ottomat/`, `strategies/`, `tests/check_ottomat_plan.py`, `docs/`.

**Current:** `ottomat 1/2` handles a fixed seven-node declaration and, in v2, a policy profile. Retain these decoders for archived strategies. Define **new explicit language version** for general graphs.

Required language features:

- Version header, imports by registered algorithm/contract identity, typed named inputs/outputs, let-bound graph node results, algorithm/transform/strategy calls, conditional and matched-result routing, `emit`, and explicit declarative effects.
- Lexical grammar with bounded input size, source spans, deterministic parse trees, meaningful errors with line/column, no implicit identifier resolution or unbounded evaluation.
- Name/type/effect checker: schema kind and major-version compatibility, units and currency constraints, declared capability checks, no automatic conversions, no untyped global environment.
- Lower to **exactly the same versioned Graph IR** as a native On1x builder. An Ottomat strategy must not have its own less-restricted runtime.
- Keep loops and model iteration as bounded algorithm nodes; no arbitrary recursion or hidden network/filesystem operations in the DSL.
- Stable serialization/code hashes: each run records Ottomat source digest, compiler/lowering version, resolved plugin versions and resulting graph digest.

Minimal new-program acceptance scenario: a saved scenario input -> validated offers -> existing comparable distribution -> an independently registered pure comparison/diagnostic algorithm -> existing pricing strategy -> guardrail -> emitted recommendation. In a separate test, register an extra pure algorithm and use it without editing the parser or fixed Yieldcraft runner.

**Exit:** equivalent native On1x and Ottomat graph definitions execute the same handlers and produce the same semantic result and **semantically corresponding node trace** (source text and plan identity may legitimately have different digests); malformed syntax, incompatible types, unknown imports and attempted effects are rejected. Archived `ottomat 1/2` declarations still parse and replay byte-for-byte.

### Gate P3 — Turn static SDK metadata into an invocable plugin runtime

**Owner paths:** `source/sdk/`, `plugins/*/`, `PLUGIN.md`, `tests/check_sdk*.py`, new worker tests.

**Current:** v1 and v2 C descriptor ABIs and On1x package checks have static tables for Dragnet, Yieldcraft and Poindexter, with documented host budgets and **no dynamic invocation**. Keep existing C ABI compatibility and current manifest interpretation. Add a new SDK/protocol version when extending semantics.

- Build a registry that resolves declared `Source`, `ContractProvider`, `Transformer`, `Algorithm`, `Model`, `Strategy`, `Action` and `View` kinds to **actual verified callable implementations**, with immutable package identities and artifact digests.
- Start with **statically linked trusted On1x plugins**; add an out-of-process worker/IPC mode for untrusted or separately distributed plugins. Do not claim that an in-process C ABI or Lua `pcall` forms a sandbox.
- Specify narrow versioned C ABI structs and opaque handles with ownership, borrow duration, allocation/freeing, thread-safety, cancellation, error/timeout, feature negotiation and binary-compatibility policy.
- The host independently enforces resource/capability grants, input/output schema checks, filesystem/network visibility, CPU/memory limits and action permissions. Metadata matching is not runtime resource metering.
- Process isolation: allowlist origins and methods; deny credentials, host filesystem, arbitrary dynamic libraries, subprocesses and network by default. Pin process/IPC policy versions to run metadata. If practical OS facilities cannot guarantee a claim, state the weaker guarantee explicitly.
- Lua via MuLIB Mune must execute in a restricted host with disabled dangerous global facilities and explicit memory/instruction/time budgets. No Lua validator receives implicit source-plugin privileges.
- Conformance test: a separately authored plugin with no FinPRED-core source modifications is discovered, validated and invoked; a rejected manifest cannot invoke its entry point; malformed responses and worker crashes become typed failures; a plugin cannot publish a price.

**Exit:** one real independently registered third-party *pure algorithm* and one source adapter can be invoked through the SDK; host denies unknown capabilities and incompatible contracts; versioned plugins can coexist; prior runs replay using pinned implementation versions. Do not mark complete based on successfully loading `plugin.json` alone.

### Gate P4 — Contract registry and generic data plane

**Owner paths:** `source/core/`, `source/store/`, `contracts/`, `source/sdk/` registration interfaces, new tests.

- Generalize contract envelopes without changing existing four `@1` schemas. Add registered kind/major/minor schemas, content-addressed immutable payload references, parent lineage, explicit presence states (`present`, `unknown`, `not_applicable`, `stale`, `redacted`), and source/quality diagnostics.
- Separate `observed_at`, `ingested_at`, `valid_at`/economic period and `decision_at`; enforce as-of reads in transformations, algorithms, models and backtests. Never use a later-known datum in historical replay.
- Introduce typed money and quantity semantics for at least one additional domain. EUR minor-unit logic stays exact; cross-currency operations require an explicit **observed, timestamped** FX contract, not an implicit conversion.
- Provide a small, queryable registry/index for `kind`, `scenario`, source, as-of time, parent and run ID; immutable object bytes remain the authority. For the local release, an index may be rebuilt from verified run/object data and must not determine immutable artifact identity.
- Schema upgrades require explicit compatibility/migration procedures and recorded transform identity, never silent changes to price units or fee inclusion.

**Exit:** a new contract kind and a versioned transformation are registered from a plugin without editing the core schema switch; invalid version, late observation, missing quantity unit, corrupted parent and incompatible currencies are rejected. Existing hospitality fixtures remain identical.

### Gate P5 — Expand Dragnet lawfully and reproducibly

**Owner paths:** `plugins/dragnet/`, contract/SDK extensions and acquisition tests.

- Keep frozen CSV ingestion as the baseline. Add one **explicitly authorized** source integration (prefer licensed/public API over general scraping), with source metadata, rate limiting, retries/backoff, pagination, checkpoints, partial-batch status and immutable acquisition evidence.
- Source identity, observed time, receipt/ingest time, provider terms and data-retention policy must be part of the adapter contract. Capture raw source evidence or a permitted minimal reproducibility record.
- Never let the source plugin call a trading/publishing gateway or silently normalize away missing taxes/fees/cancellation conditions.
- Test duplicate source records, partial download, interrupted checkpoint, invalid/stale data, different provider timezones, and mismatched snapshots. Support offline replay with no network access.

**Exit:** authorized adapter converts a known provider fixture into validated versioned observations and a reproducible dataset; partial input is reported honestly; disabling network yields a deterministic replay from stored evidence. Do not fabricate live-feed results.

### Gate P6 — Prediction, optimization and evaluation become real capabilities

**Owner paths:** new `source/models/`, `source/algorithms/`, contracts/models, plugin registry, backtest tests.

The current Yieldcraft percentile policy is a **deterministic decision strategy**, **not** a trained demand predictor. Do not label descriptive market percentiles as forecasts.

- Add a typed `Forecast` contract: target, horizon, observed-as-of time, model/code/config identity, point estimate, uncertainty/interval or explicit unavailable status, training cutoff and provenance.
- Implement basic baseline models in On1x (e.g. moving averages/seasonal naive) and optionally reviewed MuLIB Histprice/PriceOpt bindings where genuinely appropriate. Do not invent callable KernelBind profiles.
- Add train/validation/holdout separation, walk-forward replay, no look-ahead from training or future model selection, baseline comparisons, MAE/RMSE and calibration diagnostics where applicable.
- Model `insufficient_evidence`, stale data, out-of-distribution conditions and forecast uncertainty explicitly; forecasts are never conflated with guaranteed financial performance.
- Add a second small domain (e.g. FX research or portfolio valuation) to prove shared core contracts, Automat, SDK, replay and audit generalize without embedding hotel concepts into universal code.

**Exit:** two model implementations can be selected via the same graph/SDK, reproducibly backtested against frozen point-in-time inputs; failure/uncertainty artifacts are typed; another financial domain runs without a separate platform core.

### Gate P7 — Operations, Poindexter and actions (after all earlier safety gates)

- Extend Poindexter through versioned valuation/worksheet input contracts, never by passing unverified mutable sheet pointers into strategies. Preserve `poindexter-workbook@1` and the verified-run vs editable-copy distinction.
- Implement durable local schedules, run cancellation/deadlines, bounded retries for *transient* failures, resource usage metrics and explicit incomplete-run states. Avoid distributed scheduling until local recovery is proven.
- Add an **independently host-controlled** action gateway only after all core safety and audit gates: capability-specific grants, approval identity, policy evaluation, idempotency keys, external effect audit, timeout reconciliation, and operator-controlled dry-run/simulation.
- Recommendation/analysis/simulation modes must never write to any external action target; capability denial must be tested from malicious strategy, plugin and native worker entry points. No execution just because a textual flag says `execution`.

**Exit:** scheduling survives process restarts without duplicate successful runs, simulations do not cause real external effects, and a separately approved action is auditable/reconcilable. Until fully tested, **disable execution rather than provide a partial live publishing interface**.

## 4. Cross-cutting correctness requirements

### Financial arithmetic, scenarios and evidence

- EUR is in signed **integer cents** in the current MVP; no binary `f64` arithmetic for monetary storage/guardrails. Parsed room base+fees+taxes is gross whole-stay price; divide only after computing the specified Type-7 whole-stay quantile, then round half-up to nightly cents.
- A room quote is a bookable offer for the **exact dates and guest conditions**. Do not compare dissimilar stay lengths, currencies, mandatory-fee scopes or conditions without explicit adjustment, contract and trace.
- Maintain one cheapest feasible room bundle per independent property (unless a declared alternative distribution method intentionally changes sampling). Do not count many room types as multiple competitor properties.
- `target_bps` and named profile rule versions are distinct choices. Shortcut: select P40 only when the intended-price minus P40 price is **strictly less** than `shortcut_cents`; equality does not trigger. Guardrails must apply after shortcut; empty floor/cap/movement intersection fails, not clamps to an invalid number.
- Preserve current bounded design: 2,000,000 bytes/file, 512 offer rows, 10 admitted rooms/property, 4 selected rooms, 8 adults + 8 children, one million inspected subsets. New limits require contract/test/version discussion rather than changing constants silently.
- No silent currency conversion, inferred future knowledge, sold-out price substitution, fabricated confidence, hidden outlier deletion or malformed-input recovery that changes financial meaning.

### KernelBind and native code

- MuLIB's `include/mulib-*.h` inventory is **not** a whitelist of callable safe imports. The inspected On1x compiler explicitly rejects unadmitted storage imports. Approved bounded numerical examples are documented separately and require operator-selected independent review.
- A C shim may implement a narrow native boundary when justified, but application semantics and control stay in On1x. Do not embed arbitrary plugin code in the host process for convenience or add unreviewed `unsafe` imports to bypass the admission gate.
- Every new native boundary must document ABI version, alignment, integer sizes, threading, lifetimes, ownership/cleanup, error status, resource limits, memory safety, one-TU implementation/linkage and independent review status. Add negative tests from a **compiled On1x** caller, not only C unit tests.
- Do not add production credentials, privileged action tokens or untrusted tool/plugin instructions to an artifact snapshot or trace. External data and plugin outputs are untrusted inputs.

### Versioning and reproducibility

- Pin compiler, MuLIB, LibStone, SDK ABI, plugin code, schema and strategy policy versions for reproducibility. A source hash is not the same as a semantic policy identifier.
- Read-only replay never updates an object, run, index (if externally visible), access-control state or original manifest. Data corruption is surfaced, never repaired silently.
- A new engine must retain **legacy execution** for v1/v2 archived runs or supply a validated migration that preserves the ability to verify exact old meaning; do not regenerate old IDs using new algorithms.
- Append new fixtures, run versions and schemas; do not overwrite golden samples to make tests green.

## 5. Test strategy and acceptance matrix

A change is complete only when it has **compiled On1x evidence** (where relevant), an independent oracle or conformance case, negative tests, and regression coverage.

| Category | Required checks |
|---|---|
| Build and packaging | Clean On1x C11 build, correct `On1xfile.m` declarations, standalone package consumer, deterministic dependency lock/pins |
| Contracts | Schema-valid and semantic-invalid inputs; missing/stale/redacted; incompatible kind/major; wrong currency/units; source times |
| Financial math | Overflow/underflow, zero, half-up ties, percentiles 0/40/50/75/100, equal-price ties, shortcut equality, empty guardrail range |
| StayMatch | Duplicate room inventory, occupancy feasibility, adult/child allocation, max room count, property dedup, exhausted search budget |
| Automat/Ottomat | Type mismatch, missing port, cycle, unknown node, declaration-order reproducibility, forbidden effect, wrong plugin version, malformed source |
| Storage | Bit flips, missing or extra object, wrong-role artifact, same/different-content conflicts, multiwriter races, symlink/special-file attacks, partial sync, power loss |
| Plugins | Wrong ABI/schema/effect, fake capabilities, over-budget input, worker crash/timeouts, denied network/fs/action, correct cleanup |
| Prediction | Chronological train/validate/test, unavailable future observation, late-ingested data, baseline comparison, source bias and uncertainty |
| Replay | Old and new run formats, unchanged IDs/digests, identical trace, replay without source paths, no mutation, corrupt-source rejection |
| Operator/UI | Run/explain/evidence/Poindexter commands, invalid IDs, independent worksheet copy semantics, denial of live publication |

At each gate, run the narrow relevant tests **and** the shared regression suite. Use the existing scripts before creating redundant test frameworks:

```sh
python3 tests/check_fixtures.py
python3 tests/validate_static.py
python3 tests/check_pricing_cli.py
python3 tests/check_ingestion_cli.py
python3 tests/check_fixed_runner.py
python3 tests/check_ottomat_plan.py
python3 tests/check_sdk.py
python3 tests/check_sdk_packages.py
python3 tests/check_yieldcraft_package.py
python3 tests/check_dragnet_frozen_csv.py
python3 tests/check_poindexter_package.py
python3 tests/check_poindexter_workbench.py
./bin/build.sh
./tests/run.sh
ctest --test-dir build/native --output-on-failure
```

Some tests require the built compiler/executable, a writable **executable** temporary filesystem, Linux-specific facilities, and Python `jsonschema`. Run relevant preconditions, capture failures and do not relabel a skip as pass.

## 6. Coordinating parallel agents

Work can be delegated, but do not let agents independently invent incompatible types or mutate the same persisted protocol:

1. **Integration lead:** owns graph/SDK version registry, acceptance report and final reconciliation; reviews every cross-domain change.
2. **Storage and FFI:** owns S1 and native review work; cannot grant its own production approval.
3. **Automat:** owns P1 graph IR/planner/runtime and new node tests.
4. **Ottomat:** owns P2 grammar and lowering; depends on a frozen typed Graph IR interface.
5. **SDK / isolation:** owns P3 registry, ABI and process workers; coordinates with Automat.
6. **Contracts / data:** owns P4 schemas, semantic types, provenance and index APIs.
7. **Dragnet / ingest:** owns P5 with one lawful adapter; never gets action permissions.
8. **Models / validation:** owns P6 algorithms and point-in-time backtests.
9. **Poindexter / operations:** owns P7 after the corresponding core APIs are stable.
10. **Verification / CI:** owns S0, golden compatibility, platform tests and regression monitoring.

Freeze and publish interface proposals *before* parallel coding. Shared schema, graph and run-file changes require an integration-owned compatibility decision. Workers should not overwrite another worker's uncommitted changes, alter global pins casually, or mark an unmerged private test as integrated.

## 7. How to implement a feature (mandatory agent procedure)

1. **Identify the gate and source files.** Read the relevant actual On1x and C code, tests and contracts. Inspect upstream API headers and compiler profiles where native calls are involved.
2. **Write acceptance assertions first.** State positive/negative inputs, old golden outputs, version plan, permission conditions and resource ceilings. Add a fixture proving the intended behavior.
3. **Implement the smallest genuinely callable slice.** Prefer actual execution over impressive scaffolding. Where a required primitive cannot be safely admitted, implement only review-safe adjacent work and surface the blocker.
4. **Compile and run.** Include tests that exercise independent consumers, not only helpers from inside the same module. Never claim tested on the basis of inspecting source.
5. **Review errors and effects.** Validate money overflow, ownership/cleanup, unknown inputs, as-of timestamps, replay immutability, bounded work, and denied action permissions.
6. **Document results.** Update relevant `.md`, SDK interface docs, conformance/golden fixture documentation and `docs/IMPLEMENTATION.md`. List exact commands, hashes, host, toolchain, pass/fail/skip counts and remaining limitations.
7. **Hand off a coherent change.** One commit/PR per reviewed gate; present specific work done, files touched, tests run, known caveats and next executable task. No unsupported `DONE` status or blanket claims of production readiness.

### Required handoff format

```text
Gate/feature:
Base FinPRED SHA; MuLIB SHA; LibStone SHA; compiler/ABI:
Files changed and new public interfaces:
Contract/schema/run/version changes (or "none"):
Actual behavior (not just proposed behavior):
Commands executed; observed exit statuses; test count/results:
Golden run IDs / bytes unchanged? evidence:
Native/KernelBind review status; permissions and isolation claims:
Outstanding blockers or skipped tests:
Next exact task with acceptance criteria:
```

## 8. Definition of done

**Current Yieldcraft MVP:** local On1x C11 application that reads frozen validated contracts, computes accurate comparable whole-stay prices, issues a bounded and explainable EUR recommendation, stores immutable evidence, and replays v1/v2 without side effects. **This exists in the recorded repository and must be preserved.**

**Next platform milestone:** a **generic, versioned, typed Automat** executes a strategy authored in both native On1x and Ottomat using at least **two independently registered pure algorithms**, with content-addressed intermediate artifacts, enforced host capabilities, deterministic replay, and legacy Yieldcraft compatibility. It must not require editing the fixed original Yieldcraft runner to register a new algorithm.

**Security milestone:** the CLI uses an independently reviewed and admitted On1x/native durable storage interface; failure statuses and power-loss validation justify the stated filesystem guarantees. Until then the private-store deployment restriction remains in force.

**General FinPRED completion:** additional contract kinds and models, a real plugin execution boundary, authorized acquisition adapters, reusable graph plans, explicit forecast uncertainty, durable operational state, and independently controlled/auditable action permissions. Do not call the full platform production-ready until these are implemented and tested with real, measured evidence.

**Preferred immediate order:** (1) make clean CI reproducible; (2) finish the native storage admission path without bypassing review; **in parallel where independent**, (3) implement the general typed Automat graph IR/runner; (4) make Ottomat compile to it; (5) make the SDK invoke independently registered plugins. Keep shipping narrow vertical tests and preserving old run identities throughout.
