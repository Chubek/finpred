#ifndef FINPRED_PRICE_PREDICTION_H
#define FINPRED_PRICE_PREDICTION_H

#include <stddef.h>
#include <stdint.h>

enum {
    FINPRED_PRICE_MAX_OBSERVATIONS = 256,
    FINPRED_PRICE_MAX_HORIZON = 365
};
#define FINPRED_PRICE_MAX_MINOR INT64_C(1000000000000)
#define FINPRED_PRICE_MAX_POINT (FINPRED_PRICE_MAX_MINOR * (FINPRED_PRICE_MAX_HORIZON + 1))

enum finpred_price_model {
    FINPRED_PRICE_NAIVE = 1,
    FINPRED_PRICE_EMA,
    FINPRED_PRICE_DRIFT,
    FINPRED_PRICE_SEASONAL,
    FINPRED_PRICE_HOLT,
    FINPRED_PRICE_ENSEMBLE
};

struct finpred_price_prediction {
    int64_t point_minor;
    int64_t dispersion_minor; /* -1 unless the model is the ensemble. */
};

/* Prices must be equally spaced, oldest first, for one comparable series.
   Horizon is relative to the last observation; season is zero unless seasonal.
   Returns 1 on success, 0 on rejection and leaves *out unchanged on failure. */
int finpred_price_predict(const int64_t *prices, size_t count, size_t horizon,
                          enum finpred_price_model model, size_t season,
                          struct finpred_price_prediction *out);

struct finpred_price_pair {
    int64_t predicted, actual;
};

struct finpred_price_metrics {
    int64_t absolute_sum, signed_sum, actual_sum;
    char square_sum[46];
    char rmse[32];
};

/* Score 1–256 rounded forecast/actual pairs; output unchanged on failure.
   Square sum is exact decimal; RMSE is rounded half-up to 0.001 minor units. */
int finpred_price_measure(const struct finpred_price_pair *pairs, size_t count,
                          struct finpred_price_metrics *out);

#endif
