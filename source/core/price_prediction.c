#include "price_prediction.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <mulib-histprice.h>
#include <mulib-price-ensemble.h>
#include <mulib-price-forecast.h>

/* Version 1 parameters. Fit and scoring always use the same alpha. */
static const double alpha = 0.5;
static const double holt_beta = 0.2;

static int ensemble(const double *samples, size_t n, size_t horizon,
                    double *point, double *dispersion)
{
    const mulib_price_forecast_model_t models[] = {
        MULIB_PRICE_FORECAST_NAIVE, MULIB_PRICE_FORECAST_EMA, MULIB_PRICE_FORECAST_DRIFT
    };
    double points[3], errors[3];
    /* Each model is weighted by one-step, expanding-window MAE over the same
       origins, starting with two observations. No future samples are fitted. */
    for (size_t i = 0; i < sizeof models / sizeof models[0]; ++i) {
        if (!mulib_price_forecast(samples, n, horizon, models[i], alpha, 0, &points[i]) ||
            !mulib_price_forecast_mae(samples, n, models[i], alpha, 0, &errors[i]))
            return 0;
    }
    return mulib_price_ensemble_blend(points, errors, 3, point, dispersion) == 1;
}

static int round_minor(double value, int64_t *out)
{
    /* A (horizon + 1) * max input bound covers these baseline predictions
       and their dispersion; the bound is below double's exact integer range. */
    if (!isfinite(value) || value < 0 ||
        value > (double)FINPRED_PRICE_MAX_POINT)
        return 0;
    *out = (int64_t)round(value);
    return 1;
}

/* The largest square sum is 256 * (366e12)^2. Even after the extra
   factor 4e6 for the RMSE midpoint test it fits 5 base-1e9 limbs. */
#define RADIX UINT64_C(1000000000)
enum { WIDE_LIMBS = 5, RMSE_SCALE = 1000 };
struct wide { uint32_t limb[WIDE_LIMBS]; };

_Static_assert(FINPRED_PRICE_MAX_POINT <= INT64_MAX / FINPRED_PRICE_MAX_OBSERVATIONS,
               "absolute, signed and actual sums must fit int64_t");
_Static_assert(FINPRED_PRICE_MAX_POINT <= (RADIX * RADIX - 1) / (2 * RMSE_SCALE),
               "RMSE midpoint must fit the square routine's input");

static int wide_square(uint64_t x, struct wide *out)
{
    if (x >= RADIX * RADIX)
        return 0;
    uint64_t a = x % RADIX, b = x / RADIX;
    uint64_t p = a * a;
    out->limb[0] = p % RADIX;
    p = p / RADIX + 2 * a * b;
    out->limb[1] = p % RADIX;
    p = p / RADIX + b * b;
    out->limb[2] = p % RADIX;
    out->limb[3] = p / RADIX;
    out->limb[4] = 0;
    return 1;
}

static int wide_add(struct wide *sum, const struct wide *other)
{
    uint64_t carry = 0;
    for (size_t i = 0; i < WIDE_LIMBS; ++i) {
        uint64_t digit = carry + sum->limb[i] + other->limb[i];
        sum->limb[i] = digit % RADIX;
        carry = digit / RADIX;
    }
    return carry == 0;
}

static int wide_scale(struct wide *x, uint32_t factor)
{
    uint64_t carry = 0;
    for (size_t i = 0; i < WIDE_LIMBS; ++i) {
        uint64_t digit = carry + (uint64_t)x->limb[i] * factor;
        x->limb[i] = digit % RADIX;
        carry = digit / RADIX;
    }
    return carry == 0;
}

static int wide_le(const struct wide *a, const struct wide *b)
{
    for (size_t i = WIDE_LIMBS; i-- > 0;)
        if (a->limb[i] != b->limb[i])
            return a->limb[i] < b->limb[i];
    return 1;
}

static int wide_print(const struct wide *x, char *out, size_t capacity)
{
    size_t i = WIDE_LIMBS - 1;
    while (i && !x->limb[i])
        --i;
    int n = snprintf(out, capacity, "%" PRIu32, x->limb[i]);
    if (n < 0 || (size_t)n >= capacity)
        return 0;
    size_t used = (size_t)n;
    while (i > 0) {
        n = snprintf(out + used, capacity - used, "%09" PRIu32, x->limb[--i]);
        if (n < 0 || (size_t)n >= capacity - used)
            return 0;
        used += (size_t)n;
    }
    return 1;
}

