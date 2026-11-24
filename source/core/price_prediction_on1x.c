/* Trusted, private C11 companion for core.price_prediction. No On1x callers
   exchange native structs, floating-point values, or unmanaged pointers. */
#include "price_prediction.h"
#include "on1x_runtime.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static int decimal(const char **cursor, const char *end, char delimiter,
                   int64_t limit, int64_t *out)
{
    const char *start = *cursor, *s = start;
    int64_t value = 0;
    while (s < end && *s >= '0' && *s <= '9') {
        int digit = *s++ - '0';
        if (value > limit / 10 || (value == limit / 10 && digit > limit % 10))
            return 0;
        value = 10 * value + digit;
    }
    if (s == start || s == end || *s != delimiter || (*start == '0' && s - start != 1))
        return 0;
    *cursor = s + 1;
    *out = value;
    return 1;
}

static enum finpred_price_model parse_model(const char *model)
{
    if (strcmp(model, "naive") == 0) return FINPRED_PRICE_NAIVE;
    if (strcmp(model, "ema") == 0) return FINPRED_PRICE_EMA;
    if (strcmp(model, "drift") == 0) return FINPRED_PRICE_DRIFT;
    if (strcmp(model, "seasonal") == 0) return FINPRED_PRICE_SEASONAL;
    if (strcmp(model, "holt") == 0) return FINPRED_PRICE_HOLT;
    if (strcmp(model, "ensemble") == 0) return FINPRED_PRICE_ENSEMBLE;
    return 0;
}

static size_t parse_history(const char *history, int64_t *prices)
{
    static const char header[] = "period,price_minor\n";
    const int64_t bytes = on1x_text_len(history);
    if (bytes <= (int64_t)(sizeof header - 1) || bytes > 5000 ||
        memcmp(history, header, sizeof header - 1) != 0)
        return 0;

    const char *cursor = history + sizeof header - 1, *end = history + bytes;
    size_t n = 0;
    while (cursor != end) {
        int64_t period;
        if (n == FINPRED_PRICE_MAX_OBSERVATIONS ||
            !decimal(&cursor, end, ',', FINPRED_PRICE_MAX_OBSERVATIONS - 1, &period) ||
            period != (int64_t)n ||
            !decimal(&cursor, end, '\n', FINPRED_PRICE_MAX_MINOR, &prices[n]))
            return 0;
        ++n;
    }
    return n;
}

int64_t finpred_on1x_price_history_count(const char *history)
{
    int64_t prices[FINPRED_PRICE_MAX_OBSERVATIONS];
    return (int64_t)parse_history(history, prices);
}

const char *finpred_on1x_price_predict(const char *history, const char *model_name,
                                      int64_t horizon, int64_t season)
{
    const enum finpred_price_model model = parse_model(model_name);
    if (!model || horizon < 1 || horizon > FINPRED_PRICE_MAX_HORIZON ||
        (model == FINPRED_PRICE_SEASONAL
         ? (season < 2 || season > FINPRED_PRICE_MAX_OBSERVATIONS) : season != 0))
        return "invalid-request";

    int64_t prices[FINPRED_PRICE_MAX_OBSERVATIONS];
    const size_t n = parse_history(history, prices);
    if (!n)
        return "invalid-history";
    struct finpred_price_prediction result;
    if (!finpred_price_predict(prices, n, (size_t)horizon, model, (size_t)season, &result))
        return "model-rejected";

    char wire[96];
    int len = snprintf(wire, sizeof wire, "%zu,%" PRId64 ",%" PRId64,
                       n, result.point_minor, result.dispersion_minor);
    if (len < 0 || (size_t)len >= sizeof wire)
        return "internal-error";
    return on1x_text_slice(wire, 0, len);
}

const char *finpred_on1x_price_measure(const char *rows)
{
    const int64_t len = on1x_text_len(rows);
    if (len < 1 || len > FINPRED_PRICE_MAX_OBSERVATIONS * 32)
        return "internal-error";
    const char *cursor = rows, *end = rows + len;
    struct finpred_price_pair pairs[FINPRED_PRICE_MAX_OBSERVATIONS];
    size_t n = 0;
    while (cursor != end) {
        if (n == FINPRED_PRICE_MAX_OBSERVATIONS ||
            !decimal(&cursor, end, ',', FINPRED_PRICE_MAX_POINT, &pairs[n].predicted) ||
            !decimal(&cursor, end, '\n', FINPRED_PRICE_MAX_MINOR, &pairs[n].actual))
            return "internal-error";
        ++n;
    }
    struct finpred_price_metrics m;
    if (!finpred_price_measure(pairs, n, &m))
        return "internal-error";
    char wire[160];
    int written = snprintf(wire, sizeof wire, "%" PRId64 ",%s,%" PRId64 ",%" PRId64 ",%s",
                           m.absolute_sum, m.square_sum, m.signed_sum, m.actual_sum, m.rmse);
    if (written < 0 || (size_t)written >= sizeof wire)
        return "internal-error";
    return on1x_text_slice(wire, 0, written);
}
