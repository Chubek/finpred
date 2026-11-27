# Core overhaul: scope and admission

The integration base is FinPRED `f2fc160349a8e83e62ede88557c9a4cb026387d3`.
It pins MuLIB `cbb7d66f217f188493f25b38c10101aa26469c48`, which pins
LibStone `4e60694e341977ebf39b3344cb5fb3bcb2684af2`. On1x, GrammarEmbed,
and the MuLIB kernels come from that MuLIB tree; Cephyr and its generators
come from that LibStone tree. Qualify the C11 hosts, not the toolchain's
entire backend inventory. Do not recursively initialize LibStone: a retired
gitlink in that tree has no mapping.

LibStone's Valijson tree is `9cfec2396c421aadaa6061af037998de0bbfa715`;
it is not the upstream Valijson checkout used in older CI. The only separately
provisioned header checkout for this Cephyr build is nlohmann-json at
`322063822f66533bb81ef8e938fd07e5f6394917`. The historical Aurocks helper
used only by Cephyr's qld build is LibStone blob
`cbf0cddc364ca1a48d55d51abc5107d71b1b16a9`. The generated On1x scanner uses
the pinned native Aurocks, not that Perl helper.

## Eight review lanes

| Worker | Exclusive implementation ownership |
| --- | --- |
| 0 Broker | Toolchain, staging, release and suite wiring; IPC and integration records |
| 1 Architect | `source/core` except price prediction; nominal financial types and focused checks |
| 2 Automat | `source/automat` and focused schedule/graph tests |
| 3 Ottomat | `source/ottomat` and focused frontend/lowering tests |
| 4 Numerics | `source/algorithms`, `source/core/price_prediction*`, focused statistical oracles |
| 5 Evidence | `source/store`, `native`, new evidence contracts and tests |
| 6 Interfaces | `source/sdk`, `source/cli`, `source/main.on1x`, Python bindings, interface tests |
| 7 Verification | Independent gates and acceptance record; no production patches |

Keep each lane on a separate branch/worktree. Workers report revision,
contract, tests and known failures; a report does not admit a patch. Check
ownership, diff and tests, then verify the combined candidate. Existing
plugins and plugin-owned build inputs are out of scope. No archives,
historical fixtures, dependency gitlinks, or existing action authorizations
are replaced.

## Compatibility constraints

- The old fixed, scalar and typed-financial graph paths have different
  scheduling, handler, and identity contracts. Canonicalization must be
  version-specific. Validating one graph does not authorize an effect.
- Legacy Ottomat frontends preserve the grammar, error ordering, lowering and
  evidence of their declared version. New grammar does not upgrade stored
  strategies on read.
- Existing code-identity fragments include `core/contracts.on1x`, `csv.on1x`,
  `date.on1x`, `money.on1x` and, for forecast subjects, `feed_snapshot.on1x`,
  `format.on1x` and `sdk/callable.on1x`. Check the exact old bytes before
  changing any subject-linked implementation.
- A manifest digest does not authenticate a producer. Atomic visibility,
  file and directory synchronization, crash recovery, and post-power-loss
  durability are separate claims. Plugin action capabilities remain disabled
  unless admitted under their separate authorizations.

## On1x and MuLIB adoption gates

Use the pinned `on1x/docs/{language,modules,operators,nominal-adts,ownership-backends,opaque-module-abi}.md`,
the `stdlib/on1xfile` project guide and `hir/FFIHandler/README.md`. Declared
`.on1xm` membership and `.on1xi` signatures are a whole-unit checked boundary,
not separately compiled ABI files. Non-generic sealed copy values have a
direct-C11 execution path; sealing is not transported in Unit-v1 PPX and is
not inferred to work in MIR. Keep foreign bytes out of nominal owning fields
unless the lifetime is proved. Copy values and lexical loans do not imply
cross-thread closure or runtime safety.

Use selective imports for operators. Custom precedence and tightness are
separate tiers, with explicit associativity; operands are evaluated once in
source order, including for ternary operators. Prefer `std.operators` and
`std.operator.utils` for operations they define. Do not use a Result-returning
operator as if it provided control-flow short circuiting.

The pinned build separately scans C headers, emits diagnostic catalogue
entries, and indexes executable recipes admitted by its compiler. A `*.ffi`
in `catalogue/` is **not** executable. Manifest registration is sufficient for
some native link-driver uses but not for language-call ownership, error
semantics, or backend parity. No production `import foreign stdffi` is
justified by an upstream test that provisions its own signed test recipes.

