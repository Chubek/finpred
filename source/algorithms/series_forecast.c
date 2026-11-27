#include "series_forecast.h"

#include <float.h>
#include <mulib-statsproc.h>

enum { PHASE_CAP = 24, PHASE_MIN = 3, KEY_SCALE = 2048, PAIR_CAP = PHASE_CAP * (PHASE_CAP - 1) / 2 };
#define OFFSET_BOUND (6 * FINPRED_SERIES_MAX_ABS * (PHASE_CAP - 1) * (PHASE_CAP - 1))
#define CYCLE_BOUND (PHASE_CAP - 1 + FINPRED_SERIES_MAX_HORIZON)
#define POINT_BOUND (FINPRED_SERIES_MAX_ABS * (1 + 2 * CYCLE_BOUND))
#define ERROR_BOUND (POINT_BOUND + FINPRED_SERIES_MAX_ABS)

_Static_assert(FLT_RADIX == 2 && DBL_MANT_DIG >= 53, "MuLIB keys require binary64 precision");
_Static_assert((int)PAIR_CAP >= (int)FINPRED_SERIES_MAX_OBSERVATIONS, "rank weights cover both uses");
_Static_assert(KEY_SCALE > (PHASE_CAP - 1) * (PHASE_CAP - 1), "distinct slopes need distinct keys");
_Static_assert(2 * FINPRED_SERIES_MAX_ABS * KEY_SCALE < INT64_C(4503599627370496),
               "slope keys must be exactly representable");
_Static_assert(OFFSET_BOUND < INT64_C(4503599627370496),
               "offset keys and their half-integer medians must be exactly representable");
_Static_assert(2 * OFFSET_BOUND + 8 * FINPRED_SERIES_MAX_ABS * (PHASE_CAP - 1) * CYCLE_BOUND +
               2 * (PHASE_CAP - 1) * (PHASE_CAP - 1) <= INT64_MAX,
               "exact extrapolation numerator and rounding must fit");
_Static_assert(ERROR_BOUND < INT64_C(9007199254740992), "residual ranks use exact integer keys");
_Static_assert(ERROR_BOUND <= INT64_MAX / (42 * FINPRED_SERIES_MAX_OBSERVATIONS),
               "95 percent interval score sums must fit");

struct ratio { int64_t num, den; };

/* The query is strictly inside the requested mass, never on a CDF boundary. */
static int order_stat(const double *keys, size_t n, size_t rank, double *out)
{
    double weights[PAIR_CAP];
    for (size_t i = 0; i < n; ++i)
        weights[i] = 1.0;
    return mulib_statsproc_weighted_quantile(keys, weights, n, ((double)rank - 0.5) / (double)n, out);
}

/* Truncation toward zero preserves ordering except potentially across zero.
   Here every distinct pair of rationals is more than one scaled unit apart,
   and each nonzero slope is at least KEY_SCALE/(PHASE_CAP-1) units from zero. */
static int64_t slope_key(struct ratio r)
{
    return r.num * KEY_SCALE / r.den;
}

static int median_slope(const int64_t *values, size_t n, struct ratio *out)
{
    struct ratio candidates[PAIR_CAP];
    double keys[PAIR_CAP];
    size_t count = 0;
    for (size_t i = 0; i < n; ++i)
        for (size_t j = i + 1; j < n; ++j) {
            candidates[count] = (struct ratio){ values[j] - values[i], (int64_t)(j - i) };
            keys[count] = (double)slope_key(candidates[count]);
            ++count;
        }

    double lo_key, hi_key;
    if (!order_stat(keys, count, (count + 1) / 2, &lo_key))
        return 0;
    hi_key = lo_key;
    if (!(count % 2) && !order_stat(keys, count, count / 2 + 1, &hi_key))
        return 0;

    struct ratio lo = {0}, hi = {0};
    for (size_t i = 0; i < count && (!lo.den || !hi.den); ++i) {
        if (keys[i] == lo_key)
            lo = candidates[i];
        if (keys[i] == hi_key)
            hi = candidates[i];
    }
    if (!lo.den || !hi.den)
        return 0;
    *out = lo_key == hi_key ? lo : (struct ratio) {
        lo.num * hi.den + hi.num * lo.den, 2 * lo.den * hi.den
    };
    return 1;
}

static enum finpred_series_status point(const int64_t *samples, size_t train, size_t target,
    size_t season, int64_t *out)
{
    if (!train)
        return FINPRED_SERIES_INSUFFICIENT;
    size_t phase = target % season;
    if (phase >= train)
        return FINPRED_SERIES_INSUFFICIENT;
    size_t total = 1 + (train - 1 - phase) / season;
    if (total < PHASE_MIN)
        return FINPRED_SERIES_INSUFFICIENT;
    size_t n = total > PHASE_CAP ? PHASE_CAP : total;
    size_t start = phase + (total - n) * season;
    int64_t values[PHASE_CAP];
    for (size_t i = 0; i < n; ++i)
        values[i] = samples[start + i * season];

    struct ratio slope;
    if (!median_slope(values, n, &slope))
        return FINPRED_SERIES_ERROR;
    double offsets[PHASE_CAP], median;
    for (size_t i = 0; i < n; ++i)
        offsets[i] = (double)(values[i] * slope.den - slope.num * (int64_t)i);
    if (!mulib_statsproc_quantile(offsets, n, 0.5, &median))
        return FINPRED_SERIES_ERROR;
    int64_t time = (int64_t)((target - start) / season);
    int64_t num = (int64_t)(2 * median) + 2 * slope.num * time;
    int64_t den = 2 * slope.den;
    /* Round the exact signed rational to nearest, breaking half ties away from zero. */
    *out = num >= 0 ? (num + den / 2) / den : -((-num + den / 2) / den);
    return FINPRED_SERIES_OK;
}

