#ifndef FINPRED_PRICE_PREDICTION_H
#define FINPRED_PRICE_PREDICTION_H

#include <stddef.h>
#include <stdint.h>

enum {
    FINPRED_PRICE_MAX_OBSERVATIONS = 256,
    FINPRED_PRICE_MAX_HORIZON = 365
};
#define FINPRED_PRICE_MAX_MINOR INT64_C(1000000000000)

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

#endif
