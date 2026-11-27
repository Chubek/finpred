#include "holt_winters.h"

#include <math.h>

/* Reject rather than clipping, silently dropping a candidate, or changing models. */
#define STATE_LIMIT (1024.L * FINPRED_SERIES_MAX_ABS)

_Static_assert(FINPRED_SERIES_MAX_ABS <= INT64_MAX / (2 * FINPRED_HW_MAX_SEASON),
               "the two initialization cycle sums must fit");

struct model {
    long double level, trend, phase[FINPRED_HW_MAX_SEASON];
    long double drift, loss;
    double points[FINPRED_SERIES_MAX_OBSERVATIONS + 1]; /* By origin prefix length. */
};

static int unit(double x)
{
    return x >= 0 && x <= 1;
}

static int valid(const int64_t *samples, size_t count, size_t horizon, size_t season,
    const struct finpred_hw_config *candidates, size_t candidate_count)
{
    if (!samples || !count || count > FINPRED_SERIES_MAX_OBSERVATIONS || !horizon ||
        horizon > FINPRED_SERIES_MAX_HORIZON || season < 2 || season > FINPRED_HW_MAX_SEASON ||
        !candidates || !candidate_count || candidate_count > FINPRED_HW_MAX_CANDIDATES)
        return 0;
    for (size_t i = 0; i < candidate_count; ++i) {
        const struct finpred_hw_config *c = &candidates[i];
        if (!unit(c->alpha) || !unit(c->beta) || !unit(c->gamma) || !unit(c->phi) || c->phi <= 0)
            return 0;
    }
    for (size_t i = 0; i < count; ++i)
        if (samples[i] < -FINPRED_SERIES_MAX_ABS || samples[i] > FINPRED_SERIES_MAX_ABS)
            return 0;
    return 1;
}

static void initialize(struct model *m, const int64_t *samples, size_t season)
{
    int64_t sum0 = 0, sum1 = 0;
    for (size_t j = 0; j < season; ++j) {
        sum0 += samples[j];
        sum1 += samples[j + season];
    }
    m->trend = (long double)(sum1 - sum0) / (season * season);
    long double mean = (long double)(sum0 + sum1) / (2 * season);
    m->level = mean + m->trend * (2 * season - 1) / 2;
    for (size_t j = 0; j < season; ++j)
        m->phase[j] = (long double)(samples[j] + samples[j + season]) / 2 - mean -
            m->trend * ((long double)j - ((long double)season - 1) / 2);
    m->loss = 0;
}

static int update(struct model *m, const struct finpred_hw_config *c, size_t j, int64_t actual)
{
    long double prev_level = m->level, damped = (long double)c->phi * m->trend;
    long double old_season = m->phase[j];
    /* Innovation form of additive smoothing (seasonal update uses the new level). */
    long double innovation = actual - (prev_level + damped + old_season);
    long double correction = (long double)c->alpha * innovation;
    m->level = (prev_level + damped) + correction;
    m->trend = damped + (long double)c->beta * correction;
    m->phase[j] = old_season + (long double)c->gamma * (innovation - correction);
    return fabsl(m->level) <= STATE_LIMIT && fabsl(m->trend) <= STATE_LIMIT &&
        fabsl(m->phase[j]) <= STATE_LIMIT;
}

static size_t minimum_origin(size_t horizon, size_t season, size_t candidate_count)
{
    return 2 * season + (candidate_count > 1 ? horizon + FINPRED_HW_MIN_SELECTION_ERRORS - 1 : 0);
}

/*
 * At prefix n, first admit the error whose actual just arrived (if its origin
 * was eligible). Then update and forecast from prefix n. No candidate gets to
 * use errors with a later actual time, even if their predictions already exist.
 */
