# CaravanScript v1 and data contracts — draft

Status: draft, 2026-11-26. An initial offline parser and planner exist; see
[the plugin README](../../plugins/caravansary/README.md) for implemented limits. This is an
implementation contract for review; names and syntax are not yet stable.
The script is the entry point for acquisition and reporting; it may reference
external competitor and weight files. Its configuration grants no network,
filesystem, plugin, or credential authority: the host grants those separately.

## Language profile

UTF-8 source, case-sensitive identifiers, `#` comments through end of line,
JSON-style quoted strings, decimal integers, and braces for blocks. Fields use
`name = value;`; arrays use `[value, ...]`. Commas separate array elements.
String escape sequences follow JSON. Reject duplicate blocks/fields, unknown
fields, unsupported versions, invalid escapes, and trailing tokens. No implicit
environment interpolation, shell execution, or imports. Relative input paths
resolve against the script directory; output paths are separately host-approved.
Time zones are IANA names; dates are Gregorian local civil dates; clocks in
records are RFC 3339 UTC. Currency is ISO 4217. Durations are positive integer
seconds unless a field says otherwise. Accommodations use an extensible string
classification, not a closed enumeration.

```text
caravan "Riviera Hotel" version 1 {
  property {
    type = "hotel"; latitude = "43.000000"; longitude = "7.000000";
    timezone = "Europe/Paris"; currency = "EUR";
    room_types = ["standard", "suite"];
  }
  competitors = "riviera-comparables.json";
  sources = ["booking", "agoda"];
  search {
    horizon_days = 365; start = "today";
    guest_configurations = ["one_adult", "two_adults"];
    stay_lengths = [1, 2, 3];
    booker_country = "FR"; locale = "fr-FR";
  }
  refresh {
    tick_seconds = 3600; weights = "weights.json";
    max_age_seconds = 86400; booking_requests_per_hour = 100;
    agoda_requests_per_hour = 100; booking_concurrency = 1;
    agoda_concurrency = 1;
  }
  output { observations = "observations.jsonl"; coverage = "coverage.json"; }
}
```

Example values are hypothetical, not recommendations or a runnable script.
The referenced competitor document defines the guest configurations so each
ID resolves to a positive room count, adult count and array of child ages; each
room allocation must be representable. Maximum supported counts and provider
restrictions are validated by the adapter; they must not silently shrink the
configured matrix. Locale and country describe the booking context, not the
property location. Prices for different contexts cannot be silently combined.
`start` is `today` or a `YYYY-MM-DD` string. For today, capture the property's
local date at matrix generation; create 365 check-in dates, inclusive of the
start. The checkout is check-in plus stay length in calendar days. It can be
beyond the 365-day horizon. Re-evaluation rolls the start forward; retain past
observations per authorized retention policy.

V1 above defines the collection subset. Transformation functions, procedures,
Yieldcraft calls and plugin imports are reserved for a subsequent language
revision; no executable function syntax or sandbox is promised by this draft.
That revision must define types, deterministic evaluation, input/output
contracts, limits, errors, provenance, and granted capabilities before use.

### Collection grammar and validation

The following EBNF fixes the shape of the draft collection subset. Whitespace
and comments may occur between tokens; field order inside a block is
irrelevant. `string` is a JSON string, `integer` is a nonnegative decimal
integer without leading zeros except `0`, and `identifier` is an ASCII letter
followed by ASCII letters, digits, or underscores. Literal words and
punctuation are quoted here for clarity.

```ebnf
script      = "caravan", string, "version", "1", "{", statement*, "}" ;
statement   = field | block ;
field       = identifier, "=", value, ";" ;
block       = identifier, "{", statement*, "}" ;
value       = string | integer | array ;
array       = "[", [ value, { ",", value } ], "]" ;
```

This grammar describes syntax; the following schema restricts the otherwise
generic statements. Require exactly one each of the top-level `property`,
`search`, `refresh`, and `output` blocks and `competitors` and `sources`
fields. No other top-level blocks or fields are valid. Property requires
`type`, `latitude`, `longitude`, `timezone`, `currency`, and `room_types`;
coordinates are decimal strings within latitude -90..90 and longitude
-180..180. `room_types` is a nonempty array of unique nonempty strings.
Search requires `horizon_days` (1..365), `start`, nonempty unique
`guest_configurations` and `stay_lengths`, `booker_country`, and `locale`.
Each stay length is a positive integer. `booker_country` is an ISO 3166-1
alpha-2 code; locale is a valid BCP 47 language tag. Each guest ID must
resolve once in the referenced competitor input. `sources` is a nonempty
unique subset of `booking` and `agoda`. Refresh requires `tick_seconds`,
`weights`, `max_age_seconds`, and request budget and concurrency fields for
each selected source; all numeric values must be positive. Fields for an
unselected source are allowed but do not authorize it. Output requires
`observations` and `coverage`, distinct nonempty paths. Referenced input
files must exist and pass their own validation before any acquisition starts.
Providers may impose tighter supported bounds, which validation reports
without discarding requested cells.

For multi-room configurations, `allocation` is an array of exactly `rooms`
objects, each with `adults` and `child_ages`. Each room has at least one adult;
the sum of allocation adults and the multiset of child ages must equal the
configuration totals. A one-room configuration may omit `allocation`; it
is then exactly the stated party. Guest party, booking context and output
paths are not credentials; any credential is supplied by the host.

## Competitor input: `caravansary.competitors@1`

