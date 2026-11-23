# AGENTS.md — FinPRED implementation mandate

> Repository: https://github.com/Chubek/finpred  
> Inspected branch/commit: `master` at `ec958f21864f42a6a1141aa61a96b5bb7bfee689` (2026-11-23 14:04:02 UTC).  
> Comparison checkpoint: `6d3994a2c9caeda157592b5a556b002113ff5edf`.  
> Historical release-toolchain pins used by GitHub Actions: MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`; LibStone `b5c962721a32df18b2fb22de136c1f2ef8b6390d`.  
> **CI at the inspected commit: failed** — workflow `45190236799`: application job failed at `Build C11 CLI` with exit code 2 because `bin/build.sh` looked for `build/mulib/on1x/on1xc`, while CI built `third_party/mulib/build/on1x/on1xc`. Both new Dragnet tests were therefore **skipped**. Native-store job passed. Prior commit `6d3994a` passed both jobs, **without** the new Dragnet dispatcher/feed CI gates.
>
> Purpose: instructions to **implement and verify code**, not to write aspirational documentation.

**IMPORTANT:** This file is tied to a specific inspection. At the start of every agent session, re-read the actual files and current commit. Never represent this snapshot, GitHub workflow configuration, a test file, or an earlier report as evidence that the *current* checkout passed.

## 1. Product and architecture

FinPRED is intended to be a contract-driven financial observation, analysis, forecasting, optimization, decision and eventually controlled-action system. Its present verified business slice is **local accommodation-price recommendation**, not a universal forecasting engine.

```text
CONTROL PLANE                       DATA PLANE
Trusted On1x host                   Versioned, typed observations and artifacts
  -> SDK source/algorithm registry     ^            ^
  -> Ottomat -> validated Automat DAG  |            |
  -> effect / capability policy        |            |
  -> bounded execution             Dragnet -> normalization -> contracts
  -> decision, lineage, replay         |
  -> approval gateway (FUTURE)         +-> analysis/model/strategy artifacts