static int walk(const int64_t *samples, size_t last_origin, size_t horizon, size_t season,
    const struct finpred_hw_config *candidates, size_t candidate_count,
    size_t first_target, struct finpred_hw_fold *folds, long double *outer_loss,
    size_t *outer_count, struct finpred_hw_prediction *next)
{
    const size_t initial = 2 * season;
    size_t minimum = minimum_origin(horizon, season, candidate_count);
    if (last_origin < minimum)
        return 1;

    struct model models[FINPRED_HW_MAX_CANDIDATES];
    for (size_t k = 0; k < candidate_count; ++k) {
        struct model *m = &models[k];
        initialize(m, samples, season);
        long double phi = candidates[k].phi;
        m->drift = 0;
        for (size_t h = 0; h < horizon; ++h)
            m->drift = phi * (1 + m->drift); /* phi + ... + phi^h, including phi == 1. */
    }

    size_t losses = 0;
    for (size_t n = initial; n <= last_origin; ++n) {
        size_t target = n - 1 + horizon, phase = target % season, winner = 0;
        int realized = n >= initial + horizon;
        if (realized)
            ++losses;
        for (size_t k = 0; k < candidate_count; ++k) {
            struct model *m = &models[k];
            if (realized)
                m->loss += fabsl((long double)m->points[n - horizon] - samples[n - 1]);
            if (n > initial && !update(m, &candidates[k], (n - 1) % season, samples[n - 1]))
                return 0;
            m->points[n] = (double)(m->level + m->drift * m->trend + m->phase[phase]);
            if (m->loss < models[winner].loss)
                winner = k;
        }
        if (n < minimum)
            continue;
        const struct model *m = &models[winner];
        struct finpred_hw_prediction p = {
            .point = m->points[n], .level = (double)m->level, .trend = (double)m->trend,
            .seasonal = (double)m->phase[phase], .candidate_index = winner,
            .selection_count = losses, .selection_absolute_error_sum = (double)m->loss
        };
        if (folds && target >= first_target) {
            struct finpred_hw_fold *f = &folds[target - first_target];
            f->prediction = p;
            f->has_point = 1;
            *outer_loss += fabsl((long double)p.point - f->actual);
            ++*outer_count;
        }
        if (next && n == last_origin)
            *next = p;
    }
    return 1;
}

enum finpred_series_status finpred_hw_predict(const int64_t *samples, size_t count,
    size_t horizon, size_t season, const struct finpred_hw_config *candidates,
    size_t candidate_count, struct finpred_hw_prediction *out)
{
    if (!out || !valid(samples, count, horizon, season, candidates, candidate_count))
        return FINPRED_SERIES_ERROR;
    if (count < minimum_origin(horizon, season, candidate_count))
        return FINPRED_SERIES_INSUFFICIENT;
    struct finpred_hw_prediction result;
    if (!walk(samples, count, horizon, season, candidates, candidate_count, 0,
              NULL, NULL, NULL, &result))
        return FINPRED_SERIES_ERROR;
    *out = result;
    return FINPRED_SERIES_OK;
}

int finpred_hw_evaluate(const int64_t *samples, size_t count, size_t horizon,
    size_t season, const struct finpred_hw_config *candidates, size_t candidate_count,
    size_t first_target, struct finpred_hw_fold *folds, size_t fold_capacity,
    struct finpred_hw_metrics *out)
{
    if (!folds || !out || first_target >= count || fold_capacity < count - first_target ||
        !valid(samples, count, horizon, season, candidates, candidate_count))
        return 0;
    struct finpred_hw_fold results[FINPRED_SERIES_MAX_OBSERVATIONS];
    for (size_t t = first_target; t < count; ++t)
        results[t - first_target] = (struct finpred_hw_fold){
            .target = t, .training_count = t >= horizon ? t - horizon + 1 : 0, .actual = samples[t]
        };
    size_t last_origin = count >= horizon ? count - horizon : 0;
    size_t point_count = 0;
    long double loss = 0;
    if (!walk(samples, last_origin, horizon, season, candidates, candidate_count, first_target,
              results, &loss, &point_count, NULL))
        return 0;
    for (size_t i = 0; i < count - first_target; ++i)
        folds[i] = results[i];
    *out = (struct finpred_hw_metrics){point_count, (double)loss};
    return 1;
}
