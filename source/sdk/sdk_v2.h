#ifndef FINPRED_SDK_V2_H
#define FINPRED_SDK_V2_H

#include "sdk.h"

#ifdef __cplusplus
extern "C" {
#endif

#define FINPRED_SDK_ABI_V2 UINT32_C(2)

typedef struct {
    uint32_t count;
    const char *const *items;
} finpred_sdk_names_v2;

typedef struct {
    uint32_t csv_rows, bytes_per_input, rooms_per_property, maximum_rooms;
    uint32_t adults, children, search_budget_max, runs_per_call, data_rows;
    uint32_t columns, output_bytes_max;
} finpred_sdk_limits_v2;

typedef struct {
    uint32_t sdk_version; /* package manifest SDK, independent of C ABI */
    const char *name, *package_version, *kind, *output, *mode, *effect;
    finpred_sdk_names_v2 inputs, dependencies, capabilities;
    finpred_sdk_limits_v2 limits;
} finpred_sdk_descriptor_v2;

typedef struct {
    uint32_t sdk_version;
    const char *package_version, *kind, *output, *mode, *effect;
    finpred_sdk_names_v2 inputs, requested;
} finpred_sdk_use_v2;

typedef struct {
    finpred_sdk_names_v2 dependencies, grants;
    finpred_sdk_limits_v2 ceilings;
} finpred_sdk_host_v2;

typedef struct finpred_sdk_plugin_v2 finpred_sdk_plugin_v2;

/* Borrowed static handles/descriptors, valid for this library's lifetime.
 * Failed lookup clears *out; describe returns NULL for an unknown handle. */
finpred_sdk_status finpred_sdk_lookup_v2(uint32_t abi, const char *name,
                                        const finpred_sdk_plugin_v2 **out);
const finpred_sdk_descriptor_v2 *finpred_sdk_describe_v2(const finpred_sdk_plugin_v2 *plugin);

/* Caller owns valid, immutable arrays/strings for the duration of the call;
 * names are distinct NUL-terminated strings of 1..127 bytes, <=16 per list.
 * Host supplies its own ceilings, dependency inventory and grants. No callbacks,
 * execution, handles to host resources or authority tokens are returned. */
finpred_sdk_status finpred_sdk_check_v2(const finpred_sdk_plugin_v2 *plugin,
                                       const finpred_sdk_use_v2 *use,
                                       const finpred_sdk_host_v2 *host);

#ifdef __cplusplus
}
#endif
#endif