External publication / booking / trading: UNIMPLEMENTED AND DENIED.
```

Core principles:

1. **On1x first.** Keep financial rules, contract semantics, planning, DSL lowering, registry policies, replay and source normalization in On1x. MuLIB C11 kernels and narrow reviewed C11 helpers may supply lower-level facilities. Python is for tooling, tests and independent oracles, not a replacement FinPRED runtime.
2. **Host-owned effects.** A plugin descriptor, Ottomat declaration or source URL is never an authority grant. Trusted host grants are explicit, scoped, checked before execution and again at call boundaries. No action or publication grant exists in the current CLI.
3. **Clear provenance.** Record versioned kind, units, economic/valid time, source observation, receipt and ingestion times, immutable bytes and parents. A BLAKE3 digest proves content consistency relative to trusted identities; it does **not** prove authorship or an external provider's authenticity.
4. **Local and replayable.** Frozen evidence must reconstruct each decision without reopening live data sources, modifying an original archive or changing its historical interpretation.
5. **Separate control/data planes.** Dragnet acquisition processes may use explicitly authorized read-only transport. Pure On1x normalization/analysis handlers must not inherit network, file write or action permissions.
6. **Minimalism and honesty.** Prefer one working, independently tested vertical feature over ten stub APIs. Call incomplete gates *blocked*; do not silently add fallback unsafe FFI.

### Source precedence

- **Product intent:** `docs/USER_SPECIFICATION.md` (design, not an executable proof).
- **Actual system behavior:** current `source/`, `plugins/`, `contracts/`, `native/`, `strategies/`, `On1xfile*`, executable scripts and tests.
- **Historical formats:** `docs/RUN_FORMAT.md`, `fixtures/replay_v1.json`, golden test artifacts. These are compatibility contracts.
- **Risk decisions:** `native/STORE_ADMISSION.md`, `source/store/README.md`, `plugins/dragnet/PUBLIC_FEEDS.md`, `plugins/dragnet/SOURCE_DISPATCH.md`.
- **Recorded execution history:** `docs/IMPLEMENTATION.md`, `tests/COVERAGE.md`, CI logs. Verify against actual executions; many notes refer to earlier compiler revisions or earlier commit SHAs.
- **Upstream:** the exact checked-out MuLIB and nested LibStone revisions, not imagined APIs or the current upstream `master`.

When sources conflict, record the contradiction and its risk. Do not rewrite a persisted format to make disparate documents agree.

## 2. Current implementation inventory (checkpoint `ec958f21`)

| Path / subsystem | Implemented or materially present | Still missing / qualification |
| --- | --- | --- |
| `source/core/` and four `contracts/*.schema.json` | Bounded CSV parsing, civil dates/as-of checking, integer EUR cents, deterministic contract envelopes | General typed schema registry, currencies/units, semantic migrations and unknown/stale states |
| `plugins/yieldcraft/`, `source/algorithms/quantile.on1x` | Exact room-bundle feasibility, property deduplication, Type-7 quantile, five named strategies and guardrails | General model/predictor, independent domain abstraction |
| `source/automat/{graph,runner}.on1x` | Seven-node fixed recommendation plan with host-supplied Yieldcraft policy and validation | General financial contract DAG, extensible execution lifecycle |
| `source/automat/{dag,dag_artifacts,dag_replay,scalar_*}.on1x` | Typed bounded scalar DAG, versioned operators, content-addressed intermediate artifacts, run-local memoization and scalar replay | Execute actual hospitality/FX contracts, effects and durable general runs |
| `source/ottomat/` | GrammarEmbed-powered legacy declarations and `ottomat` v3/v4/v5 scalar graph dialects | General financial typed graph language and common executable lowering |
| `source/sdk/` | On1x/C metadata interfaces, static trusted engine/handler registry | Unified invocable generic SDK, dynamic packages and isolation for untrusted code |
| `plugins/dragnet/source/dragnet/source_registry.on1x` | **New:** static pure dispatcher for frozen CSV, Crossref, public-feed normalization | Independent general SDK Source registration, non-Dragnet consumers, dynamic loading and trusted invocation lifecycle |
| `plugins/dragnet/source/dispatch_host.on1x`, `build-dispatch.sh` | **New:** standalone offline On1x dispatcher with inherited bounded descriptor bytes | Proof of successful compiled execution at latest SHA; host-controlled error/capability object; process isolation |
| `tests/check_dragnet_dispatch.py`, `tests/check_dragnet_public_feeds.py` | **New CI targets** for dispatcher parity and ECB/Eurostat loopback acquisition, integrity, cancellation and replay | Latest CI application job must **finish successfully**; live-provider compatibility remains separate and opt-in |
| `plugins/dragnet/feeds`, `feed_{fetch,decode}.c`, public feeds | Fixed read-only ECB reference-rate and Eurostat guest-night snapshots; pure On1x normalization; separate foreground capture host | Real-provider end-to-end verification, provider compatibility maintenance, generic Source lifecycle and durable scheduling |
| `plugins/dragnet/crossref*`, frozen CSV | Offline bibliographic evidence and eligible hospitality offers | Source package versioning in common SDK; Crossref metadata is not room-price evidence |
| `plugins/poindexter/` | Verified-run CSV projection, terminal worksheet, optional ImmGTK X11 editor, separate workbook storage | General multi-domain worksheet, robust large-workbook operations; no need to rewrite UI now |
| `source/store/` | BLAKE3 private cooperating-writer artifact publication, v1 archive replay/v2 writer | Adversarial filesystem confinement, power-loss durability and approved native KernelBind import |
| `native/store.{c,h}` | Independently tested Linux C11 durable-publication **candidate** | No independently admitted On1x FFI; no production storage claim or proven power-cut/remount semantics |
| `.github/workflows/verify.yml` | Pinned application/native jobs; new Dragnet packages/feeds/dispatch CI steps | Current head **failed** at CLI build due to compiler path; Dragnet checks skipped |
| `bin/build.sh`, `bin/build-env.sh`, `Makefile`, `INSTALL.md` | Attempted move of build outputs to `build/`; compiler path documented as `build/mulib/on1x/on1xc` | **Known contradictory paths and missing target; P0 gate below** |

The new Dragnet dispatcher is not a generic plugin host. `source_registry.on1x` enumerates three names in source code; `SOURCE_DISPATCH.md` explicitly states it is offline, static, and not registered in the general SDK package registry.

### Historical and business invariants (NEVER REGRESS)

- Default synthetic stay: `recommendation_minor=17100` (EUR 171/night), reason `lower_percentile_shortcut`, five eligible independent comparable properties, two rejected offers, `published=false`.
- Multi-room synthetic stay: `recommendation_minor=16000` (EUR 160/night), reason `guardrail_adjustment`, `published=false`.
- Five named strategy profiles: `value-p40`, `balanced-p55`, `premium-p75`, `lead-linear`, `lead-quadratic`; retain checked golden prices and lineage.
- Historical `finpred-run@1` archives remain **read-only** and byte-preserving. New pricing writes are `finpred-run@2` only; preserve exact run IDs, artifact digests, recommendation/trace bytes, and replay semantics.
- Distinguish `scalar-run@1`, `scalar-run@2`, `scalar-run@3` from `finpred-run@1/@2`; these are **not** interchangeable persisted formats.
- Distinguish Ottomat syntax version, Automat Graph IR version, SDK ABI version, plugin package version, artifact schema version, and run format version.
- Source spelling is **Ottomat** / `ottomat` (not `ottmat`) for new names and sources. Legacy `ottmat 1/2` strategy headers may remain accepted **only** to preserve archived source-byte identities. Migrate/newly emit the canonical `ottomat` spelling without rewriting old evidence.
- `replay`, `explain`, `evidence`, and Poindexter projections do not mutate run stores; source paths can be unavailable during replay. Failed validation may not partially publish a recommendation.
- ECB rates are **non-executable indicative reference quotes**; Eurostat nights are aggregates. Both use `pricing_input=false` and are not hotel offers, tradable quotes, or automatic currency conversions.

## 3. Required agent bootstrap

Before coding:

```sh
git status --short
git log -7 --oneline
git rev-parse HEAD
git submodule status third_party/mulib
git -C third_party/mulib submodule status on1x/third_party/libstone
sed -n '1,150p' .github/workflows/verify.yml
sed -n '1,130p' Makefile
sed -n '1,130p' INSTALL.md
```

If MuLIB/LibStone are not provisioned, follow their checked-in submodule records as described in `INSTALL.md`. The historical independent CI pins are only for reproducing historical evidence. Neither On1x's compiler nor a reviewed kernel profile should be guessed into existence.

For a current checkout, use the shared local and CI layout:

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
make mulib
make
./bin/finpred selftest
make test
```

Explicit toolchain overrides must use a matching source checkout, compiler and PPX installation. **These commands are a test recipe, not proof of execution on the current checkout.** Record toolchain SHAs, compiler binary SHA-256, host architecture and exact result.

Use a private, executable temporary filesystem with adequate disk space, plus `jsonschema` Draft 2020-12, `pkg-config`, libcurl >= 7.85, libxml2 and Jansson headers for Dragnet native conformance. Test CI offline with loopback transport only.

## 4. Gate P0 — Repair and certify the build (START HERE)

**Owner:** release/CI integration agent. **Paths:** `Makefile`, `bin/build*.sh`, `bin/finpred`, `bin/poindexter`, `INSTALL.md`, `.github/workflows/verify.yml`, affected `tests/` paths.

The inspected commit **failed CI** due to the first mismatch below (`Build C11 CLI`, exit 2, workflow `45190236799`). The other two were separate source-verified contradictions. Recheck the current checkout before taking on platform features:

1. **Compiler path conflict.** CI configures the compiler inside `$MULIB_ROOT/build/on1x`; `bin/build.sh` now defaults to `$ROOT/build/mulib/on1x/on1xc`. No CI export of `ON1XC` is present. **GitHub Actions log confirms the exact missing-compiler error.** Choose ONE canonical build directory, or explicitly export `ON1XC` and `FINPRED_STDPPX_DIR` consistent with the chosen build in every test path. Ensure GrammarEmbed and compiler binary come from the same source revision.
2. **Missing `make mulib`.** `INSTALL.md`, `AGENTS.md` and `bin/build.sh` instruct users to run `make mulib`, but the current `Makefile` contains no `mulib:` rule. Either implement the real CMake target with explicit out-of-tree build/pins or update all documentation and error messages to the actual command. No false build target in release instructions.
3. **Incorrect `make test` executable.** The default CLI output is now `build/dev/finpred`, but `make test` explicitly sets `FINPRED_EXE` from `${FINPRED_BUILD_DIR:-target/dev}`. Update it to the same default as `bin/build.sh` and `bin/finpred`; test an isolated clean checkout, not a stale `target/dev` executable. Prefer a single shared build-path resolution instead of duplicating defaults.

Additionally:

- Document whether the checked-in MuLIB Git submodule SHA or the earlier independent CI `MULIB_SHA`/`LIBSTONE_SHA` pair is authoritative. Test the selected pair; maintain a compatibility matrix only for combinations actually run.
- Keep outputs, temporary projects, generated PPX artifacts, compiler builds and caches within an explicitly configured build root where possible, without modifying source trees. Verify clean builds with `TMPDIR` set and unset.
- Remove contradictory stale paths from scripts, test fixtures, `INSTALL.md`, `docs/IMPLEMENTATION.md`, `SOURCE_DISPATCH.md` and documentation. Update only verified commands.
- `AGENTS.md` appears in `.gitignore` despite being tracked. Check that source-control behavior is intentional; remove the misleading ignore rule if appropriate, without deleting the tracked file.
- `README_PATCH.md` and `VALIDATION.md` were committed as patch-bundle metadata. Move their useful details into canonical implementation/release documentation or explicitly mark them archival; they should not be authoritative current instructions.

**P0 acceptance:** clean source checkout, correct submodules/compiler/PPX, `make` and `make test` build and run the **same intended executable**; `make dragnet-test` passes; GitHub application and native-store jobs pass on the latest head. Reject stale executable paths, mismatched toolchain pins, or missing target names automatically. CI success on a previous commit is not P0 acceptance.

## 5. Gate P0b — Prove the new Dragnet patch actually works

**Owners:** Dragnet + CI verification. **Paths:** `plugins/dragnet/`, `tests/check_dragnet_{public_feeds,dispatch}.py`, `.github/workflows/verify.yml`, `tests/COVERAGE.md`.

The new dispatch source files exist, but **the current-head CI never reached their compiled conformance steps**: the earlier CLI build failed. Fix P0 first, rerun the new CI gates to completion; if they fail, analyze logs and make the smallest correction. Preserve the previous adapters' exact bytes and negative cases.

Mandatory checks:

- `python3 tests/check_dragnet_frozen_csv.py`
- `python3 tests/check_dragnet_elvi.py`
- `python3 tests/check_crossref_replay.py`
- `python3 tests/check_dragnet_public_feeds.py`
- `python3 tests/check_dragnet_dispatch.py`
- `make dragnet-test`

Inspect actual `source_registry.on1x` and `dispatch_host.on1x`. Validate selector syntax/version rejection, input descriptors and size caps, correct adapter dispatch, independence from `FINPRED_HOME`, and exact parity with prior direct hosts. Ensure failed normalizations cannot emit half-valid observations. Test bad decoder/raw pairs, unauthorized effect modes, duplicate inputs, invalid-as-of data, unavailable handlers, deadline/cancellation, corrupted archives, `429/503` backoff and no network calls during offline replay. Include original-provider byte snapshots and independent schema validation.

The dispatcher currently has **five generic string arguments**; this is a useful first trusted adapter but not a sound long-term typed plugin ABI. Define typed source request/result/error records and exact per-provider argument profiles without changing existing output bytes. The source selector must stay host-owned and deny unknown identities by default. Avoid granting raw OS paths or action privileges to a strategy.

**Acceptance:** current-head CI application job actually executes and passes both new compiled test steps; all three sources are compared byte-for-byte with existing hosts; no pricing state or network is touched by the offline dispatcher. Real public-provider polling is a **separate, explicitly opt-in** compatibility gate and cannot make offline CI flaky.

## 6. Gate A1 — Converge the two Automats into a general typed financial DAG

**Owner:** Automat lead. **Paths:** `source/automat/`, `source/cli/`, `plugins/yieldcraft/`, `source/sdk/registry.on1x`, new independent consumers/tests.

**Now:** `automat.runner.run` checks a fixed seven-node pricing plan and accepts a trusted host-supplied Yieldcraft function. `automat.dag` runs bounded scalar operators (minimum, maximum, distance, select, midpoint), with versions, deterministic ordering, memoization and scalar-run replay. These are two distinct executors.

Implement a common, versioned **Graph IR** with:

- Named typed input/output ports and explicit edge types (contract kind, major version, units, currency, presence semantics).
- Stable graph/node identities and handler owner/version/policy identity; declared effect classification: `pure`, `read`, `record`, `action` (the last remains denied).
- Deterministic bounded topological ordering, cycle rejection, resource limits, no hidden global evaluation state.
- Host-controlled static handler resolution first. At least two **independently registered** pure algorithms must execute on a genuine nontrivial financial contract graph.
- Pure replayable immutable intermediate artifacts, full parent lineage, input/handler/strategy digests, typed errors, as-of constraints.
- Correct memo keys including exact inputs, versioned handler identity and policy/code identity; memoization must be in-run and never alter artifact ordering or meaning.
- Planning and invocation-time capability enforcement; no external action inference from Ottomat.

**Migration rule:** do not replace the old fixed runner for historical `finpred-run@1/@2`. Introduce adapters that allow a new general graph to *compute equivalent Yieldcraft decisions* on frozen fixtures while preserving an independent legacy replay implementation. Do not create a `finpred-run@3` until its payload/compatibility rules are stable and independently tested.

**Acceptance:** one graph combines normalized offers, comparable distribution, an independently registered diagnostic/algorithm, Yieldcraft decision and guardrails. Both native On1x builder and Ottomat compile to the same typed IR; cross-engine semantic outputs and corresponding trace events agree. Existing archived run IDs/bytes remain identical. Test cycles, wrong port kind/version/units, denied effect, missing handler, budget overflow, duplicate IDs and wrong replay parents.

## 7. Gate A2 — Ottomat: one typed lowering, no second runtime

**Owner:** language/frontend agent. **Paths:** `source/ottomat/`, `strategies/`, versioned Graph IR, tests.

- Preserve legacy source-byte replay. Keep accepted old headers where necessary but standardize **new** source to `ottomat`.
- Extend the existing GrammarEmbed frontend with typed financial input/output declarations, registered imports, bounded let bindings and `emit`; support explicit declared effects and source spans.
- Lower exclusively to the *same* validated Graph IR used by native On1x; no secret Ottomat-only execution shortcuts.
- Resolve names/versions/contracts/units at compile/plan time; reject unknown algorithms and effect escalation before work begins.
- Record source bytes/hash, compiler + lowering identity, resolved plugin identities, and Graph IR digest. Distinguish source identity from semantically equivalent graph/run identity.
- Avoid arbitrary recursion/unbounded loops; repeated model computations should be bounded handler operations.

**Acceptance:** a general hospitality strategy written in Ottomat yields the same semantic result and compatible trace as a native On1x graph. Negative grammar/type/effect tests compile and execute using the pinned compiler/GrammarEmbed, with exact diagnostics where practical. Original `ottomat` 1/2 and scalar dialect tests remain passing.

## 8. Gate SDK1 — Make plugin invocation real, typed and controllable

**Owner:** SDK/security agent. **Paths:** `source/sdk/`, `plugins/*/`, `PLUGIN.md`, `plugins/dragnet/source/dragnet/source_registry.on1x`, ABI tests.

First reconcile **two** existing registries: `sdk.registry` controls linked engine policies; `dragnet.source_registry` independently hard-codes source IDs. Do not create a third incompatible registry.

Provide a versioned, host-authoritative interface for registered `Source`, `Transformer`, `Algorithm`, `Model`, `Strategy`, `View`, and future `Action` handler types. Use actual callable registered handlers, not only descriptors.

- Explicit immutable package and handler identity (`name@version`, code digest, ABI/schema, owner, dependencies).
- Exact input and output kinds, port names/arity, units, effects, budget, source as-of and capability requirements.
- Register **trusted static On1x implementations first**, including Dragnet Source and scalar midpoint, without editing core dispatch for every additional *trusted* handler.
- Deny malformed/unavailable packages, conflicting versions, weakly typed argument bags and permission escalation.
- Add typed outcome/error records for failure/partial/missing data; enforce measured resource ceilings, timeouts and cancellation at the host boundary.
- Any untrusted native code must execute in a separately reviewed process/OS isolation boundary. A descriptor, C function pointer, shell wrapper or KernelBind annotation is **not** isolation.
- Preserve the current C ABI v1/v2 and static consumers. If interface semantics change, publish a new ABI and conformance fixtures.

**Acceptance:** at least two separate packages are registered, called through the same SDK/Automat runtime, and provenance captures exact handler identities. Disabling a package causes a clear failure before its code executes. Neither Dragnet nor Ottomat grants external network or action authority.

## 9. Gate DATA1 — General contract registry, as-of semantics, and durable lineage

**Owner:** contracts/data-plane agent. **Paths:** `source/core/`, `contracts/`, registry code, `source/store/`, source adapter contracts.

- Add registered kind/version schemas, versioned transforms, explicit input/output artifacts and semantic validators; distinguish schema compatibility from binary equality.
- Model source/economic period, observed, received, ingested, valid, forecast target and decision cutoffs distinctly. Historical as-of replay must not read later-ingested observations even if their economic period is old.
- Introduce explicit units/currency/quantity semantics and available/partial/stale/unknown/redacted states. EUR minor-unit pricing stays integer and exact.
- Onboard validated ECB FX and Eurostat aggregate observations as **analysis-only** contract kinds. No implicit FX conversion; an FX transformation requires dated reference-rate units, explicit target and clear semantics. Never feed aggregate guest-night counts to hotel-room comparable selection.
- Define a query/index path over verified immutable artifacts, source and parent IDs that can be reconstructed without becoming the authority over original bytes.
- Document schema migrations and incompatible version boundaries. New data plane must allow another financial domain without importing `plugins/yieldcraft` into universal core modules.

**Acceptance:** a new source observation and registered transformation produce a typed artifact with stable provenance; invalid version, as-of lookahead, cross-unit misuse, missing source and parent tampering fail deterministically; old four `@1` schemas and old pricing records retain exact meaning.

## 10. Gate STORE1 — Independently reviewed native storage admission

**Owner:** native storage + upstream FFI reviewer. **Paths:** `native/`, `native/STORE_ADMISSION.md`, `source/store/`, MuLIB/On1x KernelBind sources; new direct compiled consumers.

The standalone C11 native store is a **candidate**, not an admitted On1x capability. Do not bind it using an unreviewed Exotract/ExoML declaration, manually signed test profile, or fallback raw libc calls and then advertise production safety.

Required:

1. Explicit sealed/owned read-only and read-write handles with caller lifetime, close/error semantics and no arbitrary caller-controlled path traversal.
2. Independently reviewed, approved KernelBind profile with compiled On1x caller and correct C ABI lowering for handles, buffers, errors and cancellation.
3. Directory-relative constrained access, no-follow/no-replace, safe ownership checks, bounded IO and clear conflict/uncertain-durability results.
4. Publish referenced objects **before** manifests and use file and directory sync according to a documented filesystem crash model; replay reads never modify or repair stores.
5. Adversarial tests for competing publishers, symlink/rename races, special files, short writes, `ENOSPC`, `EINTR`, partial sync, power cut/remount and unchanged historical artifact bytes.

**Acceptance:** only after independent admission, compiled On1x invocation and power-loss tests may the CLI claim the corresponding guarantees. If external review is unavailable, keep native storage disconnected and work on independent gates; status remains **BLOCKED**.

## 11. Gate DRAG1 — Complete reproducible acquisition, not speculative scraping

**Owner:** Dragnet transport and adapters. **Paths:** `plugins/dragnet/`, source contracts, `tests/check_dragnet_*`.

- Keep frozen hospitality CSV, offline Crossref and ECB/Eurostat providers. Live ECB/Eurostat compatibility checks are opt-in; CI must remain deterministic and offline.
- Refactor the static dispatcher into a reusable typed registered Source interface **after** SDK1's identity/capability contract is frozen. Avoid two independently evolving source registries.
- Reuse a common conceptual pipeline: `transport -> capture -> decode -> validate -> normalize -> evidence -> offline replay`, without collapsing provider-specific formats or data licensing policies.
- Capture provenance, provider terms/retention IDs, actual capture metadata, source identity, time-of-knowledge and raw snapshots where permitted. Policy IDs do not prove authorization; hashes do not authenticate a provider.
- Harden HTTP/parse limits, XML external entities, duplicate JSON dimensions, redirects, timeouts, truncated bodies, backoff, lock/checkpoints and restart/cancellation. Add regression tests *before* fixing any discovered defect.
- Make sure failures never produce misleading partial success. A valid Eurostat missing observation is `partial`; a truncated/invalid HTTP transfer is `failed`.
- Explicitly separate the existing native libcurl/libxml2/Jansson helper dependencies from MuLIB's no-external-dependency kernel policy. Do not introduce silent dependencies into the core On1x runtime.
- Defer general web scraping, booking inventory and price-sourcing until an explicitly licensed/authorized provider contract, identity and rate policy exist.

**Acceptance:** a newly added trusted Source handler can run through the common SDK without editing Automat; offline source evidence verifies exactly from frozen bytes, no network on replay, and as-of correctness is enforced. The product never misclassifies a reference rate or aggregate statistic as live market price.

## 12. Gate MODEL1 — Actual forecasting, testing and uncertainty

**Owner:** models/algorithms agent. **Paths:** new typed forecast contracts, model registry, On1x algorithm implementations, evaluation tests.

Yieldcraft's current percentile recommendation is **not** a trained demand forecast. Implement at least two reproducible baselines, e.g., moving average and seasonal naive, with:

- Clearly typed forecast target, horizon, training cutoff, issuance time, source and model/code identity.
- Missing-data/insufficient-evidence state; uncertainty intervals or explicit unavailable status. No guarantee of economic profitability.
- Walk-forward evaluation with no lookahead or late-ingested observations, training/validation/holdout distinction and MAE/RMSE where well-defined.
- Full offline replay and independent baseline comparisons; documented unit/currency correctness.
- At least one additional financial analysis domain (e.g. FX **research**, not execution) using the *same* contracts and Automat/SDK rather than a new specialized engine.

**Acceptance:** two registered models execute in one general graph and can be independently backtested from frozen point-in-time inputs with reproducible artifacts, typed uncertainty and no unapproved external side effect.

## 13. Gate OPS1 — Operability and Poindexter

**Owner:** operations/UI agent. No broad rewrite before the platform APIs stabilize.

- Extend CLI `run`, `replay`, `explain`, `evidence` and inspection commands to versioned generic analysis only after Graph IR and contracts are stable. Legacy CLI remains default where needed for compatibility.
- Add explicit job lifecycle (`planned`, `validated`, `running`, `completed`, `failed`, `cancelled`, `blocked`), bounded retry semantics, real cancellation and idempotency; persist only with approved storage guarantees.
- Keep Poindexter as a **view** of verified runs/analysis artifacts. Formulas/worksheet scripts cannot mutate upstream pricing evidence or grant trading/booking permissions.
- Future `Action` requires separate human/operator approval, audited intent, idempotency keys and isolated authorization. **Do not enable in this milestone.**

**Acceptance:** a general read-only analysis is observable/explainable, failures are typed and reproducible, cancellation does not leave a false completed state, and all current worksheet/GUI tests remain passing.

## 14. Verification matrix and executable gates

Use existing compiled tests; avoid a second redundant Python-only framework. After P0, the expected command set is:

```sh
# Build and full regressions, once coherent paths/toolchain are fixed
make
make test
make dragnet-test
make native-test