static int rounded_rmse(struct wide squares, uint32_t count, char *out, size_t capacity)
{
    /* Rounded sqrt(S/n) * scale is at least k iff
       n * (2*k-1)^2 <= 4 * scale^2 * S. No floating point or midpoint ambiguity. */
    if (!wide_scale(&squares, 4 * RMSE_SCALE * RMSE_SCALE))
        return 0;
    uint64_t lo = 0, hi = (uint64_t)FINPRED_PRICE_MAX_POINT * RMSE_SCALE;
    while (lo < hi) {
        uint64_t mid = lo + (hi - lo + 1) / 2;
        struct wide threshold;
        if (!wide_square(2 * mid - 1, &threshold) || !wide_scale(&threshold, count))
            return 0;
        if (wide_le(&threshold, &squares))
            lo = mid;
        else
            hi = mid - 1;
    }
    int n = snprintf(out, capacity, "%" PRIu64 ".%03" PRIu64,
                     lo / RMSE_SCALE, lo % RMSE_SCALE);
    return n >= 0 && (size_t)n < capacity;
}

int finpred_price_measure(const struct finpred_price_pair *pairs, size_t count,
                          struct finpred_price_metrics *out)
{
    if (!pairs || !out || count < 1 || count > FINPRED_PRICE_MAX_OBSERVATIONS)
        return 0;
    struct finpred_price_metrics result = {0};
    struct wide squares = {0};
    for (size_t i = 0; i < count; ++i) {
        int64_t point = pairs[i].predicted, actual = pairs[i].actual;
        if (point < 0 || point > FINPRED_PRICE_MAX_POINT ||
            actual < 0 || actual > FINPRED_PRICE_MAX_MINOR)
            return 0;
        int64_t error = point - actual, mag = error < 0 ? -error : error;
        result.signed_sum += error;
        result.absolute_sum += mag;
        result.actual_sum += actual;
        struct wide square;
        if (!wide_square((uint64_t)mag, &square) || !wide_add(&squares, &square))
            return 0;
    }
    if (!wide_print(&squares, result.square_sum, sizeof result.square_sum) ||
        !rounded_rmse(squares, (uint32_t)count, result.rmse, sizeof result.rmse))
        return 0;
    *out = result;
    return 1;
}

int finpred_price_predict(const int64_t *prices, size_t count, size_t horizon,
                          enum finpred_price_model model, size_t season,
                          struct finpred_price_prediction *out)
{
    if (!prices || !out || count < 1 || count > FINPRED_PRICE_MAX_OBSERVATIONS ||
        horizon < 1 || horizon > FINPRED_PRICE_MAX_HORIZON ||
        (model == FINPRED_PRICE_SEASONAL ? (season < 2 || season > count) : season != 0))
        return 0;

    double samples[FINPRED_PRICE_MAX_OBSERVATIONS];
    for (size_t i = 0; i < count; ++i) {
        if (prices[i] < 0 || prices[i] > FINPRED_PRICE_MAX_MINOR)
            return 0;
        samples[i] = (double)prices[i];
    }

    double point, dispersion;
    struct finpred_price_prediction result = {.dispersion_minor = -1};
    mulib_price_forecast_model_t baseline;
    switch (model) {
    case FINPRED_PRICE_NAIVE: baseline = MULIB_PRICE_FORECAST_NAIVE; break;
    case FINPRED_PRICE_EMA: baseline = MULIB_PRICE_FORECAST_EMA; break;
    case FINPRED_PRICE_DRIFT: baseline = MULIB_PRICE_FORECAST_DRIFT; break;
    case FINPRED_PRICE_SEASONAL: baseline = MULIB_PRICE_FORECAST_SEASONAL; break;
    case FINPRED_PRICE_HOLT: {
        mulib_histprice_forecast_t forecast;
        if (!mulib_histprice_holt(samples, count, alpha, holt_beta, 1, horizon, &forecast) ||
            !round_minor(forecast.point, &result.point_minor))
            return 0;
        *out = result;
        return 1;
    }
    case FINPRED_PRICE_ENSEMBLE:
        if (!ensemble(samples, count, horizon, &point, &dispersion) ||
            !round_minor(point, &result.point_minor) ||
            !round_minor(dispersion, &result.dispersion_minor))
            return 0;
        *out = result;
        return 1;
    default:
        return 0;
    }
    if (mulib_price_forecast(samples, count, horizon, baseline, alpha, season, &point) != 1 ||
        !round_minor(point, &result.point_minor))
        return 0;
    *out = result;
    return 1;
}
