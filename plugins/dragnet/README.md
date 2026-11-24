# Dragnet — Elvi search and bounded page extraction

The search host is an **On1x-controlled, trusted standalone host**, not a
generic plugin sandbox. It uses the pinned MuLIB `elvi-scrape` engine and its
Google/Bing profiles, then `scrape-readable` to remove tags, comments, scripts
and styles and collapse whitespace. It does not execute JavaScript or a browser.
Entities remain encoded, as specified by MuLIB's readable-text kernel.

## Build and run

From the repository root, after provisioning the pinned compiler (`make mulib`):

```sh
make
make dragnet
./bin/dragnet --config plugins/dragnet/examples/Dragnet.json  # offline demo
sh bin/dragnet --config Dragnet.json
sh bin/dragnet --config Dragnet.json --daemon
make dragnet-search-test
```

Build dependencies: the same C11/On1x toolchain as FinPRED, `pkg-config`,
libcurl >= 7.85 and its development headers. libcurl is an explicit **host**
dependency, not a new MuLIB kernel dependency. Build output is
`build/dragnet/dragnet` for acquisition and `build/dragnet/finpred-dragnet`
for read-only consumption. Set `FINPRED_DRAGNET_BUILD_DIR` to use another
directory for both build and launchers.
Provider source bytes are embedded from the selected MuLIB checkout at build
time. The runtime does not look up mutable `.elvs` files.

`--daemon` stays in the foreground for systemd or another supervisor. It runs
one cycle immediately, then waits `interval_seconds` after completion.
SIGINT/SIGTERM cancel the active worker or wait. One failed cycle stops the
daemon, with a nonzero status; there are no hidden retries. A fresh process
per cycle bounds process-lifetime On1x allocations. There is no background
double-fork, scheduler database, pidfile or claim of exactly-once ingestion.
Use one supervisor instance per configuration.

## Frozen source adapters

The standalone adapters retain their original input and output contracts. They
are independent of the search host and do not need its configuration or
credentials:

| Adapter | Build | Run or verify |
| --- | --- | --- |
| Frozen offer CSV | `plugins/dragnet/build-frozen-csv.sh` | `build/dragnet/dragnet-frozen-csv 3<fixtures/scenario.csv 4<fixtures/offers.csv` |
| Frozen Crossref | `plugins/dragnet/build-crossref.sh` | `plugins/dragnet/crossref` (local snapshots only) |
| ECB / Eurostat feeds | `plugins/dragnet/build-feeds.sh` | [`plugins/dragnet/feeds`](PUBLIC_FEEDS.md) |
| Offline Source dispatcher | `plugins/dragnet/build-dispatch.sh build/dragnet-dispatch` | [Source selectors and descriptor protocol](SOURCE_DISPATCH.md) |

The frozen CSV [manifest](plugin.json) declares a pure, analysis-only Source
with no host capabilities. It validates the complete CSV and emits eligible
`hospitality.offer@1` records as JSON Lines, using the exact offer CSV bytes
for the provenance digest. Only the explicit, caller-opened descriptor inputs
are used. Supply unchanged regular files from a trusted directory: scenario
on fd 3, offers on fd 4, at most 2,000,000 bytes each and 1–512 offer rows.
Invalid inputs produce no records; a valid snapshot with no eligible
observations succeeds with empty stdout.

For example, import and verify the synthetic, offline Crossref fixtures:

```sh
plugins/dragnet/build-crossref.sh
fixtures=tests/dragnet_elvi_consumer
plugins/dragnet/crossref import 'hotel & rates' \
  "$fixtures/request.csv" "$fixtures/search.json" "$fixtures/work.json" > evidence.json
plugins/dragnet/crossref verify 'hotel & rates' \
  "$fixtures/request.csv" "$fixtures/search.json" "$fixtures/work.json" evidence.json
```

