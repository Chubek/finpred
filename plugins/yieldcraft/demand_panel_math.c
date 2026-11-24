#include <math.h>

#define MULIB_IMPL_PRICEOPT
#include "mulib-priceopt.h"

double yieldcraft_panel_log(double x) { return log(x); }
double yieldcraft_panel_exp(double x) { return exp(x); }
double yieldcraft_panel_sqrt(double x) { return sqrt(x); }

double yieldcraft_panel_isoelastic(double rate, double shape, double relative_price)
{
    const mulib_priceopt_demand_model_t model = {MULIB_PRICEOPT_ISOELASTIC, rate, shape, 1.0};
    return mulib_priceopt_demand(&model, relative_price);
}
