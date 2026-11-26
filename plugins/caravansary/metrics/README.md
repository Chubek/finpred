# Native CaravanScript metrics

`plugins.caravansary.metrics.transform` has four host entry points:

- `compile_transform(ast_json)` checks the Python-shaped transform AST and
  returns `(error, program)`. Call it before planning, including for `plan`.
- `evaluate_report(program, base_report)` returns `(error, metrics_json)`.
  Pass the validated `planning.json` report tree: tagged object and array lists,
  and decoded strings as S-expression string atoms. The evaluator reads
  only `cells[*].source`, `status`, and `freshness`.
- `evaluate_counts(program, counts)` returns the same tuple without walking a
  report. For a host that already visits every cell, initialize with
  `counters.empty()`, resolve decoded labels with `counters.label(value,
  field, false)`, and fold them into the tally with `counters.increment()`.
- `evaluate(program, base_report_json)` accepts the same report serialized as
  JSON. This is useful for standalone fixtures; a host that already has a
  report tree should use `evaluate_report` to avoid another JSON scan.

Empty error strings signal success. A program is immutable and must come from
a successful compile. The returned metrics object preserves declaration order;
the CLI owns canonical report serialization, digests, and I/O.

The checker enforces the Python function/metric, arity, depth, node, and
literal limits, including unreachable declarations. The evaluator maintains a
shared 10,000-node budget, uses explicit continuations, and checks signed
64-bit intermediates. Source, status, and freshness are exact labels.

The serialized boundary rejects malformed UTF-8 and duplicate AST keys.
Its JSON adapter caps nesting at 140 levels and kept containers at 4,096 items,
independently of the lower language limits. Unknown report fields are skipped;
duplicate recognized fields are rejected. Text values compare by exact
Unicode scalars (no normalization); JSON escape spelling can differ from
Python's and the report host canonicalizes independently. This standalone
boundary preserves escaped NUL, but any caller converting to decoded On1x
`string` values is subject to the C-string ABI's NUL restriction.

## Focused native checks

From the repository root (after building MuLIB):

```sh
mkdir -p build/tmp
TMPDIR="$PWD/build/tmp" PYTHONDONTWRITEBYTECODE=1 \
  python3 third_party/mulib/on1x/tools/on1x-build.py \
  plugins/caravansary/metrics/test_transform.on1x \
  --backend c11 --on1xc "$PWD/build/mulib/on1x/on1xc" \
  --mulib-root "$PWD/third_party/mulib" -I "$PWD" --stdppx checks \
  --cflag=-DON1X_DATA_MAX_TEXT=33554432u \
  --cflag=-DON1X_DATA_MAX_POOL=268435456u \
  -o "$PWD/build/tmp/caravansary-metrics-test"
build/tmp/caravansary-metrics-test
```

The test uses the shipped `checks` PPX for exact assertions. The production
CLI has no PPX carriers; the full compilation unit is too large for the v1
PPX wire, so the processor is scoped to this focused test build.
To compare a saved fixture, pass two files to the test binary:
`caravansary-metrics-test AST.json BASE_REPORT.json`.
