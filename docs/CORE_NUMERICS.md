# Core series numerics

`source/algorithms/series_forecast.h` exposes a read-only C11 forecast and
walk-forward evaluator. The input is one equally spaced series, oldest first,
with 1–256 signed fixed-point observations of magnitude at most `10^12`.
Results use the same unit as the input. The horizon is 1–365 steps; season is
1–256 steps, with 1 meaning no phase grouping. The caller supplies the regular
grid and a fixed model configuration. The core does not fill gaps, infer a
calendar, select a season, or treat a forecast as a decision.

## Point and interval

For target index `t` and a training prefix of length `n`, take the latest 24
prefix observations whose indices are congruent to `t` modulo the season. Fit
a Theil–Sen line to those points: the slope is the median of pairwise slopes,
and the intercept is the median of the corresponding offsets from that slope.
Even medians average the central values. Evaluate the line at `t` and round to
the nearest integer, with exact half ties away from zero. The model abstains
when the target phase has fewer than three observations. No sign clipping is
applied; extrapolations can exceed the input range.

For interval calibration, use absolute errors of the **rounded** predictions
from the same model and horizon, each fitted using only its own origin prefix.
Only residuals whose actual index is `< n` are available. The radius is the
`ceil((m + 1) * coverage / 100)`-th smallest of the `m` available errors, using
one-based ranks and no interpolation. Supported coverage levels are 80%, 90%,
and 95%. If the rank exceeds `m` (fewer than 4, 9, or 19 errors respectively),
the point is still returned, but the interval is unavailable. A zero-radius
interval is valid and distinct from an unavailable one.

These are empirical rolling-error intervals. Their finite-sample rank rule
does **not** establish distribution-free coverage for dependent observations
or under distribution shift. The evaluator reports realized coverage, which
must not be confused with nominal coverage.

## Walk-forward evaluation

For each requested target `t`, the training prefix length is
`max(0, t - horizon + 1)`. The target and any observations between the origin
and target are excluded from both fitting and calibration. Once an actual
becomes observable, its residual can enter a later fold's calibration. This
is an online evaluation protocol, not a frozen holdout simulation. A caller
using these results to tune a model needs a separate evaluation split.

The API emits a row for every requested target, including abstentions, and
returns integer totals and explicit denominators:

| Statistic | Numerator | Denominator |
| --- | --- | --- |
| Mean absolute error | Sum of absolute errors | Folds with points |
| Empirical coverage | Actuals in the inclusive interval | Folds with intervals |
| Mean interval width | Sum of `upper - lower` | Folds with intervals |
| Mean interval score | Sum of `width + 2 / (1 - coverage) * miss` | Folds with intervals |

Here coverage in the score formula is a fraction, and `miss` is the distance
outside the interval, or zero for a covered actual. A zero denominator means
the statistic is unavailable, not zero. Coverage levels were chosen so that
the miss multiplier is integral and the totals fit in `int64_t`.

## Exact arithmetic and dependency

The implementation calls MuLIB `statsproc` for medians and order statistics.
It does not round a floating-point Theil–Sen extrapolation: the selected
slopes are recovered as rationals before the intercept and forecast are
computed. Rebase same-phase timestamps to consecutive cycle indices. With
at most 24 such observations, slope denominators are at most 23. Distinct
slopes differ by at least `1 / 23²`, so the truncated integer sort key
`(2048 * rise) / run` preserves their order and identifies the exact rank's
fraction. The midpoint between two central slopes and the offset numerators
are formed with integers. Offset keys fit 52 bits, so MuLIB's half-integer
median and residual order statistics are exactly representable in binary64.
The final division and rounding are integer operations.

The per-origin fit uses at most 276 pairwise slope keys; the walk-forward
evaluator computes each point at most once. Forecasting and evaluation use
bounded temporary storage; MuLIB quantile calls may allocate bounded scratch.
No files or mutable process state are accessed by the API.

## On1x consumer

C11 targets can import `algorithms.series_forecast` and pass one canonical
signed decimal plus LF per observation (for example `"-2\n0\n5\n"`). Empty
input, leading zeros, a plus sign, negative zero, and missing terminal LF
are rejected. Calibrated predictions expose typed point, interval flag,
bounds, and calibration count. `evaluate` exposes typed score totals and
LF-terminated fold rows with these columns:

```text
target,training_count,actual,has_point,point,calibration_count,has_interval,lower,upper
```

Rows do not include a header. Flags are `0` or `1`; unavailable numeric
fields use zero. This is a library interface, not a new CLI route. A C11
consumer links `source/algorithms/series_forecast.c` and
`source/algorithms/series_forecast_on1x.c` with MuLIB `statsproc` and `-lm`.
The private bridge passes only managed strings and `i64` values across the
FFI; it does not expose pointers or C struct layouts to On1x.

## Validation

Run the independent exact-rational test oracle (Python is test-only):

```sh
python3 tests/check_core_numerics.py
python3 tests/check_core_numerics_on1x.py
```

For an isolated worktree with unpopulated submodules, set `MULIB_ROOT` to the
pinned MuLIB checkout and set `ON1XC` for the executable check. The tests
exercise both the native API and a pinned On1x→C11 executable. Cases include
signed ties, partial seasons, outliers, unavailable intervals, maximum-sized
histories, and mutations of observations beyond a fold's origin.
