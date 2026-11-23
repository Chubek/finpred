# FinPRED v1 implementation notes and review checklist

## Provenance

- User-supplied design: `docs/USER_SPECIFICATION.md`.
- Inspected public MuLIB repository `Chubek/mulib`, `master` at
  `49de89acbc97efbee493d6b28d02c8f64ed4f725` (23 November 2026).
- Reviewed paths through GitHub connector: `on1x/README.md`,
  `on1x/KERNEL_DIRECT_USAGE.md`, On1x sample programs, On1xfile guide,
  `on1x/stdlib/{io,os,crypto,collections,text}`.
- On1x compile/link status: **built and executed** with the pinned compiler
  and the On1xfile C11 driver; see the [acceptance record](#acceptance-record).
  This build does not establish independent signed ABI review.

## Architecture and isolation

### S0 verification workflow

The [Ubuntu 24.04 workflow](../.github/workflows/verify.yml) has separate
application and native-store jobs. The [coverage index](../tests/COVERAGE.md)
names the compiled positive and negative cases for each release feature.
The application job emits fixture identities and output digests via `tests/run.sh`;
both jobs log JSON test outcomes, including skipped steps.

Local rehearsal used a fresh copy of the working sources based on `24c6f3d`
and clean dependency checkouts from local Git objects: MuLIB
`49de89acbc97efbee493d6b28d02c8f64ed4f725`, LibStone
`b5c962721a32df18b2fb22de136c1f2ef8b6390d`. On x86-64 Linux
`6.18.52-1-lts` with GCC `16.2.1`, the rebuilt `on1xc` SHA-256 was
`88428528934039ca7d0eb4064ec10e156235984aeafc3138b43ee19ee18cff20`.
`./bin/build.sh && ./tests/run.sh` exited 0, including the two historical v2
IDs, both archived v1 replays, five policies, 32 pricing cases and 65 ingestion
cases. The three package consumers and Poindexter workbench passed, and strict
C11 native-store CTest passed 2/2. Hosted runner provisioning and execution
remain to be verified on GitHub.

### Data and control flow

Alongside the legacy CLI plan, the [native scalar DAG](../source/automat/README.md)
executes bounded analysis graphs with two level algorithms and a distance
transform. This first P1 slice adds an in-memory plan version; it changes no
contract schema, persisted artifact, run version or storage permission.
Verification from base `db9cd08` used the S0 pinned compiler recorded above:
`./bin/build.sh && ./tests/run.sh` exited 0. The independent DAG consumer
verified four successful executions and fourteen rejected calls; the historical
v2 IDs, recommendation/trace digests and both archived v1 replays passed.

The next P1 slice adds BLAKE3-addressed input and intermediate output bytes
to the native outcome. Node bytes name the versioned handler and bind the
left and right parent digests in port order. The caller can independently
re-execute the graph and verify the complete returned list and selected
output via `automat.dag_replay.verify`.
The integrated pinned build and `tests/run.sh` exited 0: five successful
graph executions (including an 18-artifact maximum-depth chain), fourteen
graph rejections, three byte-exact golden runs, three replay verifications
and fourteen evidence rejection cases. The two historical v2 fixture
identities and both archived v1 read-only replays also passed.

For a fresh process, `automat.scalar_manifest.freeze` emits the versioned
[`scalar-run@1` manifest](RUN_FORMAT.md#scalar-run1-native-analysis).
`automat.scalar_verify.verify` needs only its expected run ID, manifest and
ordered artifacts. There is no host filesystem access in these modules;
storing the bundle is a caller decision. The CLI continues to use only the
existing recommendation formats.

With the pinned compiler above, `./bin/build.sh` and `./tests/run.sh`
exited 0. The frozen-run consumer verified 18 snapshots in fresh processes,
rejected 25 invalid bundles and checked four failed freezes for partial
outputs. Its independent 626-byte manifest fixture has BLAKE3 identity
`e7fcc371e632492f6a007942aa0546fe74c5cf0072bf80ae27a85b5e24fd89b0`.

The native scalar evaluator now also offers [run-local memoization](../source/automat/README.md#reusing-pure-results-within-a-run).
The host opts in with `run_memoized` or `freeze_memoized`. Duplicate work
can avoid handler calls while retaining one artifact and trace row per
declaration. The table is never loaded from a manifest or shared with a
later run, so results cannot survive a change of linked implementation.
The `scalar-run@1` verifier still uses uncached execution.
`./bin/build.sh` and `./tests/run.sh` passed on the same pinned C11
toolchain. In the compiled conformance test 16 identical sibling operations
needed one invocation and produced 15 hits. Three successful cases and two
rejections passed, and the separate frozen-run consumer verified 19
snapshots, including a memoized one in a fresh process.

### On1x source modernization

The scalar analysis modules use On1x interpolation for canonical text and a
typed `Option<i64>` with an exhaustive enum match for memo lookup. The
manifest decoder uses character literals for byte-level ASCII comparisons. These
changes require no new compiler flags or KernelBind capabilities. The
release pins remain unchanged. The newer compatibility toolchain uses MuLIB
`87cbf7c361667c62f82759bd0c02834b2b07315c` with its matching LibStone
`4c35077601899944594737559534aafd9014f330`, not a mix of the two toolchain
revisions.

`make test` passed on both toolchains from base `db9cd08`. The newer
compiler SHA-256 is `faed6639728d5a39e1fa7ac86f1322f45f78853526a21fcff95f03990e2ab041`.
The feature fixture executed once and checked two compiler rejections.
The memo consumer also verified a cached zero. Scalar golden bytes and
historical Yieldcraft v1/v2 replay remained unchanged.

Use `make test` to build the CLI and run the integration suite with the
selected `MULIB_ROOT` and `ON1XC`. The Makefile also wraps the Poindexter
build and the standalone native CTests; it does not download a toolchain
or grant storage admission. `make native-test` passed both CTests, and
`make poindexter` built the terminal executable.

### Ottomat v3 scalar lowering

The [scalar dialect](../source/ottomat/README.md#v3-scalar-analysis) parses
typed input declarations, explicit registered imports, node bindings and a
selected output. It lowers to the existing `automat.scalar-dag@1` plan and
asks the native planner to validate it without running a handler. The native
freeze wrapper supplies a digest of the exact Ottomat source and a lowering
identity alongside the unchanged `scalar-run@1` snapshot. These are separate
identities: source changes can leave the lowered graph and run ID identical.
The legacy CLI still rejects v3 as a recommendation strategy.

On the release pins above (base FinPRED `db9cd08`), `make test` exited 0:
five v3 successes matched the native result, trace and evidence; 41 v3
cases were rejected. The native and DSL snapshots share the pinned scalar
run ID `e7fcc371e632492f6a007942aa0546fe74c5cf0072bf80ae27a85b5e24fd89b0`.
Both archived v1 replays and the historical v2 run IDs and output digests
passed unchanged. The three plugin package checks, Poindexter workbench
test and both standalone CTests also passed. The focused v3 consumer
passed on the newer compatibility toolchain listed above. No native store
admission, run-format change, or action permission was introduced.

### Ottomat v4 typed value selection

`ottomat 4` builds `automat.scalar-dag@2`. Its pure `select@1` handler
routes a `scalar.distance@1` condition to one of two `scalar.level@1`
results. The native planner requires all three dependencies. Both
alternatives still execute and get recorded, so the selection cannot
hide an invalid branch, an effect or a budget overrun. The versioned
[`scalar-run@2` format](RUN_FORMAT.md#scalar-run2-typed-selection) binds
the roles of all three parents, even when swapping them would not change
the final numeric result.
The fixture `strategies/scalar-select.ottomat`, with inputs 17 and 42 and a
budget of four nodes, has independently computed BLAKE3 run ID
`396debcfd132cb40dcd87f42e5bcdf5dfe5150a6f3ebd45282e2925f8ee6ae78`.
This profile is analysis-only. It adds no lazy branch execution,
filesystem access, or action capabilities.
The native boundary test freezes and replays a reverse-declared,
16-node selection chain. The pinned compiler and the documented newer
compatibility compiler both passed the chain and existing scalar
manifest checks.
On base `db9cd08` with the release pins above, `make test` exited 0.
The selection consumer passed six read-only replays and rejected 11 native
plans, 13 strategy sources and eight replay bundles. The same consumer
passed on the newer compatibility compiler. Both v2 Yieldcraft run IDs
and output digests, the two archived v1 runs, and the original
`scalar-run@1` golden snapshot stayed unchanged. `make native-test`
passed 2/2 standalone CTests; storage admission remains blocked.

### Yieldcraft current versus archival runs

New Yieldcraft runs can only publish `finpred-run@2`. The CLI recognizes
`finpred-run@1` only when decoding a frozen manifest for read-only
inspection. Both paths retain the same vetted recommendation engine and
their original version-specific evidence. Strategy syntax and SDK/contract
versions are independent of this split.

The CLI writer in `source/cli/app.on1x` has no version argument, and
`source/cli/run_formats.on1x` exposes only a v2 manifest encoder. The replay
path has no store writes. On base `db9cd08` and the release pins above,
`make test` exited 0: the format check observed four v2 writes, two read-only
v1 archives, and two unknown-version rejections. The pinned v2 run IDs and
output digests were unchanged, as were the archived fixture bytes.
Both native CTests passed; the newer compatibility compiler also built the
CLI and passed the focused format check. No schema or permission changed.

```text
CSV/fixtures (local-only) -> On1x CSV/schema contract validation
                        -> As-of eligibility filter
                        -> Stay matching: room subset -> occupancy DP
                        -> One whole-stay gross price/property
                        -> Type-7 quantiles and curve
                        -> Shortcut and independent guardrails
                        -> pricing.recommendation@1 + explanation
                        -> immutable snapshots + run manifest
replay(manifest ID) -----^ (no artifact mutations or external actions)
```

`source/core/` owns validated scenario/offer/valuation values, date checks,
minor-unit money, serialization, CSV and the recommendation record. `plugins/yieldcraft/` owns the bounded
whole-stay matcher and recommendation strategy. `source/automat/` checks the
first fixed typed DAG. `source/ottomat/` is a version 1 exact descriptor
frontend, not a second runtime. `source/sdk/` holds a closed-by-default
manifest policy. `source/store/` handles BLAKE3 identity, file snapshots and
run manifests. The CLI and store perform local file access.

The On1x SDK admits exactly the built-in pure Yieldcraft strategy. The
separately built [C11 descriptor ABI](../source/sdk/README.md) exposes its
package metadata and compatibility checks to native consumers. An opaque
descriptor handle is a reference to library-owned constants, not an On1x
runtime pointer or a grant to invoke a plugin.

## Exactness and economic semantics

**Yieldcraft relocation check (base `24c6f3d`, Linux x86-64, C11):**
`./bin/build.sh`, `tests/check_yieldcraft_package.py`,
`tests/check_dragnet_frozen_csv.py` and `tests/validate_static.py` passed.
The local MuLIB source was `87cbf7c361667c62f82759bd0c02834b2b07315c`,
LibStone `b5c962721a32df18b2fb22de136c1f2ef8b6390d`, and the `on1xc`
binary SHA-256 `0d63fc81d978f1588df8700cf4222ceb0b4425af26a97a591395b751d331a9af`.
Fresh default and multi-room stores compared byte-for-byte equal before and
after relocation (`diff -qr`), at 17100 and 16000 cents/night respectively.
`./tests/run.sh` exited 1 in both builds: the default strategy produced v2 ID
`289b11b9e247740d5616e835132197a62703a315ebdf6dac64a0a45cc598119f`,
where the historical assertion expects `28b145fb…`. Later suite checks did
not run; the archived fixtures and assertions were not regenerated.

**Replay compatibility repair:** The subsequent fix restored the v1 archive
and six shipped strategy payloads byte-for-byte from `b1d6f02`. Both header
spellings now lower to the same plan; the raw snapshot still determines
identity. On the toolchain above, `./bin/build.sh && ./tests/run.sh` exited
0, including both archived v1 replays, the pinned v2 IDs and output digests
for both fixtures, all five policies, and read-only replay of a declaration
using the newer header spelling.

- Every monetary input is a signed 64-bit **minor-unit integer**. Parsed
  prices, fees and taxes are bounded at 10^12 cents each; the gross sum must
  remain at most 10^12. The maximum four-room bundle is at most 4×10^12.
- A source row is already one **observed bookable room inventory unit**,
  with whole-stay base, total fees and taxes; the model makes **no** live
  availability or child policy inference. Separate adult, child and combined
  occupancy capacity are honored exactly by bounded DP.
- Only matching arrival/departure and currency, valid economics and
  as-of observations can enter the distribution. `observed_at` is the source
  timestamp; `ingested_at` is when that observation arrived, and both must
  precede `decision_at`. Recency uses an explicitly declared calendar-day
  bound, not an implicit 24-hour floating duration.
- Each eligible property contributes **one cheapest feasible whole-stay
  bundle**, preventing room-count bias. Cases without a bundle contribute
  no observation; infeasible property count is included in the trace.
- We compute quantiles in exact whole-stay minor units using
  Hyndman–Fan **type 7**, `h=(n-1)*p`, linear interpolation, half-up cent
  rounding. All observations in a scenario cover the same exact number of
  civil nights. Effective night rate uses a second half-up division by that
  number of nights. Prices are never stored as binary float.
- A scenario can pin target percentile (basis points 0..10000). If zero,
  the curve applies. Linear: `4000+3500*d/90`, quadratic:
  `4000+3500*d*d/8100`, with lead `d` clipped to [0,90]. All divisions
  truncate positive intermediate integers. P40 is the shortcut baseline.
- The monetary shortcut selects P40 only when `Ptarget-P40` is strictly
  less than `shortcut_cents`. The guardrail operation clamps the result into
  `max(floor,current-max_move)..min(cap,current+max_move)` and fails if this
  intersection is empty. A guardrail-adjusted reason supersedes shortcut.
- **No publishing happens**, regardless of input. Execution mode fails and
  no Action node is exposed in the fixed graph.

## Resource and security bounds

CSV at most 512 room rows and 2 MiB per file; 10 admitted offers per
property; at most 4 selected rooms and 8 adults/8 children; scenario
search_budget at most one million enumerated subsets. Each occupancy DP has
at most 81 states. Unknown CSV columns, quoted inputs and other currency
values fail closed. Script path selection is operator-controlled, not plugin
authority. The BLAKE3 digest syntax is checked when used as a filesystem
object name, preventing IDs that escape the artifact directory.

The local store uses `artifacts/blake3-{hex}.txt` and
`runs/{hex}.txt`. Existing paths are never deliberately overwritten with
different content; replay independently rehashes all fetched snapshots and
recomputes the output and trace from immutable inputs. The current writer
reserves each unpublished name using `mkdir` and publishes complete files by
same-filesystem rename. Busy reservations fail explicitly. The
[store protocol](../source/store/README.md) explains how to handle an
abandoned stage. Atomic visibility for cooperating writers does not imply
power-loss durability, directory symlink confinement, or authenticated audit.

## Module and kernel decision

MuLIB's `mulib-staymatch.h`, `mulib-pricecurve.h`, `mulib-contract.h` and
other headers are useful future integration targets, but in the checked
On1x repository they do not have admitted general callable KernelBind
profiles. Instead of silently claiming approval, the bounded matching,
quantile and policy computations are implemented in On1x. MuLIB's
standard-library C11 bridges provide local I/O, i64 array handles and
BLAKE3 hashing; they are treated as raw trusted SDK facilities and require
operator review. The existing Histprice/PriceOpt reviewed profiles are not
needed for this price-by-comparables vertical and no dummy forecast model is
invented.

## Acceptance record

### Local verification environment (2026-11-23)

FinPRED starting revision `b484951`; EndeavourOS, Linux
`6.18.52-1-lts` x86_64, GCC `16.2.1`, GNU libc `2.44`, CMake `4.4.3`,
Python `3.14.7`, `jsonschema` `4.26.0`. The Python oracle and native
runtime are separate checks:

- `python3 tests/check_fixtures.py` (exit 0): 17,100 cents with five
  independent properties and two rejected rows; 16,000 cents with three
  feasible properties and one infeasible property. For the multi-room
  fixture the oracle enumerates assignments of guests, derives whole-stay
  prices of 23,000, 30,000 and 35,000 cents, and verifies the guardrail
  adjustment from 15,000 to 16,000 cents/night.
- `python3 tests/validate_static.py` (exit 0): 15 On1x modules,
  four schemas. This checks packaging and source structure only.

MuLIB was checked out at `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
LibStone at `b5c962721a32df18b2fb22de136c1f2ef8b6390d`. Compiler:
`third_party/mulib/build/on1x/on1xc`, SHA-256
`0d63fc81d978f1588df8700cf4222ceb0b4425af26a97a591395b751d331a9af`.
The compiler does not support `--version` (exit 2). Host ABI:
`x86_64-pc-linux-gnu`, SysV. Initial configure failed (exit 1) with the
default temporary volume full. These commands succeeded (exit 0), with no
`warning:` diagnostics in the compiler build log:

```sh
git -C third_party/mulib submodule update --init on1x/third_party/libstone
mkdir -p third_party/mulib/build/tmp
export TMPDIR="$PWD/third_party/mulib/build/tmp"
cmake --fresh -S third_party/mulib/on1x -B third_party/mulib/build/on1x -DBUILD_TESTING=ON
cmake --build third_party/mulib/build/on1x --parallel 4 --target on1xc
./bin/build.sh
```

The reference compiler accepts immutable textual **atoms** in nominal records.
Typed inputs, reasons, plan labels, and descriptor fields use `sx_string`
at construction and `sx_text` when passed to string functions. This is an
internal representation change; persisted fields are ordinary JSON strings.
The original project descriptors worked with the pinned loader.
The `@1` schemas now encode the existing per-kind units, exact raw-parent
counts, and runtime bounds (up to 4×10¹² cents for pre-guardrail quantities).
This ratifies the initial envelopes without changing the v1 manifest layout
or rewriting existing artifacts.

### P0 CLI results (v1 writer)

`./bin/finpred run` and `./bin/finpred replay RUN_ID` exited 0 for each
fixture. Replay printed `replay_ok=true` followed by the original output.
Both recommendations printed `published=false`.

| Input | Run ID | Trace evidence |
|---|---|---|
| Default CSVs | `2e9001180390d28e4ed18a299d12e0913d6b85e75af5d022921169e8513f1b46` | 5 feasible properties, 2 rejected offers, 5 subsets; P50 17,500, P40 17,100; `lower_percentile_shortcut` |
| `scenario_multiroom.csv`, `offers_multiroom.csv`, same valuation | `b45c4c20ade0ab1a8b01e3d6eb0fc0381eed9fb7c2cc480314c024364ded93b6` | 3 feasible properties, 1 infeasible property, 6 subsets; P50 15,000, floor 16,000; `guardrail_adjustment` |

Across the two runs, `python3 tests/validate_runtime_json.py "$FINPRED_HOME"`
exited 0: **2 scenarios, 12 offers, 1 shared valuation, 2 recommendations**.
This validates the actual persisted JSON against all four Draft 2020-12
schemas, in addition to the application's own CSV semantic checks.

Final canonical `./bin/build.sh` exited 0 and produced `target/dev/finpred`
(SHA-256 `2d7d669aeb16b7444ea774b67583c7911576eda4cc08e14f37fe20bbd28fb073`).
`./tests/run.sh` exited 0 (`on1x_integration_ok=true`). It checks native
selftest, both fixtures and their trace counters, replay with source paths
unavailable, identical repeat runs, and an unchanged store tree. Negative
checks cover snapshot corruption (including a normalized stale offer),
missing/oversized outputs, NUL-suffixed snapshots, changed
manifests, invalid scenario and execution denial. The suite also runs
`tests/check_pricing_cli.py` (8 cases) and `tests/check_ingestion_cli.py`
(14 cases), including exact shortcut equality, both intermediate lead-time
curves, exhausted search budget, late evidence, decimal overflow and
embedded NUL. The expanded suite's first intermediate run exited 2 on an
obsolete validator filename; the final suite uses the validator above.

### Legacy replay fixture

`fixtures/replay_v1.json` is a byte-preserving capture of the two successful
v1 runs above, made **before** introducing a new writer. Its `files` map
holds the 27 original ASCII store files under their relative names; its
`runs` map holds stdout keyed by run ID. The embedded producer SHA-256
identifies the P0 executable. These are synthetic pricing fixtures. To test
an upgraded reader, restore these bytes to an empty home and replay the
original IDs, rather than creating fresh manifests with the upgraded code.

### Versioned run lineage (v2 writer)

The [v2 format](RUN_FORMAT.md) binds normalized scenario, valuation and
offer digests (including rejected offers, in original order), raw digests,
the seven graph nodes, and versioned pricing policies into a BLAKE3 run
ID. This is the digest of a stored replay recipe, not an executable
signature or proof of authorship. The four contract kinds stay at `@1`.

After `./bin/build.sh`, the default and multi-room runs produced
`28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db`
and `7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b`,
respectively. Prices and reasons matched the v1 table. Restoring v1 then
writing v2 to the same store, `python3 tests/check_explain_cli.py HOME ID`
passed on each ID: full trace bytes matched the verified replay summary
and stored trace; removing that trace prevented a successful explanation.

`python3 tests/check_pricing_cli.py` (32 cases) and
`python3 tests/check_ingestion_cli.py` (65 cases) both exited 0 against
the v2 executable. The checks distinguish many rooms from many independent
properties, exercise the maximum four-room price, ties and two-stage
rounding, exact as-of and freshness boundaries, 512 versus 513 offer
rows, and failure on inadequate evidence.

Final shared `./bin/build.sh`, `python3 tests/validate_static.py`, and
`./tests/run.sh` all exited 0 (16 On1x modules, four schemas; executable
SHA-256 `78abb88093e582c4fc5481a4683ca2b7fe4a665c10948f1922edb7f257d1388c`).
The integration run validated 17 envelopes and matched all normalized
payloads, units and timestamps to their raw CSV parents. In a separate
negative check, a schema-valid one-cent change to a rejected offer failed
this comparison. Eight of eight concurrent writers completed on the
observed run; an occupied reservation is also a permitted explicit failure.
Checks covered recovery after cleanup, two reservation boundaries and three
invalid directory placements. These are process-level tests, not a
power-loss or hostile-filesystem certification.

| Gate | Artifact | Status |
|---|---|---|
| P0 units/dates/contracts | Strict On1x CSV semantic validation and four versioned JSON Schemas | Compiled; all four fixture envelope kinds validated |
| P1 local store/CLI | BLAKE3 snapshots, v2 policy and parent lineage, atomic file visibility, read-only v1/v2 replay | Both fixture generations replayed; power-loss durability and symlink confinement outstanding |
| P2 Yieldcraft | Bounded exact multiroom matching, property dedup, Type-7 quantile, curves, shortcut, guardrails, trace | Fixture prices and derived room-allocation witnesses verified; `source/automat/runner.on1x` executes the validated fixed plan for both runs and replay |
| P3 Automat | Typed checked fixed DAG, action/effect denial | Narrow source implementation |
| P3 Ottomat | Bounded v1/v2 declaration parser and checker | Lowers to the seven-node Automat plan; not a general DAG language |
| P3 SDK | Static package compatibility checks for three packages in On1x and C11, plus legacy C descriptor ABI v1 | Contract, dependency, budget and grant checks exercised; dynamic loading and untrusted worker isolation remain open |
| P4/P5 | durable scheduler, approvals, action reconciliation, Poindexter/FX/etc. | Not implemented |

## Next implementation gate

**Integrated source checkpoint:** `TMPDIR="$PWD/target" ./bin/build.sh` and
`TMPDIR="$PWD/target" ./tests/run.sh` exited 0 on the pinned toolchain.
The fixed runner rejected six invalid plans or modes; Ottomat accepted 24
valid encodings and rejected 47 malformed declarations and four incompatible
graphs. Both SDK implementations passed the same 106 package cases. The
static hosts now check compatibility before strategy, source and pricing-view
dispatch. Store tests exercised a handled artifact write failure and an
interrupted manifest write. Replay, all five named profiles and the two
frozen fixture prices remained intact.

**Named target policies:** five [Ottomat 2 strategy files](../strategies/README.md)
select fixed P40/P55/P75 or linear/quadratic lead-time targets. The pinned
shared build and `TMPDIR="$PWD/target" ./tests/run.sh` passed
(`strategy_profiles_ok=true profiles=5`). Named policies have distinct v2
run identities; the existing v1/v2 fixture prices and digests remained stable.

**Poindexter workbench:** `./bin/poindexter --build` builds a separate On1xfile
C11 executable with workbook, formula and scripting modules. The Bash terminal
host opens an empty book, CSV values or a verified replay projection.
`python3 tests/check_poindexter_workbench.py` passed arithmetic, memoized
dependencies and cycles, lazy IF, anchored copies, quoted CSV, bounded scripts
and rollback. A real pseudo-terminal test moved the cursor, edited a formula,
ran a statement, undid/redid a change, saved and reopened the book. A seven-night
working scenario derived from the default run totaled `121800` cents and left
the original store unchanged. The pinned application build, Python oracle,
static checks and `./tests/run.sh` also passed. The spreadsheet uses its own
`poindexter-workbook@1` format; persisted pricing contracts and v1/v2 run IDs
are unchanged. See the [worksheet language and limits](../plugins/poindexter/workbench/README.md).

**Yieldcraft package:** `plugins.yieldcraft.entry.recommend` is a compile-time
On1x entry point over the existing matcher and strategy. A standalone C11
consumer build (`python3 tests/check_yieldcraft_package.py`, exit 0)
reproduced the two fixture recommendation envelopes with both v1 and v2
identities, rejected five unsupported modes and five invalid inputs, and
performed no store writes. The CLI remains the owner of run and replay.

**Dragnet package:** `python3 tests/check_dragnet_frozen_csv.py` built the
offline C11 host and exited 0 (`eligible_fixture_rows=5`). Its Source
entry point accepts frozen offer bytes and a validated scenario and emits
as-of eligible `hospitality.offer@1` JSON Lines, preserving the digest of
the complete raw offers snapshot. Only the host reads the selected files.

**Poindexter package:** the root On1xfile links `poindexter.sheet` as a
local library. `bin/finpred poindexter RUN_ID` emits only CSV, after normal
replay verifies every input, normalized object and output. The package test
passed nine negative cases. `./bin/build.sh` and `./tests/run.sh` exited 0
with the shared host: `poindexter_cli_ok=true v1=2 v2=2 rejected=2`. The
sheets retained the recommendation and normalized valuation digests and
showed differences of −400 and −1500 EUR cents/night. No run format changed.

**C11 SDK checkpoint:** On the pinned MuLIB revision listed above,
`python3 tests/check_sdk.py` built and installed `libfinpred_sdk.so.1`,
compiled a separate consumer against `<finpred/sdk.h>`, and exited 0:
`c_sdk_ok=true abi=1 manifest=yieldcraft.percentile`. The consumer checked
ABI/name lookup, package version, contracts, resource limits, allowed modes,
and denial of execution and nonzero capability requests. `./bin/build.sh`,
both Python fixture/static checks and `./tests/run.sh` also exited 0; the
pricing results and archived replay IDs were unchanged.

**Property evidence checkpoint:** The native `bin/finpred evidence RUN_ID`
command verifies the run before printing its per-row eligibility, property
outcome, cheapest bundle and adult/child room allocations. These are derived
from frozen inputs, not newly persisted observations. `./bin/build.sh`,
`python3 tests/check_fixtures.py`, `python3 tests/validate_static.py` and
`./tests/run.sh` exited 0 on the pinned toolchain (16 On1x modules, four
schemas; `evidence_cli_ok=true v1_runs=2 v2_runs=3`). The original v1/v2
fixture IDs and prices remained stable. See [report grammar](../plugins/yieldcraft/EVIDENCE.md).
Store publication now removes its own staging file after a reported short
write; `tests/check_write_failure.py` verifies retry without manual cleanup.

Finish P1 storage with a reviewed directory-relative filesystem interface
for no-follow opens, no-replace publication, and file and directory sync.
The standalone [Linux C11 store candidate](../native/README.md) now implements
those host operations. On local Btrfs, `cmake -S native -B build/native
-DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'`, `cmake --build build/native
--parallel 4` and `ctest --test-dir build/native --output-on-failure` exited 0
(2/2 tests). The checks include six real contending processes, scoped reader
and writer behaviour, partial-write and sync failure outcomes, and all 27
archived v1 store files copied byte-for-byte through the C API. On the recorded
MuLIB pin, `./bin/build.sh`, the fixture oracle, static checks and
`./tests/run.sh` also exited 0; the CLI still uses its existing backend.
Power-cut/remount validation and compiled On1x-to-native store calls have
not been performed.
The [admission specification](../native/STORE_ADMISSION.md) records the
missing prerequisites and the pinned compiler's rejection of the storage import.
The current names and replay formats do not require an in-place migration
for this work. The full P1–P4 exit gates in `AGENTS.md` remain open.