JSON object with `kind`, `guest_configurations`, and `properties`. Guest
configurations are objects with unique `id`, `rooms` (positive integer),
`adults` (positive integer), and `child_ages` (integer ages 0–17). Include
explicit room allocation if multiple rooms are requested; never infer it.
Properties contain unique string `id`, `name`, optional `type` and coordinates,
and a `providers` object keyed by source name. Each source mapping contains
`provider_property_id` and/or `url`, and `mapping_status` (`verified`,
`unverified`, `missing`). Only operator-verified mappings may be queried;
missing mappings still generate coverage cells. Reject duplicate IDs and
duplicate verified provider identities within a source. Do not automatically
merge similarly named properties across sources. A provider with no listing is
`missing`, not `unavailable`.

## Matrix and coverage: `caravansary.coverage@1`

One logical cell is keyed by script/config identity, source, competitor ID,
check-in, checkout, and complete guest configuration, including room
allocation. Search context, filters, and relevant provider configuration are
part of the versioned config identity; a changed configuration cannot reuse a
cell as though the request were identical. There may be multiple offers per
cell. The latest attempt and latest successful complete observation are
separate, timestamped records; a failed attempt never deletes a prior success.

`status` is one of `pending`, `priced`, `unavailable`, `unsupported`, or
`failed`. `priced` requires at least one valid qualifying offer;
`unavailable` requires an authoritative complete provider response for the
exact query, not an empty page, missing mapping, or transport error. Missing
mapping is `unsupported` with reason `mapping_missing`; an unverified mapping
has reason `mapping_unverified`. `failed` records a bounded reason code and
attempt time. `freshness` is independent: `fresh`, `stale`, or `none`, based
on the latest successful complete observation and its per-cell deadline. An
unavailable response can be fresh; a failure can coexist with a stale earlier
price. Reports include every expected cell, counts by status and freshness,
last success and attempt, next due time, and whether the freshness target is
achievable given current budgets. Partial results are never complete responses.

## Observation: `caravansary.observation@1`

Append-only JSON Lines; each record has `kind`, `observation_id`, `cell_key`,
`provider_property_id`, `source_url` if permitted, `observed_at` (if supplied
and trustworthy), `received_at`, `ingested_at`, `adapter_version`,
`extractor_version`, `request_context`, `complete`, `outcome`, `offers`,
and optional allowed capture digest/reference. Use null with a reason for
unknown fields; never fabricate a provider timestamp. `received_at <=
ingested_at`; an asserted observed time must not exceed receipt time.

Each offer has provider offer/room identifiers when supplied, room name,
guest/room allocation, rate plan, currency, amount in integer minor units or
an exact decimal string, `price_basis` (`stay_total`, `nightly_average`,
`nightly_itemized`, `unknown`), tax/fee components and their inclusion state,
meal and cancellation conditions, availability and source text when allowed.
`nightly_itemized` contains date/amount pairs only when the provider actually
reports those values. If a derived average is emitted, record its formula,
rounding and original total; do not label it an observed nightly price. Keep
the original raw value and locale when permitted, without guessing a currency
or charge treatment. Support multiple rate plans and do not mix discounts,
guest configuration, tax basis or checkout duration. Record the collection
and retention authority and expiry separately from credentials. Storage and
historical retention are conditional on the applicable provider agreement.

## Weights and scheduling

`caravansary.weights@1` supplies explicitly sourced, nonnegative relative
weights for guest configurations and stay lengths, or explicit joint weights;
there is no assumed statistical independence. Missing weights are a validation
error unless a declared default is provided. Each eligible cell has a positive
weight or a separate minimum-service rule. `max_age_seconds` is a target, not a
guarantee; infeasible deadlines must be reported. A tick schedules due work
within per-provider budgets, with backoff and bounded retries. Reserve service
for the least recently successful work to avoid starvation. The actual queue
algorithm and capacity proof are part of implementation, not this contract.

The v1 joint-weight input is a JSON object with `kind`, a nonempty `source`
description, `mode` equal to `joint`, and a `weights` array. Each entry has
`guest_configuration`, positive integer `stay_length`, and nonnegative numeric
`weight`. Exactly one entry is required for every configured guest/stay pair;
reject duplicates and entries for unconfigured pairs. At least one weight must
be positive. If any weight is zero, the host must enforce and disclose a
separate minimum-service rule before starting collection; zero does not remove
the cell from coverage. Other weighting modes require a later contract.

The [illustrative files](examples/riviera.crs) include matching competitor and
joint-weight inputs. Their property identities and weights are fictional, all
provider mappings are missing, and their request budgets are arbitrary. They
are design examples; there is no acquisition runtime yet. For this example
the expected matrix is 2 sources × 2 properties × 365
dates × 2 guest configurations × 3 stay lengths = 8,760 cells, all initially
unsupported due to missing provider mappings.

## Downstream interoperability

Caravansary does not make a recommendation in this phase. The existing
[`hospitality.competitor-snapshot@1`](../COMPETITOR_CUBE.md) consumes complete
replacement releases and exact occupancy quotes and has bounded input sizes;
empty releases mean no bookable offers, not failed acquisition. Its currency,
price-basis, alias, chronology and size requirements must be checked by a
future explicit adapter. It cannot directly ingest the entire matrix. The
legacy Yieldcraft percentile package has a different CSV contract and bounds.
Provider mapping, currency and charge basis must be resolved before either
handoff. Raw observations and transformation identities must remain traceable.
