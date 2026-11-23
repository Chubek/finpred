# Ottomat recommendation declarations

The CLI uses the legacy recommendation grammar below. Native hosts can
use [v3 scalar analysis](#v3-scalar-analysis) or
[v4 scalar selection](#v4-scalar-selection).

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
filesystem API.

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
Yieldcraft recommendation profile.