`DRAGNET_CROSSREF_BIN` overrides the Crossref tool directory. Pass only
authorized local snapshots: the launcher decodes and checks exact-byte
digests, but does not authenticate the provider or the asserted capture
times. It never queries Crossref or opens the pricing store.
Public-feed polling is a separate operation that requires explicit terms and
retention references; replay and the dispatcher do not poll.

Run `make dragnet-test` for the saved-fixture adapter and dispatcher checks.

## Dragnet.json

```json
{
  "version": 1,
  "provider": "google",
  "keywords": ["hotel rates"],
  "extraction": "basic",
  "as_of": "2026-11-24T23:59:59Z",
  "max_results": 2,
  "interval_seconds": 300,
  "transport": "offline",
  "fixtures": {
    "https://www.google.com/search?q=hotel%20rates&num=2": "search.html",
    "https://hotel.example/rooms": "rooms.html"
  }
}
```

All fields above are required; `fixtures` is required only for `offline`
and forbidden for `https`. Unknown fields, unsupported versions and wrong
types fail closed. Do not repeat JSON object keys; the pinned MuLIB decoder
uses the last occurrence. `provider` is `google` or `bing`; `keywords` is 1–8 nonempty
query strings, at most 256 bytes each, without control bytes.
`max_results` is 1–10 **per query**; `interval_seconds` is 60–86400.
One query string is sent to Elvi without shell splitting.

Each query is matched against the readable **page**, not its result title:
all nonempty ASCII-space-separated terms must occur, case-sensitively.
This profile does not perform language stemming, case folding or semantic
matching. Duplicate result URLs within a query are removed by Elvi; the same
page may appear for different queries/cycles.

Paths are relative to the launch working directory. Offline URL-to-file
mappings are explicit trusted operator input; missing mappings never fall back
to a network request. Snapshots/config are regular, NUL-free files, <=256 KiB.
This is not filesystem confinement against malicious local writers.

For live mode, set `"transport": "https"`, remove `fixtures`, and grant each
exact DNS host separately on the command line:

```sh
sh bin/dragnet --config Dragnet.json \
  --allow-host www.google.com --allow-host authorized-provider.example
```

For Bing, grant `www.bing.com` instead. A URL/configuration is not a network
grant. Result hosts are not implicitly trusted. The launcher clears inherited
host grants before processing arguments. Direct executable users are trusted
hosts and can supply `DRAGNET_ALLOWED_HOSTS` explicitly.

HTTPS transport verifies certificates/hostnames, disables proxies and redirects,
denies private/reserved IPv4 peers at the socket boundary and denies IPv6.
It enforces 5-second connection/15-second request deadlines and 256 KiB bodies.
Only complete HTTP 200 `text/html` transfers succeed; 429/503, consent pages
and provider layout drift have no retry/fallback policy. An empty result list
can be successful and is **not proof that no market offers exist**.
Use `"as_of": "now"` for a rolling live daemon; each output records a concrete
UTC receipt cutoff. With a fixed cutoff, the live receipt time must not exceed
`as_of`: live scraping cannot reconstruct historical knowledge.
No provider has been live-tested as part of the offline conformance suite.

Use live scraping only with an authorized provider and appropriate
terms/licensing/rate limits. Host grants do not prove that authorization.

## GPT extraction

Set `"extraction": "gpt"` to send matched readable page text to the OpenAI
Responses protocol. Dragnet uses MuLIB's OpenAI operation catalog and text
decoder over the same bounded, certificate-verified libcurl transport. It
requests one non-streaming response per matched page, with `store: false`,
at most 1,024 output tokens and no tools. The instructions are authored in
On1x; the page is separate untrusted input. A refusal, incomplete response
or unexpected/tool output fails closed. This is not a guarantee against
prompt injection: `llm_text` is untrusted **analysis only**, never interpreted
as a command, provider instruction or offer row.

For a domain-specific extraction, set `"llm_task"` in the trusted config (up to
2,048 bytes), for example `"Summarize the policy rate decision and its date."`.
It changes the analysis request, not the model's tools, capability grants, or
which downstream consumer can use the capture. The default task is generic.

