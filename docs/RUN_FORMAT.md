# FinPRED immutable run formats

Yieldcraft writes `finpred-run@3` for expected contribution and
`finpred-run@2` for secondary market positioning. There is no `finpred-run@1`
writer. Archived v1 market-positioning runs are supported read-only by
`replay`, `explain`, `evidence`, and `poindexter`.

`runs/<run_id>.txt` is the commit record for a successful recommendation.
All referenced bytes must be present before committing it locally. All three
formats use a canonical, **404-byte** manifest: seven comma-separated
ASCII fields, no spaces, and exactly one final LF. No CRLF or optional
fields. Each `H` below is 64 lowercase hexadecimal characters (BLAKE3-256).

```text
finpred-run@V,Hraw_scenario,Hraw_offers,Hraw_valuation,Hraw_strategy,Hrecommendation,Htrace
```

`V` is `1` or `2`. Each `H` resolves to `artifacts/blake3-<H>.txt`. Hash the
exact bytes, including any terminating LF. The run ID is **not** the digest
of this manifest: the recommendation contains the run ID itself. Replay
checks the output fields against independently recomputed bytes and hashes.

## V3: expected contribution

V3 assigns the third manifest field to raw own-demand evidence instead of
raw competitor offers. It does not reinterpret previous formats.

```text
finpred-run@3,Hraw_scenario,Hraw_demand,Hraw_valuation,Hraw_strategy,Hrecommendation,Htrace
```

The run ID is the BLAKE3 digest of the exact lineage artifact below. Each
line ends in LF; the four digests name the original input snapshots.

```text
finpred-run-lineage@3
strategy=yieldcraft.contribution@1
graph=yieldcraft.contribution-graph@1
mode=recommendation
raw_scenario=<H>
raw_demand=<H>
raw_valuation=<H>
raw_strategy=<H>
```

`replay`, `explain`, and `evidence` recompute the recommendation and trace from
the frozen inputs, check all stored digests and bytes, and do not write.
No live model or inputs are required. The output contract is
[`pricing.contribution-recommendation@1`](../contracts/pricing.contribution-recommendation@1.schema.json);
its `source_artifacts` order is scenario, demand, valuation. An external
evidence digest in the demand snapshot identifies an upstream response model
or experiment, not another artifact required for replay. The `evidence`
report (`yieldcraft.demand-evidence@1`) lists model provenance, feasible price
bounds, marginal cost, and the recomputed candidate rows
`candidate=<price>,<expected_milli_room_nights>,<score_in_milli_minor_units>,<status>`.
The Poindexter market-positioning sheet does not consume this contract. See
the [strategy documentation](../strategies/README.md) for the input rules
and objective.

## V2 market-positioning writer and verifier

The v2 run ID is the BLAKE3 digest of the **lineage artifact**, which lives
at `artifacts/blake3-<run_id>.txt`. The first line is a domain separator.
All lines end with LF, including the last. Fields appear exactly once in
the order shown except for the seven `node` lines and the repeated offer
lines. The following is a template; replace angle-bracket placeholders:

```text
finpred-run-lineage@2
engine=finpred.yieldcraft-engine@1
mode=recommendation
strategy=yieldcraft.percentile@1
graph=yieldcraft.fixed-graph@1
node=0,input,none,hospitality.scenario@1,read
node=1,source,hospitality.scenario@1,hospitality.offer@1,read
node=2,transform,hospitality.offer@1,hospitality.offer@1,pure
node=3,algorithm,hospitality.offer@1,pricing.distribution@1,pure
node=4,strategy,pricing.distribution@1,pricing.recommendation@1,pure
node=5,gate,pricing.recommendation@1,pricing.recommendation@1,pure
node=6,output,pricing.recommendation@1,pricing.recommendation@1,record
model=none
matcher=yieldcraft.asof-whole-stay-property-min@1
quantile=yieldcraft.type7-stay-half-up-night-half-up@1
curve=yieldcraft.p40-p75-linear-quadratic-90d@1
shortcut=yieldcraft.p40-strict-saving@1
guardrail=yieldcraft.floor-cap-movement-intersection@1
raw_scenario=<H>
raw_offers=<H>
raw_valuation=<H>
raw_strategy=<H>
normalized_scenario=<H>
normalized_valuation=<H>
offer_count=<N>
normalized_offer=<H>
```

