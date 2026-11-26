#include "state.h"
#include "http/probe/supervised.h"

/* No network transport, paths from input, arbitrary workflow loader, or
 * outputs. The child independently validates the approved fixture bytes. */
int main(int argc, const char **argv)
{
    basis_http_probe_context keys;
    if (basis_http_probe_decode_child(argc, argv, JOB_RUNNER, &keys) != BASIS_HTTP_PROBE_JOB_OK)
        return 2;
    job_state state;
    if (job_state_child(&state, false) < 0) return 2;
    bool approved = job_resolves(&state, &keys);
    job_state_close(&state);
    return approved ? 0 : 2;
}