# Selected focused tests
python3 tests/check_engines_cli.py
python3 tests/check_fixed_runner.py
python3 tests/check_dag.py
python3 tests/check_dag_replay.py
python3 tests/check_scalar_manifest.py
python3 tests/check_scalar_memo.py
python3 tests/check_scalar_registry.py
python3 tests/check_ottomat_scalar.py
python3 tests/check_scalar_selection.py
python3 tests/check_plugin_registry.py
python3 tests/check_sdk_packages.py
python3 tests/check_pricing_cli.py
python3 tests/check_ingestion_cli.py
python3 tests/check_store.py
python3 tests/check_store_publication_status.py
python3 tests/check_yieldcraft_formats.py
python3 tests/check_dragnet_public_feeds.py
python3 tests/check_dragnet_dispatch.py
python3 tests/check_poindexter_workbench.py
```

Note: some focused tests require a compiled executable and environment variables; use each script's README and known runner setup. A test's *existence* is not evidence of a pass. Failures must be recorded and not filtered away.

| Requirement | Positive test | Required rejection/failure test |
| --- | --- | --- |
| Build paths and pins | Fresh project/out-of-tree compiler, correct binary executed | Missing compiler, mismatched SHA/PPX, stale `target/dev` binary |
| Yieldcraft | EUR 171 and 160 fixtures, 5 policies, v1/v2 replay | Invalid CSV, duplicate inventory, impossible occupancy, guardrail conflicts |
| Automat | Same typed financial graph through two frontends | Cycles, wrong ports/units, unknown handlers, budget limit, denied effects |
| Ottomat | GrammarEmbed compile and source-to-IR parity | Invalid tokens/versions, type/effect escalation, unknown imports |
| SDK | Two registered executable pure handlers | Forged descriptor, disabled package, wrong ABI, untrusted caller action request |
| Dragnet | Offline source parity, loopback ECB/Eurostat, replay | Redirect, 429/503, XXE, invalid JSON, stale/late, source-byte tampering, interrupted worker |
| Contracts | Verified versioned inputs + explicit transform | Wrong time/currency/unit/version/parent, late-as-of observation |
| Storage | Reconstructed unmodified old archives, concurrent publication | Symlinks, partial writes/sync, interrupted manifest, power-cut/remount before durability claims |
| Forecasting | Chronological baseline walk-forward | Data leakage, insufficient evidence, wrong horizon, future ingestion |
| Operator/UI | Replay/explain/evidence/Poindexter projection | Missing run, corrupted artifact, denied publication, read-only store mutation |

On every gate, measure and report **exact** fixture IDs/digests. Never delete or regenerate archived fixtures to turn a regression red-to-green. If an improvement requires a new serialization, add a new explicit format version with fixtures; keep historical readers.

## 15. Parallel-agent protocol

Up to 12 workstreams can run concurrently **after** interfaces are agreed:

1. **Integrator/release lead:** current branch, ABI/Graph IR version decisions, CI merges, final acceptance.
2. **Build/CI:** P0, toolchain pins, local paths, hosted reproducibility.
3. **Dragnet tests:** P0b, compiled fixture parity, evidence and network-negative tests.
4. **Automat IR:** A1 core plan/ordering/effects/artifacts.
5. **Automat financial adapters:** A1 Yieldcraft coexistence and semantic parity.
6. **Ottomat:** A2 grammar/type/effects/lowering, waiting for Graph IR freeze.
7. **SDK:** SDK1 registered invocations, ABI, default-deny policies.
8. **Contracts:** DATA1 source kinds/units/as-of/migrations.
9. **Native storage:** STORE1 safe C11 implementation and test harness; no self-admission.
10. **KernelBind/FFI review:** independently reviews native profile; cannot approve its own test key.
11. **Forecasting:** MODEL1 baselines/evaluation, after contract signatures are stable.
12. **UI/operations & verification:** OPS1 presentation, integration regression, risk reporting.

No two agents may concurrently modify `source/sdk/registry.on1x`, central Graph IR, artifact format decoders or `.github/workflows/verify.yml` without an owner/merge protocol. Freeze interface records first, review changes through integration-owned tests, and retain independent client consumers. Never overwrite unrelated worktree changes.

### Mandatory per-change procedure

1. Capture head and toolchain SHAs, read affected source and tests, and reproduce the baseline failure/success.
2. State a narrow gate, exact files, expected interfaces, positive/negative tests and compatibility risk.
3. Add a regression test demonstrating a real defect or an executable acceptance case for a new feature.
4. Implement real code using current On1x constructs and approved native boundaries. Avoid unsupported syntax and invented MuLIB imports.
5. Compile, run targeted and shared tests, and compare golden run IDs/bytes. Capture exact command, exit status, test count, SHA and platform.
6. Reconcile documentation, manifest entries, SDK declarations and coverage. Report discrepancies, skipped checks and independent review blockers.
7. Commit/PR one coherent gate and provide handoff evidence. Do **not** label code production-ready unless the promised security and deployment properties have been measured.

### Required handoff (copy exactly, fill every field)

```text
Gate / outcome:
FinPRED SHA before and after:
MuLIB SHA, LibStone SHA, on1xc hash, host:
Changed source files and interfaces:
Contracts / ABI / Graph IR / run format changes:
Tests executed with exact exit code and evidence:
Golden v1/v2 identities and EUR 171/160 results unchanged?:
External effects / capability / KernelBind review status:
Skipped or blocked checks (explicit):
Remaining defects and next precise task:
```

## 16. Definition of done

- **P0** = repair the confirmed `ec958f21` CI build-path failure, then clean, reproducible, same-path build, correct pinned toolchain and latest CI green including Dragnet feed and dispatcher.
- **Next platform milestone** = one **general typed Automat** can execute a financial contract DAG through both native On1x and Ottomat, with multiple independently registered pure algorithms, host-checked capabilities, content-addressed evidence and deterministic replay, while preserving legacy pricing archives.
- **Storage milestone** = independently admitted native file/handle profile, compiled On1x invocation, crash-model tests and safe publication/replay; otherwise blocked.
- **FinPRED platform completion** = generic contract registry, safe invocable plugin host, authorized reproducible sources, real forecast/uncertainty and walk-forward evaluation, durable operational state and explicitly audited action authorization. The present repository is not at this stage.

**Immediate execution order:** fix the confirmed P0 CI compiler-path failure (and remaining Makefile contradictions); establish P0b current-head Dragnet conformance; then A1 common financial Graph IR and SDK1 trusted invocable handler integration in coordinated slices; A2 Ottomat lowering; DATA1 contracts; STORE1 native admission independently; MODEL1 real forecasting. Do not add another disconnected runtime or rename historical data to mask compatibility work.
