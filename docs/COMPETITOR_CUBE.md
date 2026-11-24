# Frozen accommodation competitor cube

`finpred cube` evaluates a bounded batch of guest-payable, whole-party,
whole-stay price recommendations. It does **not** collect quotes or publish
prices. Give it an operator-supplied, lawfully retained snapshot. Its output is
distinct from legacy Yieldcraft recommendations, which are nightly EUR prices.
Do not compare or combine the two without converting the basis explicitly.

## Run and replay

From the repository root, after `make`:

```sh
export FINPRED_CUBE_HOME="$PWD/build/demo-cube"
./bin/finpred cube evaluate \
  fixtures/competitor/snapshots.csv fixtures/competitor/cells.csv \
  fixtures/competitor/policies.csv > build/demo-cube.json
python3 -m json.tool build/demo-cube.json
./bin/finpred cube replay 588f6bcfcf9128268cd1f81bcc11f0b855828edfd86804fc91c6a44217c211d2
python3 tests/check_competitor_cube.py
```

The demo needs no provider credentials or network. The first cell finds three
prices (17,500, 21,000 and 24,000 EUR minor units); the recommendation is
21,000 for two adults and two children over two nights. A later cutoff
recognizes a newly ingested sold-out release instead of reusing its older
quote. The other cells exercise strategy cache reuse, no observations for a
different stay, and work budget exhaustion.

`evaluate` and `replay` both print `{"cube_id":...,"cube":...}`.
The inner result conforms to
[`pricing.competitor-cube@1`](../contracts/pricing.competitor-cube@1.schema.json).
For programmatic callers, `plugins.yieldcraft.competitor_cube.evaluate(snapshots, cells,
policy_rows)` is a pure On1x entry point returning the inner JSON. The
launcher dispatches cube commands to the separate `finpred-cube` host and
resolves relative paths from the repository root. The archive defaults to
`.finpred-cube/`, independently of `FINPRED_HOME` and `FINPRED_FORECAST_HOME`.
Only use trusted local regular input files and a private cooperating-writer
archive directory.

## Input profiles

All inputs are bounded, unquoted, printable ASCII CSV (`LF` or `CRLF`). Numbers
are unsigned decimal with no leading zeros except `0`. IDs have at most
12 digits, so they remain exact in JSON consumers using IEEE 754 doubles.
Dates use `YYYY-MM-DD`
and clocks `YYYY-MM-DDTHH:MM:SSZ`; dates must lie in 1970–2399. Supported
currencies are EUR, GBP, USD and JPY in their native minor units. No currency
conversion runs. Policy amounts are interpreted in the cell's currency; use
separate policy IDs when monetary bounds differ by currency.

### `hospitality.competitor-snapshot@1`

The first line is the contract ID; subsequent lines are ordered blocks:

```text
release,id,property,provider,arrival,departure,currency,observed_at,received_at,ingested_at,weight,bundle_min_rooms,bundle_discount_minor
quote,id,pool,quantity,adults,children,min_child_age,max_child_age,min_stay_nights,cancellation,base_minor,fees_minor,taxes_minor,discount_minor
```

The tags `release` and `quote` are literal; the rest are data, not column
headings. A file may contain no release, or up to 64 releases and 512 total
quotes (up to 32 per release, 128,000 bytes). Release IDs are positive and
strictly increasing; quote IDs are positive and strictly increasing within
their release. Property and pool IDs are positive. `provider` is a lower-case
identifier such as `demo` (ASCII letters, internal digits/hyphens, at most
32 bytes).

Each release is a **complete replacement** for one canonical
`property,arrival,departure,currency` scope. Zero quote rows means no
bookable offers, not a failed collection. Never encode a failed, truncated,
or partial acquisition as an empty release. A property may not have multiple
provider labels in one file; observations tied at the same instant for one
scope are rejected. The importer is responsible for resolving property and
inventory aliases before writing the file. Different canonical properties
are treated as independent; the engine cannot detect affiliation or aliases
that the source declared as different IDs.

Clocks must satisfy `observed_at ≤ received_at ≤ ingested_at`. A cell only
sees releases ingested at or before its cutoff. Of those it chooses the
latest observation for each property and then checks freshness; it never
falls back to an older bookable release after seeing a replacement. Freshness
uses UTC calendar days, not rolling 24-hour intervals. Other stay lengths or
currencies do not substitute for a missing release.

Quotes are for **exact** adult/child counts, not maximum capacities. Child
ages must fall in the quote's inclusive range; use `0,17` on an adult-only
quote. Each room requires at least one adult. A quote may be used more than
once if stock permits. Alternatives that share a pool draw from the same
quantity (1–32) and must declare that same quantity. Each selected quote
must meet the minimum stay and the requested cancellation class. The
supported classes are `flexible` and `nonrefundable`; they are not full
books of cancellation terms. Only a request explicitly specifying `any`
mixes classes.

