# FinPRED immutable run formats

`runs/<run_id>.txt` is the commit record for a successful recommendation.
All referenced bytes must be present before publishing it. Both formats use
the same canonical, **404-byte** manifest: seven comma-separated ASCII
fields, no spaces, and exactly one final LF. No CRLF or optional fields.
Each `H` below is 64 lowercase hexadecimal characters (BLAKE3-256).

```text
finpred-run@V,Hraw_scenario,Hraw_offers,Hraw_valuation,Hraw_strategy,Hrecommendation,Htrace
```

`V` is `1` or `2`. Each `H` resolves to `artifacts/blake3-<H>.txt`. Hash the
exact bytes, including any terminating LF. The run ID is **not** the digest
of this manifest: the recommendation contains the run ID itself. Replay
checks the output fields against independently recomputed bytes and hashes.

## V2 writer and verifier

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

Each line ends in LF. See the [evidence grammar](../source/yieldcraft/README.md)
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
contain no v2 lineage extension. Replay selects v1 by the manifest version
and verifies the original identity, normalized objects, output hashes and
bytes without writing anything. Formats can coexist in one store.

New runs write v2 only. To obtain v2 lineage for an old run, use the four
verified raw artifacts as the four `FINPRED_{SCENARIO,OFFERS,VALUATION,STRATEGY}`
inputs to `run`; retain the old manifest and outputs under the old ID. A
fresh run with current files is equivalent only if their **bytes** match.
Output references and run IDs change even where the economic result does
not. Do not rewrite old runs, silently reinterpret policy versions, or
infer v2 metadata for v1. Reject unknown formats. A future semantic change
must get a distinct identity and retain the old evaluation path (or require
the matching archived engine for read-only replay). Content-addressing
checks integrity relative to the supplied ID; it does not authenticate who
created a run.