The recognized settings are `OPENAI_MODEL` (required), `OPENAI_API_KEY` or
`OPENAI_ACCESS_TOKEN` (live auth), optional `OPENAI_BASE_URL` (default
`https://api.openai.com/v1`), `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID`.
Per variable, process environment takes precedence over `.env` (or the
optional `env_file` path), then over the `environment` object in Dragnet.json.
The dotenv reader accepts literal `KEY=VALUE` with optional matching quotes,
does not expand variables or execute a shell, and ignores unrecognized keys.
An env file or inline secrets config must be owned by the launching user and
private (`chmod 600`). The launcher does not export inline variables to the
shell. Prefer process or supervisor secrets rather than inline credentials.
`OPENAI_ACCESS_TOKEN` accepts an externally obtained OAuth bearer for an
endpoint that supports it; Dragnet does not implement login or token refresh.

Live GPT additionally needs explicit permission to send page text and an
exact host grant for the API endpoint:

```sh
./bin/dragnet --config Dragnet.json --allow-llm \
  --allow-host www.google.com --allow-host authorized-provider.example \
  --allow-host api.openai.com
```

For offline GPT, add `llm_fixtures` mapping each matched **page URL** to a
frozen Responses JSON file. No credential is needed and no POST is made.
Successful GPT evidence includes endpoint/model, request body, response bytes,
digest and receipt time; it excludes authentication headers. Save only where
the page and response data are permitted to be retained. A custom endpoint
must be trusted with both the bearer credential and readable page text.

## Shared handoff to plugins and core code

Use `--handoff` to save a complete acquisition cycle as a consumer-neutral
capture. Dragnet does not pick, start, or grant capabilities to a consumer.
The same file can be read by several consumers, with no provider credentials
and no access to the original HTML files.

```sh
./bin/dragnet --handoff --config plugins/dragnet/examples/Dragnet.json > capture.jsonl
./bin/finpred dragnet-inspect capture.jsonl 2026-11-24T00:00:00Z
```

`dragnet-inspect` is a read-only core consumer. It checks the capture against
the explicit UTC cutoff and reports its digest and page/LLM/offer-claim counts.
It makes no pricing decision and doesn't open a FinPRED store.

### Consumer contract

- A capture contains one canonical `dragnet.batch@1` header, zero to 80
  `dragnet.page@1` lines, and one `dragnet.batch-end@1` trailer, all UTF-8 with
  LF delimiters. Up to 2,000,000 bytes per frame. See the
  [framing](contracts/dragnet.batch@1.schema.json) and
  [page](contracts/dragnet.page@1.schema.json) schemas.
- The trailer records the page count and BLAKE3 of the **exact** header and
  page bytes, including every LF before the trailer. Do not reserialize a
  frame before verifying it. The shared reader also checks the embedded
  search/page/LLM parent digests and receipt/cutoff consistency.
- On1x hosts can `import plugins.dragnet.dragnet_batch as Dragnet` with the
  repository root on the module search path.
  `Dragnet.read(bytes, cutoff)` accepts exactly one frame and returns a
  `Batch` with metadata and a proper list of raw page-record strings in
  acquisition order. `Dragnet.page(sx_text(sx_head(rest)))` returns typed
  fields, including readable text and raw evidence. The reader consumes bytes
  only; the calling host chooses where to obtain them. Invalid input fails
  before a result is returned. A [compiled independent consumer](../../tests/dragnet_batch_consumer.on1x)
  demonstrates this without linking Dragnet's native host or Yieldcraft.
- `--daemon --handoff` writes one frame per successful cycle, including
  empty cycles. Stream consumers must wait for and verify each trailer before
  acting. The file-based `finpred` commands expect one frame at a time. A
  zero-page frame means no matches in that cycle, not absence of relevant
  pages in the world.
