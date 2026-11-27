# Ottomat recommendation declarations

The CLI's default legacy engine uses the recommendation grammar below.
Native hosts and `run --engine scalar` can use
[v3 scalar analysis](#v3-scalar-analysis),
[v4 scalar selection](#v4-scalar-selection), or
[v5 registered scalar algorithms](#v5-registered-scalar-algorithms).

Both dialect families use [embedded grammars](grammar.on1x) compiled by
On1x `stdppx/grammarembed` (DFA lexer and LALR(1) parser). GrammarEmbed is
a build-time processor; the finished program parses strategy bytes in On1x
and does not launch a processor or read grammar files at runtime.
Lowering separately checks the fixed graph, registered handler signatures,
effects, and resource bounds. The scalar preflight preserves the existing
source limits and exact whitespace diagnostics.

## V6 financial graphs

`ottomat 6` is a separate, additive [GrammarEmbed frontend](financial_grammar.on1x)
for the [native financial graph](../automat/README.md#typed-financial-graph).
It accepts ASCII with exactly one space between tokens and LF-terminated
lines; no comments, blank lines, or dynamic expressions. A source must
declare `effect pure`, named inputs, exact registered imports, named-port
`let` bindings, typed outputs, and corresponding `emit` lines, in that order.
Input and output declarations use `name kind@major unit currency required
max_bytes`. A reference names an external input or `node.output_port`; a
binding names `input_port=reference`. See the
[hospitality fixture](../../tests/ottomat_financial_consumer/hospitality.ottomat).

Lowering returns the native graph with its canonical digest, declaration
byte spans, resolved pins, exact original source and its digest, compiler
identity supplied by the trusted host, and lowering version. Source and
graph identities are separate: for example, argument reordering can preserve
the graph digest while changing the source digest. Any non-pure declaration
is denied.
The frontend does not execute the graph and does not alter dialects 1–5.
A trusted host can pass a successful `Lowered` to `ottomat.financial_run.execute`
with its own inputs, context, budget, resolver and invoker. The bridge
rechecks the canonical graph digest before dispatch and rejects a changed
valid binding as `graph_mismatch`. The digest is not an authorization token;
the host still controls the linked handlers.
`ottomat.financial_run.capture` additionally binds the exact strategy
source and host-supplied compiler identity to an `ottomat.financial-replay@1`
bundle. Replay requires the trusted bundle digest and independently approved
compiler identity, re-lowers the frozen source, and then replays the native
evidence. The bundle cannot choose or load a compiler or grant execution.
Run `python3 tests/check_ottomat_financial.py` for compiled native parity and
negative syntax, type, import, and effect cases.

## V7 financial composition

`ottomat 7` assembles two to four named fragments into one native financial
graph. Like v6, it requires `effect pure`, exactly one ASCII space between
tokens, and LF after every line. Sources are limited to 4096 bytes and 96
lines. Each fragment uses the v6 `input`, `import`, `let`, `output`, and
`emit` declarations in that order, followed by its `wire` declarations and
`end`:

```text
ottomat 7
effect pure
fragment prepare
input raw example.value@1 none none required 64
import example.prepare@1
let prepared = example.prepare@1 value=raw
output normalized example.value@1 none none required 64
emit normalized prepared.value
end
fragment review
input inbound example.value@1 none none required 64
import example.review@1
let reviewed = example.review@1 value=inbound
output decision example.value@1 none none required 64
emit decision reviewed.value
wire inbound normalized
end
```

`wire <root> <export>` consumes a root in the current fragment and connects
it to an export from any earlier fragment. The first fragment has no wires;
each later fragment needs at least one. Each root can be wired at most once.
Every fragment must be valid on its own, and the declared export must match
the declared root type, including byte limits. Native composition removes
wired roots, retains all exports, and checks the merged graph against the
same host budget and resolver. Names are neither qualified nor silently
merged in the native graph; fragment names are source provenance only.

`ottomat.financial_composition.lower(source, mode, budget, compiler, resolve)`
returns the native graph, separate graph and source digests, the exact source,
compiler identity, resolved handler pins, and the lowering identity
`finpred.ottomat-financial-composition@1`. Its `spans` are
`(fragment verb name start end)` entries in source order, including the
header, effect, and fragment delimiters. Byte ranges are zero-based and
half-open, excluding LF. Errors return no graph identity or partial
provenance; `diagnostic` contains a status, optional fragment and subject,
one-based line and byte column, and the same half-open byte range convention.
If the native validator cannot identify a unique declaration, the error
points to the fragment header.

A trusted host can use `ottomat.financial_composition_run.execute` to
recheck the canonical graph digest before dispatch. V7 has no Ottomat
archive entry point and does not alter v6 lowering or replay. Run
`python3 tests/check_ottomat_composition.py` for native graph and execution
parity, source spans, wiring failures, and the binding recheck.

## Legacy recommendation declarations

`Ottomat.lower(source)` parses a v1 or v2 declaration and resolves it to
Automat's fixed seven-node recommendation plan. A valid `Plan` carries
`syntax_version`, `graph` (the identity from `Graph.version()`), and
`profile`. Nodes are the native `Graph.node(0)` through `Graph.node(6)` in
order; the frontend does not construct a second execution graph.
On failure the version is `0` and both text atoms are empty. The existing
`Ottomat.profile(source)` and `Ottomat.checked_strategy(source)` return the
profile name or `""`, and its validity as a boolean, respectively.

## Grammar

The following notation uses quoted ASCII literals, `SP` for **one** ASCII
space, `EOL` for LF or CRLF (chosen per line), and `[]` for optional syntax.
EOF must follow the declaration.

```text
v1       = header SP "1" EOL nodes [EOL] EOF
v2       = header SP "2" EOL nodes EOL policy [EOL] EOF
header   = "ottmat" | "ottomat"
nodes    = node EOL node EOL node EOL node EOL node EOL node EOL node
node     = word SP contract
contract = word "." word "@" number
policy   = "profile" SP word "@" number SP ("target_bps" SP number | "curve" SP word)
word     = [a-z][a-z0-9_-]{0,31}                (regular expression)
number   = 0 | [1-9][0-9]*                      (decimal, at most 10000)
```

The parser consumes at most 512 bytes, exactly seven node declarations,
and zero (v1) or one (v2) profile. It does not skip whitespace: tabs,
indentation, trailing spaces, blank lines, and bare CR are errors. Numbers
are unsigned canonical decimals. Contract and named policy versions must
be `1`. The parser uses byte offsets and bounded integer arithmetic; it has
no recursion, imported code, expressions, or user-controlled iteration.

## Type, effect, and policy checks

Each declaration must resolve to the native node at its ordinal and name its
exact output contract. That node's input must match the preceding *declared*
output (or `none` for the first node). Effects come from Automat. The
frontend checks them by family:

| Family, in graph order | Admitted effect |
| --- | --- |
| `input`, `source` | `read` |
| `transform`, `algorithm`, `strategy`, `gate` | `pure` |
| `output` | `record` |

External actions and unknown families or effects cannot be admitted by this
grammar. The resolved plan must also pass `Graph.validate("recommendation")`.
Lowering itself reads no files and grants no capabilities.

V1 selects `scenario`. V2 admits these exact typed name/argument pairs:

| Profile name (`@1`) | Operator | Value |
| --- | --- | --- |
| `value-p40` | `target_bps` | `4000` |
| `balanced-p55` | `target_bps` | `5500` |
| `premium-p75` | `target_bps` | `7500` |
| `lead-linear` | `curve` | `linear` |
| `lead-quadratic` | `curve` | `quadratic` |

The frontend does not normalize the strategy bytes used for persistence.
For example, an LF and CRLF file can select the same plan but still have
different BLAKE3 identities. See [strategy outcomes](../../strategies/README.md).

## Verification

`python3 tests/check_ottomat_plan.py` builds an independent On1x C11
consumer. It checks the graph identity and syntax version, the legacy APIs,
48 accepted encodings, and 50 malformed, ill-typed, or unauthorized
declarations (including a v3 file). A second build substitutes a test graph
to confirm that an unchanged valid declaration is rejected if the root input, strategy effect,
output effect, or Automat admission decision changes incompatibly.
With the pinned MuLIB checkout, `./bin/build.sh` and
`./tests/run.sh` also passed in an isolated project copy, including the
frozen v1 replays, v2 run/recommendation/trace digests, and all five named
pricing profiles. The two default fixture recommendations remain 17100 and
16000 EUR cents per night with `published=false`.

## V3 scalar analysis

[`strategies/scalar-spread.ottomat`](../../strategies/scalar-spread.ottomat)
computes the distance between two independent scalar algorithms' outputs.
The native host supplies the input values, execution mode and node budget.
The file cannot authorize execution, read files, or invoke a handler not
registered by the host.

```text
ottomat 3
input first scalar.level@1
input second scalar.level@1
effect pure
import maximum@1
import minimum@1
import distance@1
let spread = distance@1 hi lo
let hi = maximum@1 first second
let lo = minimum@1 first second
emit spread
```

The four header lines are fixed. Declare 1–16 unique registered handler
imports, then 1–16 node declarations, then one `emit`. Each call needs a
preceding import; unused imports are allowed. Each node binds two required
ports. IDs contain 1–32 lowercase ASCII letters. Forward node references
are permitted, but cycles and incompatible ports are rejected. V3 uses one
ASCII space between tokens, LF after every line, and no comments or blank
lines. The scanner limits source to 4096 bytes, 37 lines, six tokens per
line, and 64 bytes per token.

`ottomat.scalar.lower(source, mode, budget)` returns a native
`automat.dag.Plan` only on success; it validates without executing handlers.
Lexical errors identify a byte line and column, grammar errors point to the
offending line, and graph validation errors point to `emit`. Coordinates are
one-based on source errors.

`ottomat.scalar_run.freeze(source, mode, budget, first, second)` invokes the
native scalar manifest writer with its 1–16 budget range and 0–10¹² input
range. It returns the canonical scalar snapshot plus
the exact source's BLAKE3 digest and the lowering identity
`ottomat.scalar-lowering@1`. Source provenance is separate from the scalar run
ID: reordering imports alone leaves the native plan and snapshot identical.
The manifest pins operations through their versioned handler identities.
Neither entry point modifies the CLI recommendation path or provides a
filesystem API. The scalar CLI lowers and executes the plan for display;
it does not call the manifest writer.

## V4 scalar selection

[`strategies/scalar-select.ottomat`](../../strategies/scalar-select.ottomat)
uses the same grammar with `ottomat 4` and an additional registered handler:

```text
import select@1
let picked = select@1 spread hi lo
```

The three bindings are `condition`, `positive`, and `zero`, in that order.
The condition must be a `scalar.distance@1`; both branch values must be
`scalar.level@1`. A positive distance selects the positive binding; zero
selects the zero binding. The output is a `scalar.level@1`. All referenced
nodes execute regardless of the selection, so both branches are validated,
counted against budget, and included in evidence. This is value selection,
not lazy execution or a way to gate effects.

V4 permits up to seven tokens per line for the three-binding call. Other
source bounds and diagnostic rules stay the same. It lowers to
`automat.scalar-dag@2`, freezes as `scalar-run@2`, and reports
`ottomat.scalar-lowering@2`. V3 does not admit `select@1`, and v4 is not a
fixed recommendation profile.

## V5 registered scalar algorithms

V5 uses the v4 grammar with `ottomat 5` and allows hosts to supply additional
binary operations. Pass a trusted binding to `lower_with` to validate the
imports, or to `scalar_run.freeze_with` to use that binding for both lowering
and execution. The built-in-only `lower` and `freeze` do not see host bindings.
The operation and owner identities appear in the node artifact. The mode,
effect and resource limits remain unchanged.

V5 lowers to `automat.scalar-dag@3`, freezes as `scalar-run@3`, and
reports `ottomat.scalar-lowering@3`. An older profile does not admit the
new handler, even as an unused import. This is static host linking, not
dynamic SDK discovery or invocation.