| Facility | Useful upstream semantics | Decision / blocker at the pin |
| --- | --- | --- |
| Money, Fraction | Explicit currency/scale and bounded checked rational arithmetic | `missing-views`; preserve archived parsing and rounding. Do not silently substitute fraction normalization or Money import. |
| TimeSeries, AsOf | Ordered samples, separate effective/knowledge cutoffs, withdrawals and winning-rank conflicts | Both `missing-views`; TimeSeries does not model same-key revisions directly. AsOf is a candidate for a distinct native selection policy, not the old guest-night policy. |
| Contract, DecisionTrace | Bounded contract metadata/digests and event-buffer encodings | Both `unsupported`; neither encoding is an existing FinPRED identity. |
| Backtest | Finite point scores and replay checks | `missing-views`; not a leakage-resistant model selection pipeline or a replacement for exact archive arithmetic. |
| Portfolio, Risk, FXRate | Mark/gross, limit diagnostics, directed cutoff-aware conversion | `missing-views`; no FX or implicit conversion is admitted by discovering these headers. |
| HistPrice, StatsProc, PriceOpt | EMA/Holt, seasonal and AR/robust trends, Theil–Sen, scenario/candidate search | `missing-views` in the production scan. Keep the trusted static C route for applicable kernels; check bounds, rounding and validation on its On1x bridge. |
| Graph, NodeGraph | Topological traversal, compile/validate, cache components | Native ordering and representation do not establish equivalence to named typed ports, canonical graph bytes, or Automat tie-break rules. |
| Hashing | Host cryptographic and BLAKE3 implementations | Use the existing trusted runtime hash for archived bytes and vetted native digest implementations for new identities; no authenticity claim. |
| JSON, CBOR, Artifact | Byte/object codecs and bounded artifact envelopes | `missing-views`; no substitution without canonical-byte and resource proofs. Artifact is not a durable store. |
| POSIX queues/shared memory | `on1x/tools/on1x-module-coord.c` uses `mq_open` and `shm_open` at this revision | Reference for POSIX APIs, distinct from MuLIB System V IPC. It does not broker grants. FinPRED development coordination is separate from engine FFI. |

The clean build classified 2,077 catalogue entries (1,755 missing views,
322 unsupported, zero malformed) and emitted one executable recipe:
`stdffi.clamp`. A signed-64-bit boundary probe for saturation and clamping
matched a Python integer oracle in direct C11, MIR-generated C11, the
reference evaluator, and a separately emitted and verified VM image run by
`on1x-vm`. This probe did not admit saturation as a financial checked
operation, or qualify any FinPRED host on MIR/VM. The unchecked reversed
interval also returned the recipe-defined value; callers cannot infer an
invalid-interval diagnostic.

## Baseline evidence

The source pins above were verified before the build. Local build host:
Linux x86-64 6.18.52-1-lts, glibc 2.44, GNU ld 2.47, Clang/Clang++
22.1.8 for the compiler and GrammarEmbed, GCC 16.2.1 20260810 for generated
host C, CMake 4.4.3, Make 4.4.1, Python 3.14.7, Perl 5.42.2 and
pkg-config 3.0.7. The observed dependency versions were LibYAML 0.2.5,
libxml2 2.15.4, Jansson 2.15.1, curl 8.22.0, OpenSSL 3.6.4 and X11 1.8.13.
Local schema-test versions: `jsonschema` 4.26.0, `referencing` 0.37.0,
`jsonschema-specifications` 2025.9.1, `attrs` 26.1.0 and `rpds-py`
2026.6.3. This is a host observation, not a claim to match CI's wheel lock.

| Local toolchain artifact | SHA-256 |
| --- | --- |
| `on1xc` | `b27704b426e3f3546be246b2c18e5251798caa41c978faf1384532a35c24e774` |
| GrammarEmbed | `7353cdd5e341e0368137af3aff863ce459d3c5b3fa0a82a24bc7d4f12603806b` |
| GrammarEmbed schema | `e2a26a3ca3620e43ec2289ef749746b1f6a956d087e0676cd225d02bb7fadeaa` |
| host `libcephyr.so` | `01c9f1e1caab86931465abde7a06f61202dbc161b8d6349c9a847f3362242562` |
| generated `stdffi/mulib/index.json` | `d5a37ea74d370bcf2b13315ecc6001982dfb9b868b1f614775e17a5a94f44acb` |
| application `cc` | `8aac907d6fbf40394b424b5fa4a2ad1aa291dac7d3a0315c5b415c1f5ace1287` |
| compiler-build `clang` | `67ad17f2e61ed725abd3cefdd3fa1c24dc5c09ec3ed064dc03c0798e66fe8955` |
| compiler-build `clang++` | `b621028947ed7d2b0c0d8cdae1cb886ac8371fd47f8d25162568812eb9ccfe` |
| compiler-build `llvm-ar` | `a6d906986e7840289870d48f29a69f0178c352c299eb5c72802b256482943c60` |

