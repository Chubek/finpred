#ifndef FINPRED_SERIES_FORECAST_H
#define FINPRED_SERIES_FORECAST_H

#include <stddef.h>
#include <stdint.h>

#define FINPRED_SERIES_MAX_ABS INT64_C(1000000000000)
enum {
    FINPRED_SERIES_MAX_OBSERVATIONS = 256,
    FINPRED_SERIES_MAX_HORIZON = 365,
    FINPRED_SERIES_MAX_SEASON = 256
};

enum finpred_series_status {
    FINPRED_SERIES_ERROR = 0,
    FINPRED_SERIES_OK,
    FINPRED_SERIES_INSUFFICIENT
};

struct finpred_series_prediction {
    int64_t point, lower, upper;
    size_t calibration_count;
    int has_interval; /* Lower and upper are zero when unavailable. */
};

struct finpred_series_fold {
    size_t target, training_count;
    int64_t actual;
    int has_point;
    struct finpred_series_prediction prediction;
};

struct finpred_series_metrics {
    size_t point_count, interval_count, covered_count;
    int64_t absolute_error_sum, interval_width_sum, interval_score_sum;
};

/*
 * Input is one signed fixed-point series on a regular grid, oldest first.
 * Horizon 1 means the next index; season 1 disables phase grouping.
 * Coverage must be 80, 90 or 95 percent. Bounds are inclusive. No output is
 * changed on ERROR or INSUFFICIENT (fewer than 3 target-phase observations).
 */
enum finpred_series_status finpred_series_predict(const int64_t *samples, size_t count,
    size_t horizon, size_t season, unsigned coverage, struct finpred_series_prediction *out);

/*
 * Score targets [first_target, count) at the fixed horizon. Emits one fold
 * per target (including abstentions); fold_capacity must fit count-first_target.
 * Folds without points have a zero prediction. No output is changed on error.
 * Sums use the point/interval counts as their respective denominators.
 */
int finpred_series_evaluate(const int64_t *samples, size_t count, size_t horizon,
    size_t season, unsigned coverage, size_t first_target, struct finpred_series_fold *folds,
    size_t fold_capacity, struct finpred_series_metrics *out);

#endif
