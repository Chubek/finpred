# Caravansary pricing and backtesting

These native On1x libraries consume and return immutable `planning.json`
values. No library reads a clock, obtains a grant, fetches a rate, or publishes
a price. Inputs labeled `fixture` are synthetic, not evidence about a market.

## Independent nightly positioning

`plugins.caravansary.stdlib.price.position(comparables, policy)` accepts the
array returned by `stdlib.comparables.select`, concatenated across successfully
validated cells. Physical property IDs must come from host-verified links;
a provider listing ID is not a substitute. Do not transform failed
projections or unavailable coverage into prices.

The host selects a `caravansary.price-policy@1` object with:

- `subject_property_id`, `qualification` (`fixture` or `observed`), and `as_of`
  (an explicit RFC 3339 UTC timestamp).
- The exact projected `scope`: `currency`, `checkin`, `checkout`,
  `guest_configuration` (the full planner object, including child ages and
  allocation), `booker_country`, `locale`, `price_basis`, `taxes_fees_inclusion`,
  `meal`, and `cancellation`. Only explicit meal and cancellation terms and
  included mandatory taxes/fees qualify.
- `min_properties` (3–512), `max_age_seconds` (0–31,536,000), and `quantile_bps`
  (0–10,000). The sample uses the most recent usable price per physical
  property; equal-time conflicting amounts exclude that property. Evidence
  must satisfy `observed_at <= received_at <= ingested_at <= as_of`, and
  freshness is measured from `observed_at`. Subject quotes and different
  qualification/scopes do not count.
- Positive `current_minor`, `floor_minor`, `ceiling_minor`, and nonnegative
  `max_move_minor`; these are nightly amounts in the requested currency and
  must each be at most 10¹². The recommendation clamps the nearest-rank
  quantile to `[floor_minor, ceiling_minor] ∩ [current_minor − max_move_minor,
  current_minor + max_move_minor]`.

A one-night `stay_total` needs no conversion. For multiple nights, only a
directly reported `nightly_average` qualifies; a `stay_total` returns
`unsupported_price_basis`. No derived nightly amount, FX, fee adjustment,
or occupancy adjustment is performed. Exact scope does not establish room
category equivalence across properties.

The `caravansary.position@1` body has methodology
`independent-nearest-rank-nightly@1` and status `recommended` or `abstained`.
Success has `recommendation_unit: "nightly"`, `recommended_minor`, sample
summary, evidence, rejection counts, guardrails, and a clamp indicator.
Abstention has `reason` but no `recommended_minor`. With too few usable
properties it also contains the selected evidence and the rejection counts.
Rejection counts describe the submitted artifact, not facts that were
available at decision time. For example, an appended future record can
change the audit counts without changing the usable evidence or recommendation.
The body identity is `Json.digest(body)` (SHA-256 of canonical JSON, no
newline), kept outside the body.

`stdlib.statistics.describe(sample, quantile_bps)` exposes the same
descriptive kernel for a nonempty array of up to 4,096 integers in
`[0, 10¹²]`. It returns exact sum/count, extrema, median and median absolute
deviation floored to integers, and a nearest-rank quantile (0 selects min).

## Chronological first-party rooms-sold baselines

`stdlib.forecast.predict(history, request)` and
`stdlib.forecast.backtest(history, request)` use finalized realized
rooms sold, not unconstrained demand, occupancy probability, or elasticity.
History is `caravansary.rooms-sold-history@1`, with `qualification`,
`property_id`, `room_scope`, and `observations` (at most 1,024). Each row has
`stay_date` (a UTC daily bucket), `available_at` (explicit UTC clock no
earlier than next-day midnight), and `rooms_sold` (integer 0–1,000,000).
The caller supplies a point-in-time archive; never overwrite the historical
value or use the stay date as a stand-in for when a revision was posted.

The forecast request `caravansary.rooms-sold-forecast-request@1` supplies
`target_date` (same UTC day as `as_of` or up to 365 days after it), `as_of`,
and `settling_days` (0–30). The fixed 28-day training window ends one day
before the decision's UTC date, minus `settling_days`. All 28 observations
must be present and visible at the cutoff. The two baselines are the
rounded mean of the four matching weekdays and the mean of all 28 days.
Unobserved dates are not replaced with zero. Tied conflicting or invalid
current revisions cannot be replaced with older values.

The backtest request `caravansary.rooms-sold-backtest-request@1` supplies
`start_date`, `end_date` (inclusive, up to 180 dates), `lead_days` (0–365),
`settling_days`, and `eval_as_of`. Each fold decides at midnight
UTC on `target_date - lead_days`. Held-out actuals must be finalized and
available by `eval_as_of`, never used in that fold's training. The two
absolute error sums divided by `scored_folds` give exact matched-fold MAEs;
skipped dates are reported separately. Neither model is selected or fit
using the holdout.

## Separate expected contribution

`stdlib.revenue.expected(inputs)` computes simple scenario arithmetic from
`caravansary.first-party-contribution-input@1`: `provenance: "first_party"`,
`qualification`, `property_id`, total-stay `scope`, `as_of`,
`assumptions_available_at`, `gross_stay_minor`, `available_stays`,
`expected_consumed_stays_milli`, `net_revenue_per_consumed_stay_minor`,
and `variable_cost_per_consumed_stay_minor`. The latter two are capped at
10⁹ minor units; expected consumed stays cannot exceed availability,
which is capped at 10⁶. Contribution is expected consumed stays times
`(net revenue − variable cost)` per stay, rounded to the nearest minor unit
with ties away from zero. Positive or negative contribution does not
establish causal price effects.

`stdlib.revenue.for_position(position, inputs)` also checks exact equality
of property, scope, qualification, cutoff, and recommended amount versus
the separately supplied gross stay scenario. Because the join is between
a nightly recommendation and stay-total economics, it only matches a
one-night stay-total scope. It never derives first-party demand from
comparables or uses competitor price as net revenue.

## Focused synthetic fixtures

From the repository root, after provisioning the pinned compiler:

```sh
ON1XC="$PWD/build/caravansary/toolchain/on1xc" sh plugins/caravansary/pricing/check.sh
```

The runner uses Clang and isolated `build/caravansary/W4/` output. Fixtures
cover exact minor units, deduplication and conflicts, stale and future
evidence, mismatched scope and qualification, a bounded nightly price and
multi-night total abstention, future-history invariance, delayed/missing
actuals, and independent contribution. They do not establish forecast
performance or any provider capability.
