#include "price_prediction.h"

#include <math.h>
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
        value > (double)FINPRED_PRICE_MAX_MINOR * (FINPRED_PRICE_MAX_HORIZON + 1))
        return 0;
    *out = (int64_t)round(value);
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
