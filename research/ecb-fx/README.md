# Empirical exercise: ECB monthly USD per EUR

**Source:** European Central Bank (ECB), Frankfurt am Main, Germany,
Data Portal series `EXR.M.USD.EUR.SP00.A`, January 2022–December 2024,
retrieved 2026-11-24 via the
[ECB public data API](https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A?startPeriod=2022-01&endPeriod=2024-12&detail=dataonly&format=csvdata).
The [ECB copyright and disclaimer](https://www.ecb.europa.eu/home/disclaimer/html/index.en.html#c)
permits accurate and attributed reuse of this information subject to its
conditions. The data is freely available from the ECB; the local copy is not
an ECB publication.

The original 2,268 CSV bytes have SHA-256
`e8fe31fccc7d53fb3ab772d38257dab60fb5f6d8b44ca987ee913325f84133a6`.
The [checked-in snapshot](monthly-usd-per-eur-2022-2024.csv) changes only CRLF
to LF; no observations have been altered. Restoring CRLF reproduces the raw
digest. A later download may represent a different vintage.

## Offline reproducibility

After `make`, run `python3 tests/check_price_backtest.py`. This validates the
source series and the complete 36-month sequence, then converts each
observation to integer ticks of `0.000001 USD per EUR`, rounded half up.
That conversion is a FinPRED modification, not ECB data. The compiled
backtest transports ticks in its `price_minor` field; these are **not** cents.
January 2022 is period 0. The exercise uses one fixed EMA model (no tuning
on the report), a one-month horizon, period 24 as the first scored target
and last observation as its benchmark. Each later forecast can use a prior
2024 observation only after its fold origin reaches that observation.

The compiled diagnostic and independent exact-arithmetic oracle agreed:

| 2024 targets | EMA MAE (ticks) | Last-observation MAE (ticks) |
| --- | ---: | ---: |
| 12 of 12 scored | 158512 / 12 | 144640 / 12 |

The EMA did worse in this series and window. This is an **empirical
single-vintage retrospective diagnostic**, not a pre-registered
point-in-time holdout: the feed is one later vintage, with no reconstructed
release timestamps or revision history for the folds. It does not establish
future performance, trading value, hospitality demand or revenue uplift.
ECB reference rates are not executable quotes. The synthetic numerical
and leakage fixtures in the same test serve a separate purpose.
