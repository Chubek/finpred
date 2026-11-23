#include "sdk_v2.h"

#include <stddef.h>
#include <string.h>

struct finpred_sdk_plugin_v2 {
    finpred_sdk_descriptor_v2 descriptor;
};

static const char *const drag_inputs[] = {"hospitality.scenario@1", "finpred.offers.csv@1"};
static const char *const drag_deps[] = {"finpred.core@1", "yieldcraft.asof-whole-stay-property-min@1"};
static const char *const yield_inputs[] = {"hospitality.scenario@1", "hospitality.offer@1", "pricing.valuation@1"};
static const char *const sheet_inputs[] = {"pricing.recommendation@1", "pricing.valuation@1"};
static const char *const sheet_deps[] = {"yieldcraft.percentile@1"};

#define NAMES(a) {sizeof(a) / sizeof((a)[0]), a}
static const finpred_sdk_plugin_v2 packages[] = {
    {.descriptor = {
        .sdk_version = 1, .name = "dragnet.frozen_csv", .package_version = "1.0.0",
        .kind = "Source", .output = "hospitality.offer@1", .mode = "analysis", .effect = "pure",
        .inputs = NAMES(drag_inputs), .dependencies = NAMES(drag_deps),
        .limits = {.csv_rows = 512, .bytes_per_input = 2000000}
    }},
    {.descriptor = {
        .sdk_version = 1, .name = "yieldcraft.percentile", .package_version = "1.0.0",
        .kind = "Strategy", .output = "pricing.recommendation@1", .mode = "recommendation", .effect = "pure",
        .inputs = NAMES(yield_inputs),
        .limits = {.csv_rows = 512, .rooms_per_property = 10, .maximum_rooms = 4,
                   .adults = 8, .children = 8, .search_budget_max = 1000000}
    }},
    {.descriptor = {
        .sdk_version = 1, .name = "poindexter.pricing-sheet", .package_version = "1.0.0",
        .kind = "View", .output = "poindexter.pricing-sheet@1", .mode = "analysis", .effect = "pure",
        .inputs = NAMES(sheet_inputs), .dependencies = NAMES(sheet_deps),
        .limits = {.runs_per_call = 1, .data_rows = 1, .columns = 11, .output_bytes_max = 512}
    }}
};

finpred_sdk_status finpred_sdk_lookup_v2(uint32_t abi, const char *name,
                                        const finpred_sdk_plugin_v2 **out)
{
    if (!out) return FINPRED_SDK_INVALID;
    *out = NULL;
    if (!name) return FINPRED_SDK_INVALID;
    if (abi != FINPRED_SDK_ABI_V2) return FINPRED_SDK_INCOMPATIBLE;
    for (size_t i = 0; i < sizeof(packages) / sizeof(packages[0]); ++i) {
        if (!strcmp(name, packages[i].descriptor.name)) {
            *out = &packages[i];
            return FINPRED_SDK_OK;
        }
    }
    return FINPRED_SDK_NOT_FOUND;
}

const finpred_sdk_descriptor_v2 *finpred_sdk_describe_v2(const finpred_sdk_plugin_v2 *plugin)
{
    for (size_t i = 0; i < sizeof(packages) / sizeof(packages[0]); ++i)
        if (plugin == &packages[i]) return &plugin->descriptor;
    return NULL;
}

static int contains(finpred_sdk_names_v2 xs, const char *s)
{
    for (uint32_t i = 0; i < xs.count; ++i)
        if (!strcmp(s, xs.items[i])) return 1;
    return 0;
}

static int valid(finpred_sdk_names_v2 xs)
{
    if (xs.count > 16 || (xs.count && !xs.items)) return 0;
    for (uint32_t i = 0; i < xs.count; ++i) {
        const char *s = xs.items[i];
        if (!s || !s[0]) return 0;
        size_t n = 0;
        while (n < 128 && s[n]) ++n;
        if (n == 128 || contains((finpred_sdk_names_v2){i, xs.items}, s)) return 0;
    }
    return 1;
}

static int subset(finpred_sdk_names_v2 required, finpred_sdk_names_v2 offered)
{
    for (uint32_t i = 0; i < required.count; ++i)
        if (!contains(offered, required.items[i])) return 0;
    return 1;
}

static int fits(finpred_sdk_limits_v2 p, finpred_sdk_limits_v2 h)
{
    return p.csv_rows <= h.csv_rows && p.bytes_per_input <= h.bytes_per_input &&
        p.rooms_per_property <= h.rooms_per_property && p.maximum_rooms <= h.maximum_rooms &&
        p.adults <= h.adults && p.children <= h.children && p.search_budget_max <= h.search_budget_max &&
        p.runs_per_call <= h.runs_per_call && p.data_rows <= h.data_rows &&
        p.columns <= h.columns && p.output_bytes_max <= h.output_bytes_max;
}

finpred_sdk_status finpred_sdk_check_v2(const finpred_sdk_plugin_v2 *plugin,
                                       const finpred_sdk_use_v2 *use,
                                       const finpred_sdk_host_v2 *host)
{
    const finpred_sdk_descriptor_v2 *d = finpred_sdk_describe_v2(plugin);
    if (!d || !use || !host || !use->package_version || !use->kind || !use->output ||
        !use->mode || !use->effect || !valid(use->inputs) || !valid(use->requested) ||
        !valid(host->dependencies) || !valid(host->grants)) return FINPRED_SDK_INVALID;
    if (use->sdk_version != d->sdk_version || strcmp(use->package_version, d->package_version) ||
        strcmp(use->kind, d->kind) || strcmp(use->output, d->output) ||
        use->inputs.count != d->inputs.count || !subset(d->dependencies, host->dependencies) ||
        !fits(d->limits, host->ceilings)) return FINPRED_SDK_INCOMPATIBLE;
    for (uint32_t i = 0; i < use->inputs.count; ++i)
        if (strcmp(use->inputs.items[i], d->inputs.items[i])) return FINPRED_SDK_INCOMPATIBLE;
    if (strcmp(use->mode, d->mode) || strcmp(use->effect, d->effect) ||
        !subset(use->requested, host->grants) || !subset(use->requested, d->capabilities) ||
        !subset(d->capabilities, use->requested)) return FINPRED_SDK_DENIED;
    return FINPRED_SDK_OK;
}
