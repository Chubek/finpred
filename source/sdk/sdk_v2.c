#include "sdk_diagnostic_v1.h"

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

static int bounded_text(const char *s, size_t limit)
{
    if (!s || !s[0]) return 0;
    for (size_t n = 1; n <= limit; ++n)
        if (!s[n]) return 1;
    return 0;
}

/* Expand the public constants at the use site so callers and the policy
 * cannot accidentally give different meanings to a result field. */
#define DIAG(status, reason, subject, field, index) \
    ((finpred_sdk_diagnostic_v1){FINPRED_SDK_##status, FINPRED_SDK_REASON_##reason, \
        FINPRED_SDK_SUBJECT_##subject, FINPRED_SDK_FIELD_##field, index})
#define NO_INDEX FINPRED_SDK_DIAG_NO_INDEX
#define OK DIAG(OK, NONE, NONE, NONE, NO_INDEX)

static finpred_sdk_diagnostic_v1 validate_names(finpred_sdk_names_v2 xs,
                                               uint32_t subject, uint32_t field)
{
    uint32_t index = NO_INDEX;
    uint32_t reason = FINPRED_SDK_REASON_NONE;
    if (xs.count > 16) reason = FINPRED_SDK_REASON_INVALID_VALUE;
    else if (xs.count && !xs.items) reason = FINPRED_SDK_REASON_NULL;
    else for (uint32_t i = 0; i < xs.count; ++i) {
        const char *s = xs.items[i];
        if (!s) reason = FINPRED_SDK_REASON_NULL;
        else if (!bounded_text(s, 127)) reason = FINPRED_SDK_REASON_INVALID_VALUE;
        else if (contains((finpred_sdk_names_v2){i, xs.items}, s))
            reason = FINPRED_SDK_REASON_DUPLICATE;
        if (reason != FINPRED_SDK_REASON_NONE) {
            index = i;
            break;
        }
    }
    if (reason == FINPRED_SDK_REASON_NONE) return OK;
    return (finpred_sdk_diagnostic_v1){FINPRED_SDK_INVALID, reason, subject, field, index};
}

static uint32_t first_missing(finpred_sdk_names_v2 required, finpred_sdk_names_v2 offered)
{
    for (uint32_t i = 0; i < required.count; ++i)
        if (!contains(offered, required.items[i])) return i;
    return NO_INDEX;
}

static finpred_sdk_diagnostic_v1 check_use(const finpred_sdk_descriptor_v2 *d,
                                           const finpred_sdk_use_v2 *use,
                                           const finpred_sdk_host_v2 *host)
{
    if (!use) return DIAG(INVALID, NULL, USE, NONE, NO_INDEX);
    if (!host) return DIAG(INVALID, NULL, HOST, NONE, NO_INDEX);
    if (!use->package_version) return DIAG(INVALID, NULL, USE, PACKAGE_VERSION, NO_INDEX);
    if (!use->kind) return DIAG(INVALID, NULL, USE, KIND, NO_INDEX);
    if (!use->output) return DIAG(INVALID, NULL, USE, OUTPUT, NO_INDEX);
    if (!use->mode) return DIAG(INVALID, NULL, USE, MODE, NO_INDEX);
    if (!use->effect) return DIAG(INVALID, NULL, USE, EFFECT, NO_INDEX);

    finpred_sdk_diagnostic_v1 r;
#define NAMES_OR_RETURN(list, subject, field) \
    r = validate_names(list, FINPRED_SDK_SUBJECT_##subject, FINPRED_SDK_FIELD_##field); \
    if (r.status != FINPRED_SDK_OK) return r
    NAMES_OR_RETURN(use->inputs, USE, INPUTS);
    NAMES_OR_RETURN(use->requested, USE, REQUESTED);
    NAMES_OR_RETURN(host->dependencies, HOST, DEPENDENCIES);
    NAMES_OR_RETURN(host->grants, HOST, GRANTS);
#undef NAMES_OR_RETURN

    if (use->sdk_version != d->sdk_version)
        return DIAG(INCOMPATIBLE, MISMATCH, USE, SDK_VERSION, NO_INDEX);
    if (strcmp(use->package_version, d->package_version))
        return DIAG(INCOMPATIBLE, MISMATCH, USE, PACKAGE_VERSION, NO_INDEX);
    if (strcmp(use->kind, d->kind)) return DIAG(INCOMPATIBLE, MISMATCH, USE, KIND, NO_INDEX);
    if (strcmp(use->output, d->output)) return DIAG(INCOMPATIBLE, MISMATCH, USE, OUTPUT, NO_INDEX);
    if (use->inputs.count != d->inputs.count)
        return DIAG(INCOMPATIBLE, MISMATCH, USE, INPUTS, NO_INDEX);
    uint32_t missing = first_missing(d->dependencies, host->dependencies);
    if (missing != NO_INDEX) return DIAG(INCOMPATIBLE, MISSING, HOST, DEPENDENCIES, missing);

#define CEILING(member, field) \
    if (d->limits.member > host->ceilings.member) \
        return DIAG(INCOMPATIBLE, EXCEEDS, HOST, field, NO_INDEX)
    CEILING(csv_rows, CSV_ROWS);
    CEILING(bytes_per_input, BYTES_PER_INPUT);
    CEILING(rooms_per_property, ROOMS_PER_PROPERTY);
    CEILING(maximum_rooms, MAXIMUM_ROOMS);
    CEILING(adults, ADULTS);
    CEILING(children, CHILDREN);
    CEILING(search_budget_max, SEARCH_BUDGET_MAX);
    CEILING(runs_per_call, RUNS_PER_CALL);
    CEILING(data_rows, DATA_ROWS);
    CEILING(columns, COLUMNS);
    CEILING(output_bytes_max, OUTPUT_BYTES_MAX);
#undef CEILING

    for (uint32_t i = 0; i < use->inputs.count; ++i)
        if (strcmp(use->inputs.items[i], d->inputs.items[i]))
            return DIAG(INCOMPATIBLE, MISMATCH, USE, INPUTS, i);
    if (strcmp(use->mode, d->mode)) return DIAG(DENIED, MISMATCH, USE, MODE, NO_INDEX);
    if (strcmp(use->effect, d->effect)) return DIAG(DENIED, MISMATCH, USE, EFFECT, NO_INDEX);
    missing = first_missing(use->requested, host->grants);
    if (missing != NO_INDEX) return DIAG(DENIED, NOT_GRANTED, HOST, GRANTS, missing);
    missing = first_missing(use->requested, d->capabilities);
    if (missing != NO_INDEX) return DIAG(DENIED, NOT_DECLARED, PACKAGE, CAPABILITIES, missing);
    missing = first_missing(d->capabilities, use->requested);
    if (missing != NO_INDEX) return DIAG(DENIED, MISSING, USE, REQUESTED, missing);
    return OK;
}

finpred_sdk_status finpred_sdk_check_v2(const finpred_sdk_plugin_v2 *plugin,
                                        const finpred_sdk_use_v2 *use,
                                        const finpred_sdk_host_v2 *host)
{
    const finpred_sdk_descriptor_v2 *d = finpred_sdk_describe_v2(plugin);
    return d ? check_use(d, use, host).status : FINPRED_SDK_INVALID;
}

finpred_sdk_status finpred_sdk_check_diagnostic_v1(const char *name,
                                                  const finpred_sdk_use_v2 *use,
                                                  const finpred_sdk_host_v2 *host,
                                                  finpred_sdk_diagnostic_v1 *out)
{
    const finpred_sdk_plugin_v2 *plugin;
    if (!out) return FINPRED_SDK_INVALID;
    if (!name) *out = DIAG(INVALID, NULL, PACKAGE, NAME, NO_INDEX);
    else if (finpred_sdk_lookup_v2(FINPRED_SDK_ABI_V2, name, &plugin) != FINPRED_SDK_OK)
        *out = DIAG(NOT_FOUND, NOT_FOUND, PACKAGE, NAME, NO_INDEX);
    else *out = check_use(&plugin->descriptor, use, host);
    return out->status;
}

static finpred_sdk_diagnostic_v1 validate_port(const finpred_sdk_port_v2 *p, uint32_t subject)
{
    uint32_t field, reason = FINPRED_SDK_REASON_INVALID_VALUE;
    if (!p) {
        field = FINPRED_SDK_FIELD_NONE;
        reason = FINPRED_SDK_REASON_NULL;
    }
#define PORT_TEXT(member, bound, id) \
    else if (!bounded_text(p->member, bound)) { \
        field = FINPRED_SDK_FIELD_##id; \
        if (!p->member) reason = FINPRED_SDK_REASON_NULL; \
    }
    PORT_TEXT(name, 63, NAME)
    PORT_TEXT(kind, 127, KIND)
    PORT_TEXT(unit, 63, UNIT)
    PORT_TEXT(currency, 31, CURRENCY)
#undef PORT_TEXT
    else if (!p->major || p->major > 999) field = FINPRED_SDK_FIELD_MAJOR;
    else if (!p->states || p->states > 31) field = FINPRED_SDK_FIELD_STATES;
    else if (!p->max_bytes || p->max_bytes > 2000000) field = FINPRED_SDK_FIELD_MAX_BYTES;
    else return OK;
    return (finpred_sdk_diagnostic_v1){FINPRED_SDK_INVALID, reason, subject, field, NO_INDEX};
}

static finpred_sdk_diagnostic_v1 check_edge(const finpred_sdk_port_v2 *output,
                                            const finpred_sdk_port_v2 *input)
{
    finpred_sdk_diagnostic_v1 r = validate_port(output, FINPRED_SDK_SUBJECT_PRODUCER);
    if (r.status != FINPRED_SDK_OK) return r;
    r = validate_port(input, FINPRED_SDK_SUBJECT_CONSUMER);
    if (r.status != FINPRED_SDK_OK) return r;
    if (output->major != input->major)
        return DIAG(INCOMPATIBLE, MISMATCH, EDGE, MAJOR, NO_INDEX);
    if (output->max_bytes > input->max_bytes)
        return DIAG(INCOMPATIBLE, EXCEEDS, EDGE, MAX_BYTES, NO_INDEX);
    if ((output->states & ~input->states) != 0)
        return DIAG(INCOMPATIBLE, MISMATCH, EDGE, STATES, NO_INDEX);
    if (strcmp(output->kind, input->kind))
        return DIAG(INCOMPATIBLE, MISMATCH, EDGE, KIND, NO_INDEX);
    if (strcmp(output->unit, input->unit))
        return DIAG(INCOMPATIBLE, MISMATCH, EDGE, UNIT, NO_INDEX);
    if (strcmp(output->currency, input->currency))
        return DIAG(INCOMPATIBLE, MISMATCH, EDGE, CURRENCY, NO_INDEX);
    return OK;
}

finpred_sdk_status finpred_sdk_connect_ports_v2(const finpred_sdk_port_v2 *output,
                                                const finpred_sdk_port_v2 *input)
{
    return check_edge(output, input).status;
}

finpred_sdk_status finpred_sdk_connect_ports_diagnostic_v1(const finpred_sdk_port_v2 *output,
                                                          const finpred_sdk_port_v2 *input,
                                                          finpred_sdk_diagnostic_v1 *out)
{
    if (!out) return FINPRED_SDK_INVALID;
    *out = check_edge(output, input);
    return out->status;
}
