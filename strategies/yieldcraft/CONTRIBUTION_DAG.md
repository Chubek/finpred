# Yieldcraft contribution in a financial graph

`yieldcraft.contribution_dag` is a library adapter for
`automat.financial_graph`, not a CLI route. Its `graph()` is a one-node
example; a trusted native host can also bind `yieldcraft.optimize-contribution@1`
in a larger `recommendation` graph. The adapter calls the existing
`yieldcraft.contribution@1` optimizer. Neither the legacy strategy declaration
nor `finpred-run@3` is used or changed.

The host supplies a resolver that calls `descriptor(handler, code_digest)`
and a dispatcher that calls `invoke(code_digest, pin, request)` with the
same host-selected identity. Use a digest for the exact code subject the host
trusts. The adapter verifies the pin against that supplied digest and its
own versioned policy text, but does not compute or authenticate a digest of
the linked executable. The operation is pure, requests no capabilities,
and charges one graph work unit for bounded input; this is not CPU metering.

## Frozen input contracts

All ports are version 1, EUR, and accept only SDK state `available`.

| Port | Kind | Unit | Maximum bytes | Payload |
| --- | --- | --- | ---: | --- |
| `scenario` | `finpred.scenario-csv` | `none` | 2048 | Existing scenario header and one data row |
| `valuation` | `finpred.valuation-csv` | `minor_per_night` | 2048 | Existing valuation header and one data row |
| `demand` | `pricing.demand` | `room_night` | 8192 | Existing `pricing.demand@1` CSV, with 2–64 price estimates |

The adapter checks bounded printable unquoted ASCII CSV (LF or CRLF) and
canonical unsigned decimal numbers before using the legacy validators.
The graph cutoff must equal `scenario.decision_at`. Scenario, valuation, and
demand chronology, demand age and method, and price grid constraints are all
checked. Demand must name the BLAKE3 digest of the exact scenario bytes, not
a reserialization. A well-formed external evidence digest remains a
reference: the adapter does not fetch it, prove who supplied it, or
authenticate the expected demand.

A conflicting valuation, a grid with no feasible estimate, and a grid with
no positive feasible contribution produce no recommendation. Like malformed
semantic inputs, these return `handler_failure` to Automat rather than
terminating the host. Root bounds and graph admission failures retain
Automat's own status codes.

## Output and verification

The `decision` port emits `pricing.contribution-decision-text@1`, a bounded
LF-terminated text record. It carries the selected price, cost, expected
room nights and contribution, fixed-point scale, feasible interval, demand
method, provenance reference and timestamps, and one `candidate=` line per
grid point with its exact score and feasibility. It is always unpublished.
This format is distinct from the CLI JSON contract
`pricing.contribution-recommendation@1`. Automat records the three exact
input artifacts as named parents of the decision, and can replay in memory
against the expected graph digest and artifact bytes. It writes no store.

Run `TMPDIR="$PWD/build/tmp" python3 -B tests/check_contribution_dag.py` with
the built toolchain and an existing `build/tmp` directory. The independent
consumer compares output byte for byte to the current optimizer and checks
the optimum and candidate scores with a separate oracle, including
guardrails, both tie-breaks, bounded arithmetic, replay and rejected inputs.