Fresh app build and selftest passed. The baseline `pricing` and `storage`
suites passed; they cover 17,100 / 16,000 / 18,000 / 17,001 minor units,
four exact v2 digest triples and both v1 read-only replays. Baseline app
reproducibility compared all three hosts across clean output paths with the
same installed toolchain. `compiler`, `forecasting` and `security` initially
failed on an inherited test-build path and stale MuLIB `include/` references.
All three passed against the same baseline app after repairing the harness.
The release wrapper passed two same-toolchain bundle builds with different
paths and umasks, relocated execution/replay, and eight malformed archives.
This is not identical compiler outputs across independent clean compilers.

Upstream GrammarEmbed, bridge, stdlib project, module visibility, opaque
module, recipe compiler, nominal-data source, operators, ownership and
backend-capability gates passed after building the relevant test targets.
Pinned upstream `on1x.nominal_hir` failed with `invalid nominal HIR/wire
admitted`, also documented upstream before this application change. Do not
qualify arbitrary imported HIR or extend trusted execution from that gate.
Native Archon, ArchVirt, and Cephyr execution backends were not configured
in this build; the separate Cephyr build-host library is not execution
evidence for those backends.

## Coordination protocol v1 (Linux/glibc)

`bin/overhaul-coord.py` is a development utility, not part of the analysis
bundle. Use Python 3, a private journal path and a fresh session name:

```sh
export FP_JOURNAL="$PWD/build/work/coord.jsonl"   # create parent directory first
c() { python3 bin/overhaul-coord.py --journal "$FP_JOURNAL" work42 "$@"; }
c 0 init
c 0 contract 'Review every candidate; preserve archived bytes'
c 2 status 'Working on the slot scheduler'
id=$(c 2 request 3 schedule-review)
c 0 snapshot
c 0 grant "$id"
c 2 send "$id" 'Candidate ready for consumer review'
c 3 recv
c 3 ack "$id"
c 0 cleanup
```

The shared-memory object uses two checksummed versioned slots with generation
counters. A bounded advisory `flock` serializes cross-process operations and
releases on process death. Publication invalidates the older slot before
writing new bytes; an interrupted publish leaves the other slot readable.
Statuses include monotonic heartbeat times. Each worker has one real POSIX
queue with capacity two, a 1 KiB message bound, and bounded waits without
holding the state lock. Backpressure never overwrites a queued notification.
Requests and grants are bounded; grant correlation, direction, purpose,
monotonic expiration and session epoch all bind the canonical queue envelope.
Receipt validates its exact wire digest. Ack is a separate state transition.

The append-only journal records decision text, metadata and payload digests,
not queue payloads or status notes. Do not put credentials in any command,
contract, or message. Journal entries precede shared publication: after
process death an entry can be intent without a matching published sequence.
Neither journal nor queues promise crash-durable or exactly-once delivery.
If a sender or recipient dies around the queue operation, the broker can
inspect the state, `revoke` the old exchange and admit a new correlation.
Applications must not put non-idempotent actions on this channel.

The `0600` objects are private to a UID, not to a worker identity. Worker 0
alone authorizes operations by cooperative protocol; a same-UID process with
access to the namespace can bypass that protocol. Use a private IPC namespace
to separate queues from unrelated local processes; it does not provide
per-role authentication or separate `/dev/shm` without mount isolation.
Run only trusted workers. A hostile-worker deployment requires distinct
principals and an authenticated broker boundary; this tool does not implement
one. After a killed initializer, Worker 0 must clean up that **reserved**
prefix before retrying. Do not reuse a prefix owned by another session or
remove unrelated queues to work around kernel quotas.

### Integration decisions

The working session used eight isolated Git worktrees and a private Linux IPC
namespace. The broker admitted all seven candidate routes and approved the
direct Automat→Ottomat contract exchange (correlation `49`); the recipient
acknowledged the unchanged `compose`/`prepare` contract. Candidate admission
did not bypass review: standalone C/Python numerics, SDK and temporal
implementations were checked independently before the combined gates.
Production build, tests, and review artifacts were staged without changing
the plugin source tree, fixtures or either gitlink.

This increment uses the existing typed financial graph as the canonical target
for new composed strategies. The fixed and scalar engines remain distinct;
the compiled schedule is deterministic and serial, not a general parallel
effect scheduler. Generic robust forecasting does not add Holt–Winters,
arbitrary AR/state-space models, nested model selection or optimization.
The temporal storage target is native-host-only and does not replace the live
On1x store. The Ottomat v7 frontend and robust series API are library
interfaces; there is no new archive serializer or general graph execution CLI.
See the [verification record](CORE_OVERHAUL_VERIFICATION.md) for scoped results.
