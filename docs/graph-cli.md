# Validate and inspect a financial graph

Build the CLI with `bin/build.sh`, then run:

```sh
bin/finpred graph validate tests/ottomat_financial_consumer/hospitality.ottomat
bin/finpred graph inspect tests/ottomat_financial_consumer/hospitality.ottomat
```

The separate `finpred-graph` host is currently included in source builds,
not the pre-existing binary release archive inventory.

These are static checks for Ottomat 6 and 7. The source must start with an
exact `ottomat 6` or `ottomat 7` header followed by LF. The host reads only a
regular file (no final symlink, directory, FIFO, or stdin), up to 4,096 bytes
of printable ASCII and LF. Ottomat also limits the source to 96 lines; v7
requires two to four fragments. Relative paths are relative to the caller.

The fixed profile `finpred.hospitality-graph-check@1` uses Yieldcraft's
existing hospitality descriptor lookup, `recommendation` mode, `pure` effect,
and a 1,000,004-work-unit ceiling. A caller cannot supply a resolver, mode,
budget, compiler identity, or plugin. The host links no dispatch callback and
does not invoke handlers, read their input data, create a store, or replay an
archive. A successful report does not grant permission to run or publish.

## Reading the JSON report

Both commands print one `finpred-graph-check@1` JSON object. On success
(exit 0), the report contains:

- `source_digest`: BLAKE3 of the exact declaration bytes read.
- `graph_digest`: BLAKE3 of Automat's canonical graph, including typed
  connections and resolved descriptor pins. Equivalent validated
  declarations can share this digest even when their source bytes differ.
- `compiler_identity`: SHA-256 of the On1x compiler used by the build;
  `lowering` names the selected Ottomat frontend. Neither field is a
  signature or an archived execution identity.
- `bounds`: worst-case declared work, graph budget, operand edge count,
  dependency depth, and sums of declared byte caps for roots, operand
  reads, and handler outputs. Each read binding is charged separately;
  these are static bounds, not runtime measurements.

`inspect` additionally lists typed inputs and exports in name order, and
nodes in canonical dependency order with their full descriptor pins, output
ports and input bindings. A binding with a null `from.node` reads a graph
input. Ottomat 7 reports the flattened graph, including its exposed exports.

Rejections exit 1 with a `status` and `diagnostic` but no partial graph or
hashes. Line and column are one-based (0 when unavailable), and `byte_range`
is zero-based and half-open when supplied by the frontend or input preflight.
`ottomat_version` is 0 when no supported header was identified.
`fragment` and `subject` may be empty. CLI misuse or a missing host exits 2
with a launcher error on stderr.

The dedicated integration check is `python3 tests/check_graph_cli.py` after
building the CLI.
