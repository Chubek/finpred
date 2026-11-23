#include "sdk.h"

#include <stddef.h>
#include <string.h>

struct finpred_sdk_plugin_v1 {
    finpred_sdk_descriptor_v1 descriptor;
};

static const char *const inputs[] = {
    "hospitality.scenario@1", "hospitality.offer@1", "pricing.valuation@1"
};

/* Metadata for the built-in On1x package. tests/check_sdk.py compares this
 * compiled descriptor with plugins/yieldcraft/plugin.json. */
static const finpred_sdk_plugin_v1 yieldcraft = { .descriptor = {
    .sdk_version = FINPRED_SDK_ABI_V1,
    .name = "yieldcraft.percentile",
    .package_version = "1.0.0",
    .kind = "Strategy",
    .effect = "pure",
    .output_contract = "pricing.recommendation@1",
    .input_count = sizeof(inputs) / sizeof(inputs[0]),
    .input_contracts = inputs,
    .required_capabilities = 0,
    .csv_rows = 512, .rooms_per_property = 10, .maximum_rooms = 4,
    .adults = 8, .children = 8, .search_budget_max = 1000000
} };

finpred_sdk_status finpred_sdk_lookup_v1(uint32_t abi, const char *name,
                                        const finpred_sdk_plugin_v1 **out)
{
    if (!out) return FINPRED_SDK_INVALID;
    *out = NULL;
    if (!name) return FINPRED_SDK_INVALID;
    if (abi != FINPRED_SDK_ABI_V1) return FINPRED_SDK_INCOMPATIBLE;
    if (strcmp(name, yieldcraft.descriptor.name) != 0) return FINPRED_SDK_NOT_FOUND;
    *out = &yieldcraft;
    return FINPRED_SDK_OK;
}

const finpred_sdk_descriptor_v1 *finpred_sdk_describe_v1(const finpred_sdk_plugin_v1 *plugin)
{
    return plugin == &yieldcraft ? &yieldcraft.descriptor : NULL;
}

finpred_sdk_status finpred_sdk_check_v1(const finpred_sdk_plugin_v1 *plugin,
                                       const char *kind, const char *output_contract,
                                       const char *effect, const char *mode,
                                       uint64_t requested_capabilities)
{
    const finpred_sdk_descriptor_v1 *d = finpred_sdk_describe_v1(plugin);
    if (!d || !kind || !output_contract || !effect || !mode) return FINPRED_SDK_INVALID;
    if (strcmp(kind, d->kind) != 0 || strcmp(output_contract, d->output_contract) != 0)
        return FINPRED_SDK_INCOMPATIBLE;
    if (requested_capabilities != 0 || strcmp(effect, d->effect) != 0)
        return FINPRED_SDK_DENIED;
    if (strcmp(mode, "analysis") != 0 && strcmp(mode, "recommendation") != 0 &&
        strcmp(mode, "simulation") != 0) return FINPRED_SDK_DENIED;
    return FINPRED_SDK_OK;
}
