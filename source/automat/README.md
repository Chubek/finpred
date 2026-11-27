# Automat engines

The [CLI](../../GUIDE.md#choose-an-engine) selects `legacy` (default) or
`scalar` for new runs. Pricing replay always uses the legacy compatibility
path. These engines have different input and output contracts; scalar
analysis does not produce a price or write to the pricing store.

## Typed financial graph

The additive `automat.financial-graph@1` library validates named ports and
references before execution and orders ready nodes by ID. It uses the
host-supplied [`sdk.callable`](../sdk/README.md#internal-typed-calls) resolver and
invoker; the graph and Ottomat source cannot register handlers or grant
effects. This slice accepts only pure work and has no CLI route.

`financial_graph.compile` performs the same validation as `prepare` and
returns its `Prepared` result alongside an in-memory schedule. `prepare`
and `compose` do not construct slots. Roots in the compiled schedule are
sorted by name and assigned the first zero-based artifact slots. Each step
is `(planned_entry, operands)` in execution order and gets the next slot.
Its operands are `(input_name, source_slot, producer_id, output_port)` in SDK
input order; an empty producer ID identifies a root. Exports are
`(output_entry, source_slot)` in export-name order. Slots are decimal strings
in these lists. The runtime uses the compiled slots for operands and exports
and executes every step, even if no export depends on it.

The schedule reports edge count (one per input binding), depth (the longest
path counting nodes, not roots), and declared upper bounds on root, read, and
emitted payload bytes. The read bound counts repeat uses of a value separately;
the emitted bound counts every node, including memo hits. These bounds are
estimates, not new admission limits: the work budget still sums each
declaration's maximum work, and the runtime still enforces its existing
actual-byte limits. A failed compilation has no schedule or metrics. Schedules
are not persisted and cannot be supplied as executable authority.

An external hospitality host binds normalization, whole-stay comparables,
a sample diagnostic, a policy
decision, and guardrail validation. The normalizer retains the rejected-row count and records
the frozen offers artifact as a parent. Only immutable values cross the
graph boundary; matcher handles stay inside each adapter.

`financial_run.execute` returns in-memory artifacts and a trace only on
success. Each artifact contains its value, cutoff, strategy digest, and
ordered named parents; node artifacts also pin the graph and exact SDK
identity. Run-local memoization preserves these artifacts and their ordering.
`financial_run.replay` recomputes from frozen bytes and compares exact
evidence without writing a store. These are not `finpred-run` archives.
`financial_run.execute_pinned` checks a host-supplied canonical graph digest
before running handlers. A terminal output may have zero bytes when explicitly
`unknown` and permitted by its port; external roots and downstream requests
must still be nonempty, even when the edge types otherwise match.
The hospitality adapters reuse legacy validators; some invalid legacy
inputs still terminate the host rather than return a structured error.
The work ceiling is a bound on admitted work, not hard CPU metering.

`financial_graph.compose` joins two bounded typed fragments by linking right
inputs to named outputs of the left fragment. The fragments and composed
graph are each validated; unresolved ports and colliding names fail before
invocation. This is an On1x builder, not new Ottomat source syntax.

`financial_archive.capture` emits an `automat.financial-replay@1` bundle
with the graph digest, mode, cutoff and strategy context, sorted input
values and ordered artifact evidence. `financial_archive.replay` requires
the original typed graph and a separately trusted digest for the bundle.
It recomputes with the host's current approved bindings and bounded resources;
archive bytes do not supply code, authority, or an independent guarantee of
compiler identity. These in-memory bundles do not change existing graph,
artifact, scalar or pricing archive formats.

With a matched On1x compiler and GrammarEmbed installed, run
`python3 tests/check_hospitality_adapters.py`,
`python3 tests/check_financial_graph.py`, and
`python3 tests/check_ottomat_financial.py`. The last test compares the
[Ottomat 6](../ottomat/README.md#v6-financial-graphs) evidence with that of
the native builder byte for byte.

## Legacy recommendation runner

`automat.runner.run(plan, mode, scenario_raw, offers_raw, valuation_raw,
collect, evidence, evaluate)` checks the seven-slot `automat.graph.Plan`
and accepts only `recommendation`. It decodes the scenario and valuation
before it invokes the host-supplied function:

```text
fn(Scenario, Valuation, string, string, bool, buffer) -> Recommendation
```

The additional arguments are the frozen offers CSV, the checked profile
name, the evidence flag, and the caller-owned evidence buffer. The runner
checks the returned recommendation against the valuation and scenario
limits. The runner does not authorize, discover, or isolate callbacks.
The CLI checks its registry binding and supplies the policy for both new runs
and replay.
The [independent consumer](../../tests/fixed_runner_consumer/main.on1x)
builds the runner with a local test policy and only the engine search path.

## Native scalar analysis graphs

`automat.dag` is a native On1x entry point alongside the fixed recommendation
runner. See the [compiled consumer](../../tests/dag_consumer/main.on1x).
To compile a built-in-only host directly, add `source/` to its module search path.
Hosts can freeze and verify this IR through the module APIs below, or lower
an [Ottomat scalar program](../ottomat/README.md#v3-scalar-analysis) to the same
plan. `run --engine scalar` displays results from this plan; the CLI does not
write scalar manifests or evidence bundles.

`Plan` identifies a version (`automat.scalar-dag@1`, `@2`, or `@3`), a declaration
list, and an output node by name. `node(id, handler, left, right)` binds both required ports to
the single result of another declaration or to a graph input (`first` or
`second`). Forward references are valid. IDs are 1–32 lowercase ASCII letters;
they must be unique and cannot shadow the inputs. Every declared node runs,
including nodes outside the selected output's dependencies.

`run(plan, "analysis", budget, first, second)` accepts immutable integer
levels in `[0, 10^12]`. These are unitless diagnostic values, not prices.
The built-in binary operations define both input ports as `scalar.level@1`.
`minimum@1` and `maximum@1` return that type; `distance@1` returns the
absolute difference as `scalar.distance@1`. A distance cannot feed a level
port. Each invocation costs one unit. The plan allows at most 16 nodes,
32 incoming edges in v1 (48 in v2) and depth 16, even with a higher host
budget. Only pure handlers with empty capability sets are admitted.

V2 adds `select_node(id, condition, positive, zero)`. It admits only a
`scalar.distance@1` condition and two `scalar.level@1` alternatives. Positive
distance selects the positive value; zero selects the zero value. Every
binding is an ordinary dependency, even for the unselected alternative.
The trace records them in role order:
`id=select@1(condition,positive,zero):value`.

V3 supports host-supplied binary operations. Use `validate_with`,
`run_with`, `invoke_binary_with`, `freeze_with`, or `verify_with` to pass
the trusted resolver and (where applicable) invoker explicitly. The same
binding should be supplied for lowering, planning, invocation, and replay.
Built-ins cannot be overridden, and an import line never grants capabilities.
Unqualified entry points resolve built-ins only.

Planning validates every binding and determines the complete order before
running a handler. `validate(plan, mode, budget)` checks the same structure
and order without needing input values or dispatching a handler. The first
ready declaration wins each tie. A successful
`Outcome` has status `ok`, the output kind, its canonical decimal value,
and one LF-terminated trace row per handler: `id=handler(left,right):value`.
A rejected plan has a reason code, nil kind/value and empty trace. This trace
is for in-memory analysis; it is not a persisted run or proof of provenance.

### Output lineage and replay

A successful `Outcome` also carries `artifacts`, a proper list of
`(digest bytes)` string pairs, and `output_digest`, the digest of the
selected output node. The list starts with `first` and `second`, followed by
every node in execution order. The selected output need not be last. On
rejection, both fields are nil.

Digests are lowercase, unprefixed BLAKE3-256 over the exact ASCII payload,
including the final LF. The two payload layouts, in field order, are:

```text
scalar-input@1
name=<input port>
kind=scalar.level@1
value=<decimal>
```

```text
scalar-node@1
id=<node id>
owner=finpred.core@1
handler=<versioned operation>
kind=<result kind>
left=<left parent digest>
right=<right parent digest>
value=<decimal>
```

`automat.dag_replay.verify(plan, mode, budget, first, second, artifacts,
output_digest)` recomputes the graph and compares the complete ordered
evidence and output selection. A node digest identifies that node and its
transitive inputs, **not** the entire plan: independent branches may leave
it unchanged. Verification needs the original plan and input values; it
does not read files or create a store.

### Frozen runs

`automat.scalar_manifest.freeze(plan, mode, budget, first, second)` accepts
a host budget of 1–16. Success returns `status="ok"`, the manifest bytes,
their BLAKE3 `run_id`, and the ordered artifact pairs. Failure returns a
status with nil manifest, run ID and artifacts.

`automat.scalar_verify.verify(run_id, manifest, artifacts)` takes a
separately expected run ID and the frozen evidence. It checks the manifest
identity, reconstructs the plan and inputs, and verifies the selected output
and all intermediate artifacts. It does not need live input paths, a
preconstructed graph, or write access. The calling host owns any files.
`automat.scalar_decode.decode` alone checks the wire grammar. Its `valid`
flag is not a verification result: a well-formed declaration can still
name an unknown handler, contain a cycle, or disagree with the supplied
evidence.

The [scalar manifest](../../docs/RUN_FORMAT.md#scalar-run1-native-analysis) binds
the whole declaration order, budget, inputs, selected output, and execution
evidence. Two runs may have the same node output digest but distinct run IDs.
For example, a different valid budget changes the run ID without changing
the calculation. A v2 plan freezes as
[`scalar-run@2`](../../docs/RUN_FORMAT.md#scalar-run2-typed-selection).

### Reusing pure results within a run

`automat.dag.run_memoized` accepts the same arguments as `run`. It starts
with an empty table and can skip a handler call if an earlier node used the
same engine, owner, versioned handler, result kind, and **ordered parent
artifact digests**. Matching numeric inputs alone is insufficient. For
example, two `maximum@1(first,second)` nodes share a calculation; swapping
`first` and `second` requires another call, even for this commutative operation.

Each declaration still uses one unit of the host budget and produces its own
trace row and node artifact. `Outcome.invocations` counts actual handler calls;
`Outcome.memo_hits` counts avoided calls. Their sum is the number of declarations
on success, and both are zero on a planning rejection. These counts are
diagnostics, not part of the frozen evidence.
Internally, the lookup uses On1x `Option<i64>`: `Some(0)` is a valid hit
and `None()` is the only miss.

`automat.scalar_manifest.freeze_memoized` produces the same scalar manifest
bytes and run ID as `freeze`. Verification continues to recompute with
the uncached runner; it does not need a memo table from the producer.
For selection nodes, the memo key includes all three parent digests in
role order, including the unselected branch.