Quote gross = `base - discount + fees + taxes`, with a maximum of 10¹²
minor units per room. Quote discounts reduce base only. Each release may also
offer a fixed bundle discount once if the solution uses at least
`bundle_min_rooms` (2–4, or `0,0` for no bundle discount). Its amount
cannot exceed that number times the smallest net base in the release. This
conservative rule prevents a bundle discount from consuming any fees or
taxes. Tax-inclusive component values must already reflect any tax treatment
required by the provider; the engine does not compute taxes.

### `pricing.competitor-cells@1`

The first line is the contract ID and the second line is the literal header
in [`cells.csv`](../fixtures/competitor/cells.csv). One row is one cube cell
(up to 48 cells, 32,000 bytes), uniquely identified by increasing positive
`id`. The request addresses arrival date and length of stay, party, cutoff,
currency, cancellation and strategy. `departure` is exclusive; the date
difference is 1–365 nights. Supply 1–8 adults, 0–8 child ages in ascending
`5|10` notation (empty for no children), and 1–4 rooms, never more rooms than
adults. `max_age_days` is 0–365, `min_properties` is 1–64, and
`search_budget` is 1–50,000 quote visits plus age-subset attempts. If the
budget is depleted before completing the search, no partial distribution or
recommendation is returned for that cell.

Cells sharing the same match parameters and budget reuse matching within the
same evaluation, even if they use different strategies or sample minimums.
`market_evaluations` reports misses, not cells. Batches currently execute
sequentially; they neither share a cache across evaluations nor track changed
dependencies across archives.

### `pricing.competitor-policy@1`

The first line is the contract ID and the second is the literal header in
[`policies.csv`](../fixtures/competitor/policies.csv). Use up to 16 policies
with increasing positive IDs (8,000 bytes). A policy supplies a target
percentile in basis points (0–10,000) as a function of UTC lead days. The
endpoints apply at lead zero and at or beyond the horizon. Interpolation
rounds half up:

| `curve` | `horizon_days` | `shape` | `knot_bps` |
|---|---|---|---|
| `fixed` | `0` | `0` | `0`; `near_bps` equals `far_bps` |
| `linear` | 1–365 | `0` | `0` |
| `power` | 1–365 | integer exponent 2–4 | `0`; weight is `(lead/horizon)^shape` |
| `exponential` | 1–365 | 1–16 segments | `0`; weight is the linear interpolation of normalized powers of two at uniformly spaced knots |
| `piecewise` | 2–365 | interior knot day | basis points at the knot; linear either side |

The comparator is the cheapest feasible bundle from each property. Equal
totals favor fewer rooms, then the first witness in stable quote/child-mask
order. `type7` uses the existing unweighted Type-7 quantile. `weighted` uses
the first price reaching the chosen cumulative weight fraction, with zero
percent at the lowest price. The positive per-property weight (1–10,000) comes
from the snapshotted release; the engine does not infer similarity, quality or
reliability from these quotes. Prefer a consistent, documented weighting
policy upstream.

The policy can select `lower_bps` instead of the target if the positive
price difference is strictly below the `minor` threshold or the `bps`
fraction of the intended amount. Use `off,0` to disable. The lower
percentile must not exceed any curve knot or endpoint. The entire party's
candidate is then clamped to `[floor_minor, cap_minor]` (up to 4×10¹²).
No floor, cap, or other policy can turn missing evidence into a price.

## Evidence, failure, and scope

- Successful cells expose the comparable releases, observation/receipt/ingest
  clocks, weights, chosen quote and pool IDs, room gross amounts, and guest
  assignment. A room's `child_mask` uses bit zero for the first age in
  `child_ages`; each bit can appear in at most one selected room. The bundle
  total may be less than the sum of room gross amounts because of a bundle
  discount.
- Non-recommended cells carry a null price and one of `no_observations`,
  `stale_observations`, `no_feasible_bundle`, `insufficient_evidence`, or
  `budget_exhausted`. A malformed input rejects the entire batch without
  printing or saving a cube.
- An archive ID is BLAKE3 of a canonical LF-terminated text manifest
  `finpred-competitor-cube@1` followed by four lower-case BLAKE3 digests:
  imported snapshots, cells, policies, and result JSON. The CLI stores the
  manifest only after all four objects. `replay` reads by digest, re-evaluates
  and compares the exact result bytes before printing; it does not reopen
  input paths or modify the archive. These digests do not authenticate a
  provider or prove that a permit to collect the data exists.
- The existing private local artifact store is not a reviewed durable or
  adversarial-filesystem backend. There are no new native bindings,
  credentials, transport, or external action capabilities.
- The input is a frozen import profile, **not** authorization for a live
  Dragnet integration. This slice does not implement provider capture and
  extraction, scheduled refresh, parallel/incremental execution, a new
  Ottomat syntax, a Poindexter dashboard, own-inventory pricing, market
  clusters, booking-velocity or event signals, hysteresis, cross-cell
  constraints, room/rate-plan allocation, elasticity, or revenue backtests.
  Existing guest-night forecasts are not property-level demand evidence.