- Checksums detect inconsistency, not authorship. A `pricing_input` flag is
  a source claim, not an authority grant. Readable/LLM text must never be
  interpreted as configuration, a plugin selector, or executable instructions.
  Downstream consumers own semantic validation and authority for their domain.

### Unframed page evidence

Default stdout is JSONL, `dragnet.page@1`, one record per matched page. It
contains query, URL, cutoff, readable text and exact search/page HTML with
BLAKE3 digests. `handler` fingerprints the application sources, compiler,
MuLIB headers and runtime sources; it is a source identity, not a signed build
attestation. `received_at` is the actual host UTC receipt for live pages;
it is empty for supplied offline snapshots, whose capture time/authenticity
this host cannot attest. `as_of` is an operator cutoff, **not** an asserted
source observation or receipt time. Save the JSONL together with the config,
build/toolchain identities and any provider authorization records.
Hashes establish content consistency, not provider authenticity.
Re-running the same config against those frozen bytes is deterministic and
does not require network or `FINPRED_HOME`.

### Optional Yieldcraft adapter

[`bin/yieldcraft`](../yieldcraft/README.md#run-binyieldcraft) can run this
capture/validation/pricing sequence in one command, or consume a frozen batch
without reacquisition.

**Basic extraction is analysis-only:** arbitrary price-looking text is never
promoted to an offer. The opt-in `offer-csv-v1` extraction profile requires an
authorized page to expose exactly one readable marker:

```text
FINPRED_OFFER_V1 <one complete FinPRED offers.csv data row> END_FINPRED_OFFER
```

See `fixtures/offers.csv` for the exact 16-column profile. Nothing is inferred:
property/room identity, stay, occupancy, total-stay price in integer minor units,
fees, taxes, EUR currency, observation/ingestion time, validity and bookability
must all be present. Existing `core.contracts.offer_csv` validates the row in
On1x. Future knowledge, duplicate markers and malformed rows fail the whole
cycle before stdout. Live ingestion time is replaced with the actual host
receipt, never the page's claimed ingestion time. A live fetch grant alone
does not grant pricing authority: each trusted offer host additionally requires
`--allow-offer-host HOST`. Offline fixtures are explicitly supplied by the
operator; their origin/authenticity still needs independent review.

Capture once using `extraction: "offer-csv-v1"`, then explicitly select the
trusted capture for the Yieldcraft adapter:

```sh
./bin/dragnet --handoff --config Dragnet.json > capture.jsonl
./bin/finpred dragnet-offers capture.jsonl 2026-11-24T00:00:00Z > offers.csv
FINPRED_OFFERS="$PWD/offers.csv" ./bin/finpred run
```

`dragnet-offers` validates eligible **input row structure and times** but does
not determine recommendation eligibility itself. It is available for one
complete trusted frame from either acquisition mode. The old `bin/dragnet
--offers-csv` one-off output is still supported, and batches from `basic` or
`gpt` cannot be converted into offers. Yieldcraft separately applies its eligibility,
independent-property, stale-data, room-feasibility and guardrail checks.
Dragnet never invokes Yieldcraft automatically, edits pricing stores, publishes
prices or books rooms. Empty matches emit no JSONL; CSV exports contain only
the header. A failed cycle emits no records (stdout IO errors can still truncate
an OS write). Unframed output is bounded by the 4 MiB On1x text limit. Use temporary files and
rename on successful exit rather than treating a redirected empty file as success.

## Explicit blockers / compatibility

- Provider and OpenAI tests use frozen responses. Live credentials, live
  provider layouts and OAuth login/refresh have not been verified.
- Acquisition is a standalone trusted executable using a scalar native adapter.
  The reusable reader is not SDK Source registration, dynamic plugin execution
  or native storage admission.
- The restored CSV/Crossref/feed/dispatcher tools have their own build paths
  and `make dragnet-test` gate. `make dragnet-search-test` separately checks
  the current Elvi host and its distinct capture format.
- No historical run formats, pricing algorithms or archived fixtures change.
