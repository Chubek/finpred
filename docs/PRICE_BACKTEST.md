# Backtest one ordered price series

```sh
./bin/finpred price-backtest MODEL HORIZON FIRST_TARGET HISTORY [SEASON]
```

For example, `./bin/finpred price-backtest ema 2 4 prices.csv` holds out
targets 4 through the end of the file and forecasts each one two periods
ahead. Use the same `period,price_minor` CSV as `price-predict`: 1–256
consecutive zero-based periods, in order, with nonnegative prices at most
1,000,000,000,000 minor units. The file must end in LF. Use an equally spaced,
comparable series in a single currency. `FIRST_TARGET` is a zero-based
period and must satisfy `HORIZON <= FIRST_TARGET < number of observations`.
Only `seasonal` takes `SEASON`.

Choose the model, horizon, and split **before** looking at the held-out
outcomes. The command neither tunes the model nor chooses between candidates.
For target `t` at horizon `h`, the origin is `t - h`; the existing model fits
only periods `0` through that origin, inclusive. Neither the target nor the
intervening `h - 1` observations enter that fit. Earlier holdout observations
can enter a later fold only once that fold's origin reaches them. In
particular, ensemble weights use the existing one-step expanding-window
procedure *within each fold's training prefix*, not the held-out outcomes
at or beyond that fold's target.

The [report](../contracts/analysis.price-backtest@1.schema.json) contains all
requested folds. A missing prediction is attributed to insufficient training
or model rejection (for example, a negative Holt forecast). The benchmark
is the last observed price at the same origin. Benchmark metrics use exactly
the same scored folds as the chosen model, not a larger sample. Both sets of
metrics use the rounded minor-unit price that `price-predict` would issue for
that prefix and horizon.

For `n` scored folds and signed errors `e = forecast − actual`:

| Field | Value |
| --- | --- |
| `mae_minor` | `sum(abs(e)) / n` |
| `mse_minor_squared` | `sum(e²) / n` |
| `rmse_minor` | `sqrt(sum(e²) / n)`, as a decimal string rounded half-up to three places |
| `wape` | `sum(abs(e)) / sum(actual)`, a ratio, not a percentage |
| `bias_minor` | `sum(e) / n` |

Except RMSE, metrics are exact, unreduced ratios with decimal-string
numerators to preserve large integers. WAPE is null when the total scored
actual is zero. All metrics are null if nothing was scored; skipped folds
never count as zero errors. The report is printed without writing a store
or changing any price-prediction or forecast archive format.

**Limits.** This is an ordered-series diagnostic, not point-in-time
validation. The CSV carries no release or ingestion clocks, revisions,
comparability evidence, or currency metadata. The command cannot detect
preprocessing leakage, prove when a model was selected, or make a holdout
independent again after repeated tuning. It does not model demand, sales,
transaction costs, or revenue. The tests use synthetic data and do not
establish empirical lift, calibrated uncertainty, or prediction intervals.
A separate [reproducible empirical exercise](../research/ecb-fx/README.md) uses
one public ECB vintage and does not claim point-in-time holdout evidence.

Run `python3 tests/check_price_backtest.py` after building the main CLI.
