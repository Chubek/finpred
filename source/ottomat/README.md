# Ottomat recommendation declarations

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
24 accepted encodings, and 47 malformed, ill-typed, or unauthorized
declarations. A second build substitutes a test graph to confirm that an
unchanged valid declaration is rejected if the root input, strategy effect,
output effect, or Automat admission decision changes incompatibly.
With the pinned MuLIB checkout, `./bin/build.sh` and
`./tests/run.sh` also passed in an isolated project copy, including the
frozen v1 replays, v2 run/recommendation/trace digests, and all five named
pricing profiles. The two default fixture recommendations remain 17100 and
16000 EUR cents per night with `published=false`.
