# CaravanScript: offline coverage transformations

Add an optional top-level `transform` block to a
[CaravanScript](contracts.md) script to derive metrics in `report`. No header
or version declaration is needed. The block does not change what `plan`
includes, how observations are matched, or how freshness is computed:

```text
transform {
  emit requires_attention = remaining(status_count("pending"), status_count("failed")) > 0;
  emit fresh_cells = freshness_count("fresh");
  emit label = "Riviera coverage";

  fn remaining(waiting: int, failed: int) -> int {
    return waiting + failed;
  }
}
```

## Declarations and types

```ebnf
transform = "transform", "{", (function | metric)+, "}" ;
function  = "fn", identifier, "(", [ param, { ",", param } ], ")", "->", type,
            "{", "return", expression, ";", "}" ;
param     = identifier, ":", type ;
type      = "int" | "bool" | "text" ;
metric    = "emit", identifier, "=", expression, ";" ;
```

A block must emit at least one metric. Function definitions may appear
before or after calls to them, including calls in another function. A
function takes typed positional parameters and returns one expression.
Functions cannot recurse, directly or indirectly. Only parameters are
visible as variables; metric names are output keys and cannot be read by
expressions. Function names, parameter names in the same function, and
metric names must each be unique within their respective namespaces.
Functions may not redefine a built-in. The words `fn`, `emit`, `return`,
`int`, `bool`, `text`, `true`, `false`, `and`, `or`, and `not` are reserved
inside the transformation block.

Values are signed 64-bit integers, booleans, and JSON-style quoted text.
Unsigned integer literals may not exceed `9223372036854775807`; the minimum
value can be expressed as `-9223372036854775807 - 1`. No implicit conversions
are performed. Operators in decreasing precedence:

| Operations | Inputs | Result |
| --- | --- | --- |
| Literals, parameters, `f(...)`, `(expression)` | As declared | Expression type |
| Unary `-`, `not` | `int`, `bool` respectively | Same type |
| `*` | Two `int`s | `int` |
| `+`, `-` | Two `int`s | `int` |
| `<`, `<=`, `>`, `>=` | Two `int`s | `bool` |
| `==`, `!=` | Two operands of the same type | `bool` |
| `and`, then `or` | Two `bool`s | `bool` |

Binary operators associate left to right. Repeated relational or equality
operators at the same precedence require parentheses. `and` skips its right
operand if the left is false; `or` skips it if the left is true. Text equality
is exact; the evaluator does not fold case or normalize Unicode.

## Authorized input

Expressions can read only counts computed from the validated, as-of coverage
rows. They cannot see prices, guest identities, property IDs, credentials,
files, clocks, network services, or plugin calls.

| Built-in | Result |
| --- | --- |
| `total_cells()` | Number of expected cells |
| `status_count(status)` | Cells with the given status |
| `freshness_count(freshness)` | Cells with the given freshness |
| `source_count(source)` | Cells for one provider |
| `source_status_count(source, status)` | Cells for one provider and status |

Each built-in argument is `text`; every built-in result is `int`. Sources are
`booking` and `agoda`. Statuses are `pending`, `priced`, `unavailable`,
`unsupported`, and `failed`. Freshness values are `fresh`, `stale`, and `none`.
Counts include unsupported cells when they match the selector. A known label
absent from the matrix returns zero; an unknown label evaluated at runtime is
an error.

## Validation, limits, and replay

Both `plan` and `report` parse and type-check the whole block, including
unused functions. Only `report` evaluates it. Limits are 64 functions,
64 metrics, 16 parameters or arguments per call, 4,096 expression nodes per
program, 64 levels in the expression tree, and 4,096 UTF-8 bytes per text
literal. The parser also caps nesting (including parentheses) at 128 levels.
Report evaluation can visit up to 10,000 expression nodes across all metrics;
each visit counts, including repeat calls. Overflow, invalid selectors,
invalid types, recursion, and budget exhaustion fail the command; `report`
emits no partial JSON.

Those are language limits, not limits on the size of the collection matrix
or the observation log. The host still validates the input and folds coverage
before the transformation runs.

`report` adds a `transformation` member without altering the base coverage:

```json
{
  "kind": "caravansary.transformation@1",
  "program_digest": "<SHA-256 of the parsed transform AST>",
  "base_report_digest": "<SHA-256 of the coverage report without this member>",
  "metrics": {"has_fresh_evidence": false}
}
```

Both hashes use the CLI's compact, key-sorted JSON serialization with ASCII
escaping and no trailing newline. The program hash binds parsed declarations,
including their order within the function and metric lists, rather than
comments or whitespace. The hashes identify inputs; they do not authenticate
observations. Adding, removing, or editing a transformation leaves cell keys
unchanged, so the same host-approved observation log can be replayed. Scripts
without the block produce the base coverage report with no `transformation`
member.

Run the [Riviera metrics example](examples/riviera-metrics.crs):

```sh
python3 plugins/caravansary/caravansary.py report \
  docs/caravansary/examples/riviera-metrics.crs --as-of 2026-11-26T12:00:00Z
```

The example emits 8,760 expected cells, zero eligible cells, 4,380 unsupported
Booking cells, and `has_fresh_evidence: false`. The properties are fictional
and have no verified mappings. No provider is queried.
