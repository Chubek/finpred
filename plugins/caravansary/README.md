# Caravansary: competitor coverage

Caravansary validates [CaravanScript](../../docs/caravansary/contracts.md),
plans a competitor matrix, and reports freshness from an offline observation
log. An optional block adds [typed coverage metrics](../../docs/caravansary/transformations.md).
The standalone On1x CLI is not a FinPRED SDK-registered plugin. It uses the
system IANA timezone data and makes no pricing recommendations. Planning and
reporting are offline; the explicitly authorized Booking sandbox command is
the only network path.

The build needs the pinned On1x C11 toolchain, OpenSSL development headers
for SHA-256 replay identities, and libcurl ≥ 7.85 for the sandbox transport.
The [CaravanScript frontend](frontend/README.md) documents how to regenerate
the `std.llsynth` grammar tables. The
[metrics tests](metrics/README.md#focused-native-checks) use the standard
`checks` PPX for exact compile/evaluation assertions.

The additive [market workflow](../../docs/caravansary/market.md) keeps
provider extraction, candidate identity, comparable evidence, independent
pricing, and scheduling as separate authority boundaries.

## Run the market examples

Build the pinned compiler first (see [INSTALL.md](../../INSTALL.md)), then
run:

```sh
CC=clang CXX=clang++ make caravansary
examples=plugins/caravansary/examples
script="$examples/workflows/canal-market.caf"
grants="$examples/workflows/host-grants.json"
bin/caravansary discover "$script" --input-root "$examples" \
  --host-grants "$grants" --as-of 2026-11-26T10:00:00Z
bin/caravansary predict "$script" --input-root "$examples" \
  --host-grants "$grants" --as-of 2026-11-26T10:00:00Z \
  --pricing-input "$examples/workflows/pricing-input.json"
make caravansary-market-test
```

These commands replay fictional Booking and Agoda HTML through native Probe.
The second command uses separately supplied exact-stay evidence; omitting
`--pricing-input` yields an abstention, not a price inferred from the page.
`market-help` lists `scrape`, `collect`, `backtest`, `history`, and `explain`
alongside `discover` and `predict`. They return versioned JSON, and market
artifacts are explicitly not for publication.

Other examples: [typed functions](examples/programming/README.md),
[provider capture fixtures](examples/providers/README.md),
[Joe Litty Rooms profile reference](examples/joe-litty-rooms/README.md), and
[persistent scheduled Probe replay](examples/jobs/README.md). See the
[jobs contract](jobs/README.md) for state ownership, clock and crash semantics.
`daemon --state DIR --at UTC --once` supervises one due job; it is not a
long-running background daemon. `schedule` takes the same profile and clock
arguments as `jobs --state DIR schedule`. Deploy the fixed market and jobs
sibling executables together in a trusted directory.

CaravanScript files contain top-level fields and blocks, with no header or
version declaration. To migrate an older script, replace its opening
`caravan "Title" version … {` line with `name = "Title";` and remove the
matching outer `}`. Keeping the title preserves cell keys for replay.
New scripts may omit `name`.

## Run the offline example

```sh
make caravansary                  # after make mulib, or with ON1XC set
script=docs/caravansary/examples/riviera.crs
bin/caravansary plan "$script" --date 2026-11-26 > matrix.jsonl
bin/caravansary report "$script" --as-of 2026-11-26T12:00:00Z > coverage.json
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
historical archive separately. The On1x CLI bounds each input file and holds
the report in memory. Native JSON text materialized into On1x strings cannot
contain embedded NUL characters.

Use the [Riviera metrics script](../../docs/caravansary/examples/riviera-metrics.crs)
to emit custom metrics. They appear under `transformation.metrics` with
digests of the parsed program and base report. Changing a transformation
does not change cell keys or invalidate past observations. Scripts without a
`transform` block produce the base report unchanged.

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
sandbox. `plan` and `report` write only to stdout; they never open the script's
output paths or load credentials. Keep secret or credential-bearing URLs out of
competitor and observation data.

## Host integration

For On1x hosts, the [frontend](frontend/README.md) compiles CaravanScript to a
validated configuration. `plugins.caravansary.planning.plan` loads it with a
script path and approved input roots. `row_count` and `row_value` expose the
matrix as indexed rows, and `row_at` renders a single row as canonical JSON.
`plugins.caravansary.coverage.coverage.report` folds host-supplied JSONL into
the matrix. These interfaces use the immutable JSON tree from
`plugins.caravansary.planning.json`.

`plugins.caravansary.coverage.scheduler` returns state values for a serial
caller to carry between `create`, `schedule` and `finish`. It never dispatches
requests. Treat On1x host integration as serial: timezone conversion uses the
process's POSIX timezone setting temporarily.

### Python compatibility API

Existing Python 3.10+ hosts can still import
`plugins.caravansary.caravansary` from the repository root. `parse(text)`
validates the script (including the structure of BCP 47 locale tags, not
membership in the complete language subtag registry).
`plan(path, on_date=None, *, now=None, input_roots=())`
returns an iterator; `load_plan(...)` additionally returns the parsed config.
Treat returned config and cell dictionaries as read-only. The host can combine
`coverage(...)` with the in-memory `Scheduler`; there is no daemon, shared
request quota, production adapter, or historical store.

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

On1x hosts can import `plugins.caravansary.credentials` and call
`resolve(config, source, environ, explicit, approved)`. Pass a validated
configuration and host-filtered value objects. `approved` is an object keyed
by provider, then `cookies` or `dotenv`, then the exact declared path; its leaf
values are already approved UTF-8 text. The resolver returns `Result` with
`mode`, `values`, and `cookies` fields on success. Keep those values out of
logs and artifacts. On1x's text snapshots last for the host process lifetime.

Python hosts can call `resolve_credentials(config, source, *, environ=None, explicit=None,
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

## Run one Booking.com sandbox test

Use an authorized Demand API partner account. In the
[Affiliate Partner Centre](https://developers.booking.com/demand/docs/development-guide/authentication#generate-an-api-key),
get an API token and Affiliate ID and have your secret store inject them into
the process as `CARAVANSARY_BOOKING_API_TOKEN` and
`CARAVANSARY_BOOKING_AFFILIATE_ID`. This command does not use the consumer
website password, browser cookies, `.env`, or any CaravanScript credential
declaration. Do not pass the API token on the command line.

```sh
bin/caravansary pilot-booking \
  plugins/caravansary/examples/booking-sandbox/pilot.crs \
  --confirm-authorized
```

This sends one read-only
[Demand API v3.3 search](https://developers.booking.com/demand/docs/open-api/3.3/demand-api/accommodations/accommodations/search)
to the [official sandbox](https://developers.booking.com/demand/docs/getting-started/sandbox),
not production. The supplied script requests a one-night stay today for two
adults at the documented Hotel Orion test property. Use `--date YYYY-MM-DD` to
choose a future check-in. A custom script must select exactly one verified
Booking cell and a documented sandbox ID. The probe sends the dates, party,
booker country and currency with the fixed `desktop` platform; the search
endpoint has no locale input.

The probe verifies TLS and limits the response to 512 KiB, with a 10-second
request deadline. It does not use a proxy, follow redirects, retry, paginate,
or make bookings. Its
stdout summary contains the attempt count, times, HTTP status if received, and
an outcome (`matched`, `no_match`, or `failed`). It never writes credentials,
raw responses, prices, reports, or observation logs. `no_match` is not proof of
unavailability. Even `matched` does not establish complete production coverage.

## What still requires a production pilot

There is no production adapter for Booking.com or Agoda.com. Credentials and
verified mappings do not grant permission to collect or retain data. Written
permission, representative property IDs, approved budgets, permitted retention
and the [measured pilot](../../docs/caravansary/feasibility.md) remain required.
There is no appraised price or Yieldcraft handoff.
The host must enforce capture permission, retention expiry and provider-specific
query restrictions before any production collection.
