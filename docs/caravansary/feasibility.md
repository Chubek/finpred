# Provider feasibility, capacity, and pilot

Assessment date: 2026-11-26. Verdict: **not yet demonstrated**. Source
inspection and offline fixtures establish a starting point, not live data
access, a viable nightly breakdown, a sustainable refresh rate, or permission
to retain data. No live provider collection was performed in this assessment.

## Existing implementation: evidence

The checked-out MuLIB revision is `26c4fc0845be2ffd120ce0d68b4b7c5ee7c95be9`.
The Booking and Agoda `.elvs` profiles declare scrape mode, fixed home URLs,
external Lua logic and IPC destinations; Booking additionally names a cookie
file. See [BookingDotCom.elvs](../../third_party/mulib/library/elvis/BookingDotCom.elvs)
and [Agoda.elvs](../../third_party/mulib/library/elvis/Agoda.elvs).
Their corresponding Lua extracts display name, URL, display price text and
location text from synthetic property cards. Booking proposes a next-page
link; Agoda caps emitted properties at 20 and does not paginate. Neither
extractor obtains dates, party, stay length, currency, room, price basis,
individual nights, tax treatment, or rate conditions. Booking's source says
explicitly that it is an offline fixture, not a live compatibility claim;
Agoda's source says it uses a synthetic static fixture. See
[Booking logic](../../third_party/mulib/library/elvis/logic/BookingDotCom.lua),
[Agoda logic](../../third_party/mulib/library/elvis/logic/Agoda.lua) and
[integration test](../../third_party/mulib/tests/test-elvi-script.c).

The coordinator starts at the profile home URL; a host fetches queued requests
under its policy. Lua's `emit` permits four strings: name, URL, price display
text and location. The HTML parser has strict markup and resource limits and
does not run JavaScript. See [coordinator](../../third_party/mulib/manual/mulib-elvi-script.md)
and [logic contract](../../third_party/mulib/manual/elvi-script-logic.md).
Thus an actual integration needs a parameterized, authorized request path,
structured emission and richer parsing or an alternative authorized adapter;
changing selectors alone cannot establish the full contract. Static profiles,
fixture extraction and existing Dragnet's Google/Bing host do not implement
this workflow. Rate limits and supported live response forms are unmeasured.

## Published access information

