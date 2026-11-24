# Empirical diagnostic: Germany's long-term convergence yield

Source: European Central Bank (ECB) Data Portal, [long-term interest rate for
convergence purposes, Germany, monthly][series], 2023-01 through 2025-12.
The [public API response][csv] (HTTP `Date` 2026-11-24 20:36:27 UTC,
`Last-Modified` 2026-11-11 09:00:00 UTC) has SHA-256
`f094f09753355aeb1b6f9215254c9f60deb1698f536dce738b2e16f523937a8d`.
The checked-in copy changes CRLF to LF. The ECB [terms][terms] permit
attributed and accurate reuse subject to their conditions. This is not an
ECB report.

Run `python3 tests/check_ecb_yield_study.py` after building. It checks the
source bytes, series dimensions, and month sequence, then multiplies rates
by 1,000 so that the price backtest transports exact integer ticks equal
to 0.001 percentage point. The recent 36-month extract has nonnegative
rates; the price transport is not suitable for periods of negative yields.
The fixed EMA (`alpha=0.5`) and last-observation benchmark use the same
origin at each horizon, with all twelve 2025 months evaluated. No model
parameters are tuned on the results. An independent arithmetic oracle
checks the folds and metrics.

| Horizon | Matched targets | EMA MAE (ticks) | Last-observation MAE (ticks) |
| --- | ---: | ---: | ---: |
| 1 month | 12 | 1254 / 12 | 1489 / 12 |
| 3 months | 12 | 1866 / 12 | 1880 / 12 |

EMA has lower MAE in this window, only narrowly at three months; it
[performed worse for USD/EUR](../ecb-fx/README.md). These are small
single-vintage retrospective diagnostics, not release-vintage holdouts or
evidence of general predictive value, tradable yields, or hospitality uplift.
The reporting months are not publication dates.

[series]: https://data.ecb.europa.eu/data/datasets/IRS/IRS.M.DE.L.L40.CI.0000.EUR.N.Z
[csv]: https://data-api.ecb.europa.eu/service/data/IRS/M.DE.L.L40.CI.0000.EUR.N.Z?startPeriod=2023-01&endPeriod=2025-12&detail=dataonly&format=csvdata
[terms]: https://www.ecb.europa.eu/home/disclaimer/html/index.en.html#c
