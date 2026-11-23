# Local pricing fixtures

These CSVs are synthetic inputs for the default Yieldcraft strategy. They do not
contact a provider or publish a price. All recommendations are EUR cents per
night; a failed case has no recommendation.

| Scenario | Offers | Valuation | Expected result |
| --- | --- | --- | --- |
| [`scenario.csv`](scenario.csv) | [`offers.csv`](offers.csv) | [`valuation.csv`](valuation.csv) | 17,100; `lower_percentile_shortcut` |
| [`scenario_multiroom.csv`](scenario_multiroom.csv) | [`offers_multiroom.csv`](offers_multiroom.csv) | [`valuation.csv`](valuation.csv) | 16,000; `guardrail_adjustment` |
| [`scenario_asof.csv`](scenario_asof.csv) | [`offers_asof.csv`](offers_asof.csv) | [`valuation.csv`](valuation.csv) | 18,000; `target_percentile` |
| [`scenario_asof_early.csv`](scenario_asof_early.csv) | [`offers_asof.csv`](offers_asof.csv) | [`valuation.csv`](valuation.csv) | `insufficient_evidence`; no run written |
| [`scenario_leap_day.csv`](scenario_leap_day.csv) | [`offers_leap_day.csv`](offers_leap_day.csv) | [`valuation_leap_day.csv`](valuation_leap_day.csv) | 17,001; `target_percentile` |
| [`invalid_scenario.csv`](invalid_scenario.csv) | [`offers.csv`](offers.csv) | [`valuation.csv`](valuation.csv) | Invalid scenario; no run written |

- **As-of cutoff:** Exact stay coverage and the seven-calendar-day freshness
  boundary are inclusive. Property 302 is ingested exactly at the decision
  timestamp and supplies the third comparable. Moving only the decision back
  one second leaves two comparables when three are required. At the original
  cutoff, four rows are excluded for future observation, late ingestion,
  staleness, and incomplete stay coverage.
- **Leap day:** February 28 to March 1, 2028 spans two civil nights.
  The P75 rank is halfway between whole-stay totals of 34,000 and 34,001 cents.
  Interpolation rounds to 34,001 cents; nightly division rounds again to
  17,001. The 34,001-cent comparable needs two rooms at the same property.

For example, from the repository root after building:

```sh
work=$(mktemp -d)
FINPRED_HOME="$work/store" \
FINPRED_SCENARIO=fixtures/scenario_leap_day.csv \
FINPRED_OFFERS=fixtures/offers_leap_day.csv \
FINPRED_VALUATION=fixtures/valuation_leap_day.csv \
FINPRED_STRATEGY=strategies/yieldcraft.ottomat \
./bin/finpred run --engine legacy
```

Use the printed run ID with `FINPRED_HOME="$work/store" ./bin/finpred evidence RUN_ID`
to inspect the frozen room allocations. `python3 tests/check_fixtures.py` runs
the independent arithmetic and eligibility oracle; `./tests/run.sh` checks the
compiled CLI and read-only replay. [`replay_v1.json`](replay_v1.json) is a
separate byte-preserving archive for historical replay tests, not a `run` input.
