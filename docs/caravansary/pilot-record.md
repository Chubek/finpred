# Authorized pilot record template

Copy this file for each provider and test date. Do not put credentials, cookies,
personal guest data, or unauthorized provider response content in the
repository. Retain raw captures only if the applicable agreement allows it.
The linked [pilot protocol](feasibility.md#authorized-pilot-protocol-and-acceptance-record)
defines the minimum test matrix.

## Authorization and configuration

| Field | Value |
| --- | --- |
| Provider and method | |
| Date and operator | |
| Non-secret agreement / permission reference | |
| Competitor monitoring allowed? | unknown / yes / no |
| Data retention and use allowed; expiry | |
| Approved request budget and concurrency | |
| Source profile / adapter version | |
| Property identifiers and mapping verification | |
| Booker country, platform, locale, currency | |
| Guest and room configurations | |
| Check-in dates and stay lengths | |
| Permitted capture location / deletion policy | |

## Attempt log

Record one row for each attempt, including pagination, failures and retries.
Use a non-sensitive query/cell ID to link requests to results; record the
actual date/time and status, not access tokens or credential-bearing URLs.

| Attempt ID | UTC sent / received | Query / page ID | Status | Complete? | Cells completed | Sanitized evidence reference |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

## Observed capabilities

Use `observed`, `unsupported`, or `unknown`, with a specific evidence
reference and limitations. An absent value is not evidence of unsupported
functionality. Distinguish itemized nightly prices from a stay total or
derived nightly average.

| Capability | Result and evidence |
| --- | --- |
| Property ID mapping and matching | |
| Date horizon and checkout beyond horizon | |
| Guest count, ages and room allocation | |
| Room/rate plan and selection completeness | |
| Price currency and basis | |
| Itemized nightly prices | |
| Taxes, fees, cancellation and meals | |
| Unavailable vs failed/partial response | |
| Pagination and request limits | |
| Repeatability and observed changes | |

## Measurements and decision

* Logical queries completed / attempted:
* All network attempts, including pages and retries:
* Complete eligible cells:
* Attempts per logical query (`a`):
* Complete cells per logical query (`b`):
* Measured date range, sample size and limitations:
* Capacity estimate for the actual approved budget and freshness targets:
* Open permissions, unknowns, failures and next action:

These measurements describe only this pilot and must not be represented as a
provider guarantee. If no authorized pilot can be run, record that as blocked;
do not fill in estimates as measured data.