* [Booking.com platform terms](https://www.booking.com/content/terms.en-gb.html),
  section A15, say automated access requires prior express written permission.
  This is a published general condition; assess the actual agreement and
  permissions for the intended account and method.
* [Booking Demand API search](https://developers.booking.com/demand/docs/accommodations/search-for-available-properties)
  documents dates, guest/room counts, property IDs, price and optional product
  and charge information. Its [API reference](https://developers.booking.com/demand/docs/open-api/3.3/demand-api/accommodations/accommodations/search)
  documents up to 100 accommodation IDs per search request. Search normally
  returns the cheapest available product; pagination, filtering, coverage,
  field availability, price basis and per-night detail need pilot validation.
  [Authentication and partner access](https://developers.booking.com/demand/docs/accommodations/v3.3/accommodation-tutorial)
  require credentials and an appropriate enabled agreement. The
  [migration FAQ](https://developers.booking.com/demand/docs/migration-guide/v3/migration-faqs)
  advises against caching prices or availability. Confirm whether this
  project's planned analysis and historical retention are permitted; API
  availability is not authorization for this use.
* [Agoda's published affiliate agreement](https://partners.agoda.com/Content/pdf/Agoda_OnlineAffiliateAgreement.pdf)
  contains restrictions on scraping and certain price-comparison uses in that
  agreement. Its applicability depends on the actual agreement. The
  [Agoda Demand Search API](https://developer.agoda.com/demand/docs/copy-of-search-api)
  describes hotel rates and availability for dates, occupancy and currency,
  and requires a site ID and API key. The [getting-started guide](https://developer.agoda.com/demand/docs/getting-started-20-1)
  describes partner onboarding and certification. Whether competitor
  monitoring, historical retention, the desired result detail and volume are
  permitted for this project remains unverified. The supply API is intended
  for connected properties and is not evidence of competitor access.

Do not infer that credentials alone authorize the contemplated use. No
provider credentials or explicit permission were available for this task, so
neither automated site probes nor API requests were made. Documentation was
examined instead. A bounded authorized pilot is the next empirical gate.

## Capability matrix

| Capability | Current Booking Elvis | Current Agoda Elvis | Partner API documentation / open question |
| --- | --- | --- | --- |
| Property name, URL, display price, location | Synthetic fixture only | Synthetic fixture only | API fields documented; actual account and mappings untested |
| Select fixed property set | Not implemented | Not implemented | Booking documents ID filtering; Agoda documents specified hotels; test coverage and limits |
| Dates, occupancy, length | Not implemented | Not implemented | Both document search criteria; request combinations and horizon untested |
| Room, rate conditions, taxes | Not extracted | Not extracted | Some product/policy/charge fields documented; exact completeness untested |
| Quoted stay total vs individual nightly amounts | Display text only | Display text only | Neither individual-night breakdown nor exact semantic basis verified |
| All 365 days and every requested combination | Not demonstrated | Not demonstrated | Availability horizon, pagination, missing inventory and quotas untested |
| Price history retained for this use | Not established | Not established | Explicit permission and permitted retention periods must be confirmed |
| Actual requests per matrix cell | Unknown | Unknown | Measure on authorized representative queries |

## Capacity model

For the illustrative 200-property, 365-check-in, 4-guest-configuration,
3-stay-length, 2-provider example, the matrix has 1,752,000 logical cells,
or 876,000 per provider. These are not network request counts.

Let `C_p` be cells for provider `p`, `b_p` the observed mean number of
**completed eligible cells** per successful logical query, `a_p` the measured
mean network attempts per logical query including pagination, retries and
failures, `T_p` the target maximum age in hours, and `B_p` the authorized
attempt budget per hour. An optimistic necessary steady-state condition for a
uniform age target is `B_p >= C_p * a_p / (b_p * T_p)`; allow additional
headroom for recovery, rollover, delays and uneven batching. This is not a
sufficient schedulability proof, and batch efficiency must be measured with
the actual missing mappings and result completeness. Initial fill requires at
least `C_p * a_p / b_p` attempts under those assumptions. Daily rollover adds
an average of 200 × 4 × 3 = 2,400 new cells per provider per local day, while
old cells expire; this is already included in a steady-state full-matrix
refresh estimate and should not be double-counted.

Illustration only, per provider, assuming `a=1`, uniform age and no overhead:

| Completed cells per query | Attempts for first fill | For 24-hour target, attempts/hour | For 1-hour target, attempts/hour |
| ---: | ---: | ---: | ---: |
| 1 | 876,000 | 36,500 | 876,000 |
| 20 | 43,800 | 1,825 | 43,800 |
| 100 | 8,760 | 365 | 8,760 |

The 100-cell illustration is arithmetic, not a promise that 100 IDs always
yield 100 usable responses in one request or that an API permits this rate or
use. At a hypothetical 100 authorized attempts/hour with `b=1`, an initial
fill takes at least 8,760 hours per provider; with `b=100`, at least 87.6
hours. The 24-hour target is infeasible in either scenario. Weighting can
allocate freshness unevenly but cannot bypass the total budget; prove each
class's maximum age separately. Stay-length and guest-count weights in the
work order are user hypotheses, not measured booking statistics.

Reproduce the 20-cell scenario with the offline calculator below. All inputs
are assumptions until measured by an authorized pilot. Run separately for
each provider; a `true` budget condition does not prove schedulability.

```sh
python3 docs/caravansary/capacity.py --properties 200 --days 365 \
  --guest-configurations 4 --stay-lengths 3 --cells-per-query 20 \
  --attempts-per-query 1 --budget-per-hour 100 --max-age-hours 24
```

## Authorized pilot protocol and acceptance record

Before running: obtain written authorization/partner terms covering the exact
method, competitor monitoring, volume, test data handling and retention;
provide source credentials through the approved host mechanism, never the
script or repository. Specify two verified competitor mappings per provider,
booker context, currency and permitted output storage. Confirm an allowed
request budget and capture policy. Without these inputs this protocol is
blocked, not passed.

For each authorized provider: test the two properties with two guest
configurations, 1- and 3-night stays, and check-ins near the start, middle and
end of the 365-day window, subject to the permitted budget. Record actual UTC
request and receipt times, input parameters, response status, pagination,
each network attempt, and sanitized output references only where retention is
permitted. Include a known missing or unavailable case if safely supported.
Verify exact matching, room/rate conditions, currency, taxes, total-versus-night
semantics, response completeness, and maximum date support. Repeat a small
approved subset to measure consistency, failures and observed requests per
complete cell; do not extrapolate a quota from one successful request.

Report source, method, account authorization reference (never secrets), date,
fixture or live classification, input matrix, each capability result as
observed/unsupported/unknown, sample size, total attempts including retries,
complete cells, `a`, `b`, any per-night detail, retention restrictions, and
failure reasons. Estimate capacity using the measured distribution and agreed
freshness and budgets. Provider layout and access may change; a pilot is a
dated observation, not a permanent guarantee.

Milestone A acceptance requires this empirical record for both sources, or an
explicit stakeholder decision accepting a documented source gap, in addition
to review of the draft contracts. Current status: **open**.

## Offline verification

On 2026-11-26, `make check-elvi-script` passed against the checkout above:
transport, Lua logic, coordinator/IPC (including synthetic Booking and Agoda
fixtures), and named IPC. The diagnostic about a stream ending without valid
completion is expected from a negative test. The checks use fixtures and do
not prove any live provider behavior. Restricted-environment attempts failed
on local file/socket access; the complete suite passed when rerun with the
required local access.
