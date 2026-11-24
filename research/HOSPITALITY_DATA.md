# Public hospitality evidence: suitability for Yieldcraft

The public sources below are useful for narrower questions, but neither
contains the exposure ledger the Yieldcraft estimators require.

| Source | Observed data | Suitability |
| --- | --- | --- |
| Antonio, de Almeida and Nunes, [*Hotel booking demand datasets*](https://doi.org/10.1016/j.dib.2018.11.126), [open article and supplements](https://pmc.ncbi.nlm.nih.gov/articles/PMC6297060/) | 119,390 accepted booking records from two Portuguese hotels, with fulfilled/canceled outcomes, lead time, segments, and average daily rate. The article is CC BY 4.0 and the authors credit hotel permission for public sharing. | Can describe cancellations conditional on a booking. It does not contain all offered prices, bookable opportunities that did not convert, or contemporaneous inventory by offer. ADR is based on lodging transactions, not a pre-assignment quote; some features are from the day before arrival rather than the booking decision. Do not turn these rows into `assigned` counts or use final status features as predictors. |
| Eurostat [`tour_occ_nim`](https://ec.europa.eu/eurostat/databrowser/view/tour_occ_nim/default/table?lang=en) | Aggregate monthly stays in tourist accommodation. FinPRED's admitted projection is EU27 guest nights by month, not property-level room nights. | Suitable for aggregate forecasting with publication/vintage controls. Not a property price-response panel or an inventory-policy outcome source. |

No records from the two hotels were imported, and neither source was used to
train or claim commercial uplift. A valid demand study requires permission
to retain a de-identified first-party offer ledger, including quoted price
and currency, pre-price segment, no-purchase exposures, availability at
exposure time, follow-up through cancellation maturity, and observation and
ingestion clocks. A policy backtest additionally needs realized cost and
capacity history and an evaluation design that addresses the fact that only
the historical policy's actions are observed. Keep the holdout and any
randomization or causal identification evidence separate from model fitting.
