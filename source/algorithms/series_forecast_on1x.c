/* Private C11 companion; only managed strings and i64 values cross the ABI. */
#include "series_forecast.h"
#include "on1x_runtime.h"

#include <inttypes.h>
#include <stdio.h>

static size_t parse(const char *text, int64_t *values)
{
    int64_t len = on1x_text_len(text);
    if (len <= 0 || len > FINPRED_SERIES_MAX_OBSERVATIONS * 15)
        return 0;
    const char *end = text + len;
    size_t n = 0;
    while (text != end) {
        if (n == FINPRED_SERIES_MAX_OBSERVATIONS)
            return 0;
        int negative = *text == '-';
        text += negative;
        const char *start = text;
        int64_t value = 0;
        while (text != end && *text >= '0' && *text <= '9') {
            int digit = *text++ - '0';
            if (value > (FINPRED_SERIES_MAX_ABS - digit) / 10)
                return 0;
            value = 10 * value + digit;
        }
        if (text == start || text == end || *text != '\n' ||
            (*start == '0' && (negative || text - start > 1)))
            return 0;
        ++text;
        values[n++] = negative ? -value : value;
    }
    return n;
}

static int request(int64_t horizon, int64_t season, int64_t coverage)
{
    return horizon >= 1 && horizon <= FINPRED_SERIES_MAX_HORIZON &&
           season >= 1 && season <= FINPRED_SERIES_MAX_SEASON &&
           (coverage == 80 || coverage == 90 || coverage == 95);
}

const char *finpred_on1x_series_predict(const char *text, int64_t horizon, int64_t season, int64_t coverage)
{
    if (!request(horizon, season, coverage))
        return "invalid-request";
    int64_t values[FINPRED_SERIES_MAX_OBSERVATIONS];
    size_t n = parse(text, values);
    if (!n)
        return "invalid-history";
    struct finpred_series_prediction p;
    enum finpred_series_status status = finpred_series_predict(values, n, (size_t)horizon,
        (size_t)season, (unsigned)coverage, &p);
    if (status == FINPRED_SERIES_INSUFFICIENT)
        return "insufficient-training";
    if (status != FINPRED_SERIES_OK)
        return "internal-error";
    char wire[96];
    int len = snprintf(wire, sizeof wire, "%" PRId64 ",%zu,%d,%" PRId64 ",%" PRId64,
        p.point, p.calibration_count, p.has_interval, p.lower, p.upper);
    if (len < 0 || (size_t)len >= sizeof wire)
        return "internal-error";
    return on1x_text_slice(wire, 0, len);
}

const char *finpred_on1x_series_evaluate(const char *text, int64_t horizon, int64_t season,
                                       int64_t coverage, int64_t first)
{
    if (!request(horizon, season, coverage) || first < 0 || first >= FINPRED_SERIES_MAX_OBSERVATIONS)
        return "invalid-request";
    int64_t values[FINPRED_SERIES_MAX_OBSERVATIONS];
    size_t n = parse(text, values);
    if (!n)
        return "invalid-history";
    if ((size_t)first >= n)
        return "invalid-request";
    struct finpred_series_fold folds[FINPRED_SERIES_MAX_OBSERVATIONS];
    struct finpred_series_metrics m;
    if (!finpred_series_evaluate(values, n, (size_t)horizon, (size_t)season, (unsigned)coverage,
            (size_t)first, folds, FINPRED_SERIES_MAX_OBSERVATIONS, &m))
        return "internal-error";
    char wire[128 + FINPRED_SERIES_MAX_OBSERVATIONS * 96];
    int len = snprintf(wire, sizeof wire, "%zu,%zu,%zu,%" PRId64 ",%" PRId64 ",%" PRId64 "\n",
        m.point_count, m.interval_count, m.covered_count, m.absolute_error_sum,
        m.interval_width_sum, m.interval_score_sum);
    if (len < 0 || (size_t)len >= sizeof wire)
        return "internal-error";
    size_t used = (size_t)len;
    for (size_t i = 0; i < n - (size_t)first; ++i) {
        const struct finpred_series_fold *f = &folds[i];
        const struct finpred_series_prediction *p = &f->prediction;
        len = snprintf(wire + used, sizeof wire - used,
            "%zu,%zu,%" PRId64 ",%d,%" PRId64 ",%zu,%d,%" PRId64 ",%" PRId64 "\n",
            f->target, f->training_count, f->actual, f->has_point, p->point, p->calibration_count,
            p->has_interval, p->lower, p->upper);
        if (len < 0 || (size_t)len >= sizeof wire - used)
            return "internal-error";
        used += (size_t)len;
    }
    return on1x_text_slice(wire, 0, (int64_t)used);
}
