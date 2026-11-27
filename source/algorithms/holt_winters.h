#ifndef FINPRED_HOLT_WINTERS_H
#define FINPRED_HOLT_WINTERS_H

#include "series_forecast.h"

enum {
    FINPRED_HW_MAX_SEASON = FINPRED_SERIES_MAX_OBSERVATIONS / 2,
    FINPRED_HW_MAX_CANDIDATES = 16,
    FINPRED_HW_MIN_SELECTION_ERRORS = 3
};

struct finpred_hw_config {
    double alpha, beta, gamma; /* Each in [0, 1]. */
    double phi;                /* Trend damping in (0, 1]. */
};

struct finpred_hw_prediction {
    double point, level, trend, seasonal; /* Seasonal component of the target phase. */
    size_t candidate_index, selection_count;
    double selection_absolute_error_sum; /* Inner walk-forward loss, not outer evaluation. */
};

struct finpred_hw_fold {
    size_t target, training_count;
    int64_t actual;
    int has_point;
    struct finpred_hw_prediction prediction;
};

struct finpred_hw_metrics {
    size_t point_count;
    double absolute_error_sum;
};

/*
 * Equally spaced signed fixed-point observations, oldest first. Observation and
 * horizon limits are the same as the series API. Season is 2..MAX_SEASON.
 * One configuration is fixed; multiple configurations are ranked by absolute
 * error sum at the requested horizon using only actuals in the current prefix.
 * The first candidate wins exact ties. Each fit needs two full cycles, and
 * selection from multiple candidates needs MIN_SELECTION_ERRORS realized errors.
 * Returns an unrounded signed point. No output changes on error or abstention.
 */
enum finpred_series_status finpred_hw_predict(const int64_t *samples, size_t count,
    size_t horizon, size_t season, const struct finpred_hw_config *candidates,
    size_t candidate_count, struct finpred_hw_prediction *out);

/*
 * Emits one row per target in [first_target, count), including abstentions
 * (zero prediction). Fits and selects anew at each origin as if only its prefix
 * were available. Metrics score the selected points, with point_count as the
 * denominator. Returns 0 and leaves both outputs unchanged on error. The
 * fold and metric output regions must not overlap.
 */
int finpred_hw_evaluate(const int64_t *samples, size_t count, size_t horizon,
    size_t season, const struct finpred_hw_config *candidates, size_t candidate_count,
    size_t first_target, struct finpred_hw_fold *folds, size_t fold_capacity,
    struct finpred_hw_metrics *out);

#endif
