#ifndef FINPRED_SDK_H
#define FINPRED_SDK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FINPRED_SDK_ABI_V1 UINT32_C(1)
typedef int32_t finpred_sdk_status;
#define FINPRED_SDK_OK             INT32_C(0)
#define FINPRED_SDK_INVALID        INT32_C(1)
#define FINPRED_SDK_INCOMPATIBLE   INT32_C(2)
#define FINPRED_SDK_NOT_FOUND      INT32_C(3)
#define FINPRED_SDK_DENIED         INT32_C(4)

typedef struct finpred_sdk_plugin_v1 finpred_sdk_plugin_v1;

/* Frozen v1 native layout. Strings are NUL-terminated, read-only UTF-8.
 * The library owns the descriptor, its arrays and its strings. */
typedef struct {
    uint32_t sdk_version;
    const char *name;
    const char *package_version;
    const char *kind;
    const char *effect;
    const char *output_contract;
    uint32_t input_count;
    const char *const *input_contracts;
    uint64_t required_capabilities;
    uint32_t csv_rows;
    uint32_t rooms_per_property;
    uint32_t maximum_rooms;
    uint32_t adults;
    uint32_t children;
    uint32_t search_budget_max;
} finpred_sdk_descriptor_v1;

/* On failure, *out is NULL. On success it is a borrowed opaque handle,
 * valid until the library is unloaded. No close/free is required. */
finpred_sdk_status finpred_sdk_lookup_v1(uint32_t abi, const char *name,
                                        const finpred_sdk_plugin_v1 **out);

/* NULL for an invalid handle. Same borrowed lifetime as the handle. */
const finpred_sdk_descriptor_v1 *finpred_sdk_describe_v1(const finpred_sdk_plugin_v1 *plugin);

/* Check a caller's expected contract and requested behaviour. No resources
 * are granted and no code is invoked. All string arguments must be valid
 * NUL-terminated strings for the duration of the call. */
finpred_sdk_status finpred_sdk_check_v1(const finpred_sdk_plugin_v1 *plugin,
                                       const char *kind, const char *output_contract,
                                       const char *effect, const char *mode,
                                       uint64_t requested_capabilities);

#ifdef __cplusplus
}
#endif
#endif