static int valid(const int64_t *samples, size_t n, size_t horizon, size_t season, unsigned coverage)
{
    if (!samples || !n || n > FINPRED_SERIES_MAX_OBSERVATIONS || !horizon ||
        horizon > FINPRED_SERIES_MAX_HORIZON || !season || season > FINPRED_SERIES_MAX_SEASON ||
        (coverage != 80 && coverage != 90 && coverage != 95))
        return 0;
    for (size_t i = 0; i < n; ++i)
        if (samples[i] < -FINPRED_SERIES_MAX_ABS || samples[i] > FINPRED_SERIES_MAX_ABS)
            return 0;
    return 1;
}

static int64_t magnitude(int64_t value)
{
    return value < 0 ? -value : value;
}

static int interval(const int64_t *past_errors, size_t train, unsigned coverage,
    struct finpred_series_prediction *prediction)
{
    double keys[FINPRED_SERIES_MAX_OBSERVATIONS];
    size_t n = 0;
    /* Index is the actual's timestamp, not the earlier origin's timestamp. */
    for (size_t i = 0; i < train; ++i)
        if (past_errors[i] >= 0)
            keys[n++] = (double)past_errors[i];
    prediction->calibration_count = n;
    size_t rank = ((n + 1) * coverage + 99) / 100;
    if (rank > n)
        return 1;
    double selected;
    if (!order_stat(keys, n, rank, &selected))
        return 0;
    int64_t radius = (int64_t)selected;
    prediction->has_interval = 1;
    prediction->lower = prediction->point - radius;
    prediction->upper = prediction->point + radius;
    return 1;
}

static enum finpred_series_status historical(const int64_t *samples, size_t target, size_t horizon,
    size_t season, size_t *train, int64_t *prediction)
{
    *train = target >= horizon ? target - horizon + 1 : 0;
    return point(samples, *train, target, season, prediction);
}

enum finpred_series_status finpred_series_predict(const int64_t *samples, size_t count,
    size_t horizon, size_t season, unsigned coverage, struct finpred_series_prediction *out)
{
    if (!out || !valid(samples, count, horizon, season, coverage))
        return FINPRED_SERIES_ERROR;
    struct finpred_series_prediction prediction = {0};
    enum finpred_series_status status = point(samples, count, count - 1 + horizon, season, &prediction.point);
    if (status != FINPRED_SERIES_OK)
        return status;
    int64_t past_errors[FINPRED_SERIES_MAX_OBSERVATIONS];
    for (size_t target = 0; target < count; ++target) {
        int64_t fitted;
        size_t train;
        status = historical(samples, target, horizon, season, &train, &fitted);
        if (status == FINPRED_SERIES_ERROR)
            return status;
        past_errors[target] = status == FINPRED_SERIES_OK ? magnitude(fitted - samples[target]) : -1;
    }
    if (!interval(past_errors, count, coverage, &prediction))
        return FINPRED_SERIES_ERROR;
    *out = prediction;
    return FINPRED_SERIES_OK;
}

static void score(const struct finpred_series_fold *fold, unsigned coverage, struct finpred_series_metrics *m)
{
    const struct finpred_series_prediction *p = &fold->prediction;
    ++m->point_count;
    m->absolute_error_sum += magnitude(p->point - fold->actual);
    if (!p->has_interval)
        return;
    ++m->interval_count;
    int64_t width = p->upper - p->lower, miss = 0;
    m->interval_width_sum += width;
    if (fold->actual < p->lower)
        miss = p->lower - fold->actual;
    else if (fold->actual > p->upper)
        miss = fold->actual - p->upper;
    else
        ++m->covered_count;
    m->interval_score_sum += width + (200 / (100 - coverage)) * miss;
}

int finpred_series_evaluate(const int64_t *samples, size_t count, size_t horizon, size_t season,
    unsigned coverage, size_t first_target, struct finpred_series_fold *folds, size_t fold_capacity,
    struct finpred_series_metrics *out)
{
    if (!folds || !out || !valid(samples, count, horizon, season, coverage) ||
        first_target >= count || fold_capacity < count - first_target)
        return 0;
    struct finpred_series_fold results[FINPRED_SERIES_MAX_OBSERVATIONS];
    struct finpred_series_metrics metrics = {0};
    int64_t past_errors[FINPRED_SERIES_MAX_OBSERVATIONS];
    for (size_t target = 0; target < count; ++target) {
        struct finpred_series_fold fold = {.target = target, .actual = samples[target]};
        enum finpred_series_status status = historical(samples, target, horizon, season,
            &fold.training_count, &fold.prediction.point);
        if (status == FINPRED_SERIES_ERROR)
            return 0;
        fold.has_point = status == FINPRED_SERIES_OK;
        if (target >= first_target) {
            if (fold.has_point) {
                if (!interval(past_errors, fold.training_count, coverage, &fold.prediction))
                    return 0;
                score(&fold, coverage, &metrics);
            }
            results[target - first_target] = fold;
        }
        past_errors[target] = fold.has_point ? magnitude(fold.prediction.point - fold.actual) : -1;
    }
    for (size_t i = 0; i < count - first_target; ++i)
        folds[i] = results[i];
    *out = metrics;
    return 1;
}
