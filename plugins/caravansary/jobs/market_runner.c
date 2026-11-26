#include "market.h"
#include "http/probe/supervised.h"

int main(int argc, const char **argv)
{
    basis_http_probe_context keys;
    if (basis_http_probe_decode_child(argc, argv, JOB_MARKET_RUNNER, &keys) !=
        BASIS_HTTP_PROBE_JOB_OK) return 2;
    job_state state;
    if (job_state_child(&state, true) < 0) return 2;
    if (job_resolves(&state, &keys)) (void)job_market_exec(&state, keys.probe);
    job_state_close(&state);
    return 2;
}