The `strategy=` line shown above is for the scenario market policy. Its
packaged declaration keeps the exact `ottmat 1` bytes that the pinned v2
run IDs depend on. Named [Ottomat profiles](../strategies/README.md) use
`ottmat 2`; for those profiles, `strategy=` is `yieldcraft.<profile-name>@1`,
also recorded in the trace. Both declarations produce `finpred-run@2`
records when used with `run`. `raw_strategy` hashes the exact declaration
bytes. Ottomat syntax and plugin SDK versions are separate from the run
format. Likewise, `finpred.yieldcraft-engine@1` identifies the engine in
v2 lineage, and `pricing.recommendation@1` identifies an output contract;
neither selects `finpred-run@1`. The recommendation envelope retains the
SDK family identity.

The last line repeats `N` times (`1..512`, canonical decimal). It lists the
normalized JSON for **every** data row in raw offers CSV order, including
rows rejected as evidence. The scenario, valuation and every offer envelope
point back to their raw source. Shared or repeated content retains its
position in the list; storage can deduplicate the object. Named policy
identities are semantic versions, not executable fingerprints. Graph nodes
are serialized from the checked plan in topological order. `model=none`
indicates that this strategy makes no model forecast.

Verification from the known run ID:

1. Read the manifest by that ID. Check its version, length, canonical bytes
   and digest syntax. Fetch and independently rehash its four raw inputs.
2. Validate those inputs; recompute the point-in-time match and decision.
   Reserialize the normalized parents from the typed inputs and check their
   stored bytes by digest. Generate the entire ordered lineage above from
   the supported policies, graph and parents. Require its digest to equal the
   requested run ID and its exact bytes to match the stored lineage artifact.
3. Recompute the `pricing.recommendation@1` envelope (its `id` is
   `recommendation:<run_id>`) and trace. The v2 trace appends
   `lineage_blake3=<run_id>\n` to the pricing decision trace. Check both
   stored objects and both manifest output digests. Only then report replay
   success. No live sources, repair writes or external action are required.

`explain RUN_ID` performs the same read-only checks as `replay RUN_ID`.
On success it prints the replay summary, then `trace_begin`, the exact
verified trace bytes and `trace_end` (each marker on its own line).

## Derived property evidence (v1 and v2)

`bin/finpred evidence RUN_ID` requires a committed run. It prints the normal
replay summary, followed by a **derived** report. The bounded whole-stay
match on the frozen inputs both collects evidence and verifies the pricing
distribution.
It prints nothing from that report until all replay integrity checks pass.

```text
evidence_begin
evidence_version=yieldcraft.property-evidence@1
source_run_id=<run_id>
<property evidence lines>
evidence_end
```

Each line ends in LF. See the [evidence grammar](../plugins/yieldcraft/EVIDENCE.md)
for row eligibility, property status, whole-stay bundle prices, room
occupancy and sample counts. The version identifies the evidence report, not
a new run format. Neither v1 nor v2 stored these allocation witnesses. The
command writes no artifacts and does not change the run ID, recommendation or
trace.

## V1 compatibility and migration

The original run ID is BLAKE3 over the literal `finpred-run@1`, LF, and
the four raw digests in manifest order separated by LF, **no final LF**.
There is no artifact named for that run ID. Its normalized objects are
derived from the raw snapshots. Its original trace and recommendation
contain no v2 lineage extension. The verifier selects v1 by the manifest
version and checks the original identity, normalized objects, output hashes
and bytes without writing anything. It accepts only the scenario policy
for archived v1 runs. All three pricing formats can coexist in one store.

