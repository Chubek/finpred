# Native scalar analysis graphs

`automat.dag` is a native On1x entry point alongside the fixed Yieldcraft
runner. See the [compiled consumer](../../tests/dag_consumer/main.on1x).
To compile a host directly, add both `source/` and the repository root to
its module search paths so the statically registered packages are available.
Hosts can freeze and verify this IR through the module APIs below, or lower
an [Ottomat scalar program](../ottomat/README.md#v3-scalar-analysis) to the same
plan. The CLI still uses the legacy Yieldcraft graph.

`Plan` identifies a version (`automat.scalar-dag@1`, `@2`, or `@3`), a declaration
list, and an output node by name. `node(id, handler, left, right)` binds both required ports to
the single result of another declaration or to a graph input (`first` or
`second`). Forward references are valid. IDs are 1–32 lowercase ASCII letters;
they must be unique and cannot shadow the inputs. Every declared node runs,
including nodes outside the selected output's dependencies.

`run(plan, "analysis", budget, first, second)` accepts immutable integer
levels in `[0, 10^12]`. These are unitless diagnostic values, not prices.
The host registry defines both input ports as `scalar.level@1`.
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

V3 also admits the statically linked `midpoint@1` binary handler, owned
by [`scalar-diagnostics@1`](../../plugins/scalar_diagnostics/README.md).
The versioned registry is shared by native planning, invocation and DSL import
resolution. The scalar plan never gains capabilities from an import line.

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
