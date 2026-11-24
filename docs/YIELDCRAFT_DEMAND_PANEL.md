# Yieldcraft observational demand panel

`bin/yieldcraft-demand panel` fits and evaluates an exposure-normalized demand
model for a single property and room product. It reads operator-supplied,
lawfully held first-party aggregates, not customer records, competitor quotes
or synthetic business outcomes. Its
[`pricing.demand-estimation@2`](../contracts/pricing.demand-estimation%402.schema.json)
report is **observational and not decision-eligible**. It never produces
`pricing.demand@1`, a price recommendation, or a causal lift estimate. The
existing randomized `estimate`, `evidence`, and `replay` commands and `@1`
contract are unchanged.

## Run and replay

```sh
bin/yieldcraft-demand build
bin/yieldcraft-demand scenario-digest scenario.csv
bin/yieldcraft-demand panel scenario.csv panel.csv > report.json
bin/yieldcraft-demand panel-replay scenario.csv panel.csv report.json blake3:REPORT_ID
```

Pin `id` separately from the report, then retain the exact source artifact
bytes. Replay compares both the pinned ID and report bytes. The report includes:

- `exposure`: digest of the exact panel bytes; `scenario`: digest of the exact
  scenario bytes.
- `training`: BLAKE3 over the panel metadata line, then **only** the training
  arm lines in source order, each normalized to one LF terminator.
- `model_id`: BLAKE3 over two LF-terminated lines, policy
  `yieldcraft.observational-panel@1` and bare training digest. The metadata
  binds the scenario digest, model, reference price, target and cutoff.
- `id`: BLAKE3 over three LF-terminated lines, `pricing.demand-estimation@2`,
  bare `model_id` and bare panel source digest. Changes only to holdout
  outcomes change `id`, not `model_id` or predictions. These identities are
  content references, not attestations of legal provenance or code signatures.

## CSV profile

Use the repository's bounded, unquoted ASCII CSV profile (LF or CRLF). The
first four lines are:

```text
pricing.first-party-demand-panel@1
scenario_blake3,property,product,currency,price_basis,assignment,train_as_of,reference_price_minor,target_exposures,model
<scenario hex>,hotel-1,standard,EUR,room_night,observational,<UTC timestamp>,15000,100,constant_elasticity
started_at,ended_at,finalized_at,ingested_at,group,price_minor,assigned,kept,cancelled,nonpurchase,unavailable,unresolved
```

- A scenario must cover one room and one night. The currency must match the
  scenario (currently EUR). Prices are integer minor units per room-night
  and must be positive, at most `10^12`, and within `[reference/4, 4*reference]`.
  The reference is operator-declared, not estimated using holdout prices.
- `group` is an operator-defined segment known **before the price assignment**
  (e.g. a fixed lead-time band). Keep the meaning stable across windows.
  Identifiers match `[a-z0-9_-]{1,64}`. Do not include PII, post-treatment
  features, a group chosen using future outcomes, or mixed price bases.
- There are 8–256 arms, up to eight training groups, with each complete
  nonoverlapping window contiguous in time order. Rows belonging to a window
  share all four UTC clocks (`started_at < ended_at <= finalized_at <=
  ingested_at`). Within a window sort by group and then strictly increasing
  price. Each group-window needs ≥2 prices spanning ≥1% of its minimum price.
- `assigned` is the denominator of finalized, bookable opportunities, each
  counted once, including nonbuyers. Each arm has 20–1,000,000 assignments.
  `assigned = kept + cancelled + nonpurchase`; `unavailable` and `unresolved`
  must be zero (fail closed; stockout and censoring are not modeled).
  `target_exposures` (1–1000) is a projection input, not observed
  future demand or a capacity check.
- Training uses windows whose `ingested_at <= train_as_of`; evaluation uses
  later windows whose `started_at >= train_as_of` (windows crossing that
  boundary or finalized/ingested late from before it are rejected). Everything
  must be ingested by scenario `decision_at`, the report's `as_of`. At least
  three training windows, two training windows per group, and one holdout
  window are required. The historical panel has no freshness guarantee.

## Models and evidence

Fit a common slope on `y = log((kept+0.5)/(assigned+1))` with assignment
weights. Both `x` and `y` are centered within each group-window for the slope
fit, so differences only between windows or groups cannot supply slope
identification. The exposure-weighted within-block feature variance must be
at least `10^-6`, and each training group needs both kept and not-kept
assignments. These checks do **not** establish exogeneity or cure selection,
confounding, interference, or shifts in exposure composition.

| `model` | Feature `x` | Slope penalty | Group log intercept |
|---|---|---:|---|
| `constant_elasticity` | `log(price/reference)` | 0 | Group training mean of `y - slope*x` |
| `log_linear` | `price/reference - 1` | 0 | Same |
| `ridge_log_linear` | `price/reference - 1` | 0.0025 | Same |
| `partially_pooled_elasticity` | `log(price/reference)` | 0.0025 | Shrink group log intercept toward the global adjusted mean with 1,000 pseudo-exposures |

Specifically, `slope = centered_weighted_cross_product /
(centered_weighted_feature_sum_of_squares + penalty * training_assigned)`.
The log-linear slope describes a change per unit of *relative* price; local
unclipped elasticity is `slope * price/reference`. For the log-price variants
the slope itself is the unclipped elasticity. Positive slopes are not
forcibly reversed. Partial pooling uses a common slope and fixed shrinkage
weight, not a fitted hierarchical variance model or posterior.

`window_cluster_slope_se_micros` is a descriptive training slope standard
error, available for unpenalized fits with at least eight windows. Using
window-level score sums `u`, it is
`sqrt(G/(G-1) * sum(u^2)) / centered_weighted_feature_sum_of_squares`, where
`G` is the number of training windows. It assumes independent windows; it
does not quantify forecasting or causal uncertainty. Penalized or
short-window fits return `null`. There are no prediction intervals.

Holdout scoring uses the training fit without refitting, and rejects any
holdout group or price beyond that group's training range (interpolation
within the range is allowed). The reported Brier losses are per assigned
exposure against kept-or-not, with a no-price baseline of each group's
training `sum(kept)/sum(assigned)`. Lower is better. Do not use the same
holdout to select a model and then claim an unbiased test score. There is
one operator-declared split; no rolling validation or automated tuning.

## Downstream consumption

Validate `version: 2`, scenario/context/as-of, and identities. Read
`groups[].predictions` directly: one entry per unique training price for the
group, in price order. Kept-rate predictions are the exponentiated fitted
log rates capped at one (this is a model-implied rate from smoothed
log outcomes, not a bias-corrected arithmetic mean). `kept_rate_micros` is
kept room-nights per million assignments; `expected_room_nights_milli`
is the same prediction scaled by `target_exposures * 1000` before rounding.
Do not derive the latter from the rounded rate field or join it to a different
target, currency, segment, room product or price basis. Workers consuming
these typed projections for offline analysis need not (and should not) fit a
second model; the contribution optimizer continues accepting only its
separate snapshot contract. The fixtures in the test verify arithmetic and
validation only; no measured commercial performance is reported.

See the [public-data assessment](../research/HOSPITALITY_DATA.md) for why
bookings-only and aggregate guest-night sources were not fitted to this contract.

Run `python3 -B tests/check_yieldcraft_demand_panel.py` to build and test all
four model variants, holdout isolation, contracts and replay.
