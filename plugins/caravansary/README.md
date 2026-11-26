# Caravansary: offline competitor coverage

Caravansary validates [CaravanScript v1](../../docs/caravansary/contracts.md),
plans a competitor matrix, and reports freshness from an offline observation
log. It is a standalone Python 3.10+ tool (stdlib and system IANA timezone data),
not a FinPRED SDK-registered plugin. It makes no pricing recommendations.

## Run the offline example

```sh
script=docs/caravansary/examples/riviera.crs
python3 plugins/caravansary/caravansary.py plan "$script" --date 2026-11-26 > matrix.jsonl
python3 plugins/caravansary/caravansary.py report "$script" --as-of 2026-11-26T12:00:00Z > coverage.json
make caravansary-test
```

The sample has 8,760 cells: two sources × two properties × 365 check-in dates
× two guest configurations × three stays. Every mapping is fictional and
missing, so every cell is `unsupported` with reason `mapping_missing`. A
verified mapping is initially `pending`, not an available quote.

`plan` streams one initial cell per JSONL line. `report` emits one
`caravansary.coverage@1` report with every cell, independent status and
freshness, and per-source capacity estimates. To fold a frozen log, pass
`report ... --observations /path/to/observation-log.jsonl`. A log may be sparse,
but its records must refer to the selected matrix. Filter any authorized
historical archive separately.
`report` holds the matrix in memory.

`--as-of` fixes the UTC clock for replay and for resolving `today`; `--date`
overrides only the `today` anchor, not a fixed date in a script. Without an
override, a run captures the clock once and resolves `today` in the property's
IANA timezone. Checkout is calendar-based and may pass the horizon. Cell keys
are deterministic SHA-256 identifiers over acquisition config, source,
competitor, check-in/checkout and the guest ID bound to its complete allocated
party by the config. The config identity is insensitive to rolling dates,
output paths, credential declarations and scheduling budget/weight changes;
resulting digests are identifiers, not a proof of provenance. A future
adapter whose queries depend on account-specific rates will need to bind
that context with a non-secret identity.

The host selects the script directory and may explicitly grant additional
input roots via `--input-root`. Competitor and weight paths resolve relative to
the script directory. Use a trusted, stable input tree; this is not an OS
sandbox. The CLI writes only to stdout; it never opens the script's output
paths or loads credentials. Keep secret or credential-bearing URLs out of
competitor and observation data.

## Host integration

Import `plugins.caravansary.caravansary` from the repository root. `parse(text)`
validates the script (including the structure of BCP 47 locale tags, not
membership in the complete language subtag registry).
`plan(path, on_date=None, *, now=None, input_roots=())`
returns an iterator; `load_plan(...)` additionally returns the parsed config.
Treat returned config and cell dictionaries as read-only. The host can combine
`coverage(...)` with the in-memory `Scheduler`; there is no daemon, shared
request quota, network adapter, or historical store.

The scheduler estimates capacity assuming one attempt per complete cell,
excluding retries, pagination, latencies and failures. Satisfying its budget
condition is not proof that the target is achievable. Already unsupported cells
are counted in coverage but never scheduled.

Use `Scheduler(config["refresh"], config["sources"])` for a single serially
managed, in-memory queue. `schedule(report["cells"], now=clock)` returns due
rows with a `reservation_id`; call
`finish(id, now=clock, success=..., retryable=...)` to release each. Reservations
count immediately against per-source concurrency and trailing-hour budget,
even if not dispatched. Weighted work shares the queue with a least recently
served slot (every fourth reservation by default) that includes zero-weight
cells. Retries are bounded and consume the same budget. Use nondecreasing
aware clocks; enforce actual request-time quotas independently of this queue.

An observation binds the exact `cell_key`, `provider_property_id` and
`request_context` from the plan. Include receipt and ingestion UTC timestamps,
adapter/extractor versions, completeness, outcome and offers. An
`unavailable` record requires `complete: true`, `authoritative: true` and an
empty offer list. A failure can be the latest attempt without replacing the
latest complete success. Results ingested after the report clock do not take
effect; freshness expires at receipt plus `max_age_seconds`. See the
[observation and offer shape](caravansary_core/coverage.py) and
[synthetic replay test](../../tests/check_caravansary_cli.py) for details.

## Credential sources (host only)

The optional `credentials` block extends the draft syntax. A selected provider
may declare one credential source. For example:

```text
credentials {
  booking { cookies = "booking-cookies.json"; }
  agoda { environment = ["AGODA_SITE_ID", "AGODA_API_KEY"]; dotenv = ".env"; }
}
```

To supply values explicitly, use a declaration such as
`agoda { explicit = ["site_id", "api_key"]; }` instead, and pass the values from
the host rather than as CaravanScript literals or command-line arguments.
A declaration cannot grant file access, read the process environment
automatically, or authorize requests. Credential keys, paths, and values
are not part of a matrix or coverage report.

Call `resolve_credentials(config, source, *, environ=None, explicit=None,
approved_files=None)` from the host. Pass only the environment names and
values approved for that provider, not the full process environment.
`explicit` maps the declared reference names to host-supplied values.
For a cookie or dotenv declaration, `approved_files` maps
`(source, "cookies" or "dotenv", exact_declared_path)` to independently
approved bytes (at most 64 KiB per file). The resolver does no file reads.
Dotenv accepts line-based UTF-8 `NAME=value` assignments with optional
`export`, comments, and single- or double-quoted values, but no expansion.
Host-supplied environment values take precedence over dotenv.
An undeclared selected provider returns `None`; otherwise the result exposes
`.mode`, `.values` and `.cookies`. Its representation redacts secrets, but
callers must not print, serialize, or store the resolved values.

Cookie input uses the repository's
[MuLIB ElviScript Cookie JSON v1](../../third_party/mulib/manual/elvi-script-transport.md#cookie-json-v1)
format, bound to `booking.com` or `www.agoda.com` respectively. It is not a
general browser-export format, and no separate “MILK” format was identified in
the repository. Keep cookie and `.env` files private, out of source control,
and outside planner input roots and observation archives.

## What still requires a live pilot

There is no Booking.com or Agoda.com network adapter in this plugin.
Credentials and verified mappings do not grant permission to collect or retain
data. Written permission, representative property IDs, approved budgets,
permitted retention and the [measured pilot](../../docs/caravansary/feasibility.md)
remain required. No provider was contacted, and there is no appraised price,
Yieldcraft handoff, or transformation language in this version. The host must
enforce capture permission, retention expiry and provider-specific query
restrictions before any future collection.