Migration means creating a **new `finpred-run@2` identity**, not upgrading
the archive in place. Verify the v1 run first, then pass its four frozen raw
artifacts as `FINPRED_SCENARIO`, `FINPRED_OFFERS`, `FINPRED_VALUATION`, and
`FINPRED_STRATEGY` to `run --engine legacy`. Keep the original v1 manifest
and artifacts under their existing identities. Use current files instead of
the frozen snapshots only if their **bytes** match. The run ID and output references
change even when the economic result does not. Do not rewrite old runs,
silently reinterpret policy versions, or infer v2 metadata for v1. Reject
unknown formats. A future semantic change must get a distinct identity and
retain the old evaluation path (or require the matching archived engine for
read-only replay). Content-addressing checks integrity relative to the
supplied ID; it does not authenticate who created a run.

## scalar-run@1: native analysis

The [native scalar graph API](../source/automat/README.md#frozen-runs)
uses a separate byte format. Its run ID is the lowercase BLAKE3-256 digest
of the **manifest itself**, including the final LF. The selected node's digest
is a different identity. This manifest is not a `runs/<run_id>.txt` CLI
recommendation record. `run --engine scalar` prints the selected node's
digest and trace, but does not persist a scalar manifest or accept it for
pricing replay.

```text
scalar-run@1
plan=automat.scalar-dag@1
mode=analysis
budget=<invocation ceiling>
first=<input value>
second=<input value>
output=<selected node id>
node=<id>,<handler>,<left binding>,<right binding>
artifact=<digest>
root=<selected node digest>
```

The template's `node` line repeats once per declaration (1–16), in
declaration order. `artifact` repeats once for each input (`first`, `second`)
and then each evaluated node, in execution order. `root` appears once and may
refer to a node other than the last one. Budget is 1–16; input values are
0–10¹². Integers have no sign or leading zeros except the single digit `0`.
All fields are ASCII, with LF terminators, no spaces or optional lines,
and a maximum manifest size of 4096 bytes.

A verifier needs the expected run ID, manifest and ordered `(digest, bytes)`
pairs. It checks the manifest identity, reconstructs the declared graph,
runs the pinned handler versions and compares the evidence and selected
output. A budget from the manifest cannot exceed the native 16-node ceiling
or authorize execution mode. A new handler meaning requires a new handler
identity; a new encoding requires its own format version. No v1/v2
migration is involved.

An [Ottomat v3 scalar program](../source/ottomat/README.md#v3-scalar-analysis)
that lowers to the same native plan produces this same manifest, byte for
byte. The host adapter reports the source digest and lowering identity
separately; verifying a scalar bundle does not authenticate a source file
as the origin of its graph.

## scalar-run@2: typed selection

This native analysis format uses the same ordered fields, byte limits and
identity rules as `scalar-run@1`, with `scalar-run@2` on the first line and
`plan=automat.scalar-dag@2` on the second. A selection declaration adds one
binding: `node=<id>,select@1,<condition>,<positive>,<zero>`. All other
node lines retain their original arity. The verifier rejects a mismatch
between the manifest version and graph version, or an attempt to put a
selection node in a v1 bundle.

Selection output uses these exact ordered fields with a final LF:

```text
scalar-select@1
id=<node id>
owner=finpred.core@1
handler=select@1
kind=scalar.level@1
condition=<condition digest>
positive=<positive branch digest>
zero=<zero branch digest>
value=<decimal>
```

Even if a branch is not selected, its digest is still part of the
selection artifact. Binary node and input artifact encodings do not
change. The manifest remains separate from the Yieldcraft store format.

## scalar-run@3: registered scalar algorithms

This format retains the `scalar-run@2` grammar and uses the paired
`scalar-run@3` and `plan=automat.scalar-dag@3` headers. It admits
`midpoint@1`, a statically linked binary handler. Its `scalar-node@1`
artifact has `owner=scalar-diagnostics@1`; previously admitted handlers
retain their existing owner and encoding. Replay verifies that owner and
the versioned handler via canonical recomputation, rather than trusting a
declaration or an artifact hash alone.
