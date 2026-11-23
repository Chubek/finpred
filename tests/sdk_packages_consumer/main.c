/* Independent installed-header consumer. The Python harness controls these
 * environment strings solely to run the same manifest cases through both ABIs. */
#include <finpred/sdk_v2.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char buf[4096];
    const char *items[32];
} list_storage;

static finpred_sdk_names_v2 names(const char *key, list_storage *s)
{
    const char *text = getenv(key);
    assert(text && strlen(text) < sizeof(s->buf));
    strcpy(s->buf, text);
    finpred_sdk_names_v2 v = {0, s->items};
    if (!*text) return v;
    char *start = s->buf;
    for (;;) {
        assert(v.count < 32);
        s->items[v.count++] = start;
        start = strchr(start, ',');
        if (!start) return v;
        *start++ = '\0';
    }
}

int main(void)
{
    const finpred_sdk_plugin_v2 *p = NULL;
    assert(finpred_sdk_lookup_v2(2, "yieldcraft.percentile", &p) == FINPRED_SDK_OK && p);
    assert(finpred_sdk_lookup_v2(1, "yieldcraft.percentile", &p) == FINPRED_SDK_INCOMPATIBLE && !p);
    assert(finpred_sdk_lookup_v2(2, NULL, &p) == FINPRED_SDK_INVALID && !p);
    assert(!finpred_sdk_describe_v2(NULL));
    int status = finpred_sdk_lookup_v2(FINPRED_SDK_ABI_V2, getenv("PACKAGE"), &p);
    if (status != FINPRED_SDK_OK) { assert(!p); return status; }
    list_storage inputs, requested, deps, grants;
    finpred_sdk_use_v2 use = {
        .sdk_version = (uint32_t)atoi(getenv("SDK")), .package_version = getenv("VERSION"),
        .kind = getenv("KIND"), .output = getenv("OUTPUT"), .mode = getenv("MODE"),
        .effect = getenv("EFFECT"), .inputs = names("INPUTS", &inputs),
        .requested = names("REQUESTED", &requested)
    };
#define LIMIT(k) .k = (uint32_t)atoi(getenv(#k))
    finpred_sdk_host_v2 host = {
        .dependencies = names("DEPS", &deps), .grants = names("GRANTS", &grants),
        .ceilings = {LIMIT(csv_rows), LIMIT(bytes_per_input), LIMIT(rooms_per_property),
                     LIMIT(maximum_rooms), LIMIT(adults), LIMIT(children), LIMIT(search_budget_max),
                     LIMIT(runs_per_call), LIMIT(data_rows), LIMIT(columns), LIMIT(output_bytes_max)}
    };
    assert(finpred_sdk_check_v2(NULL, &use, &host) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_check_v2(p, &use, NULL) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_check_v2(p, NULL, &host) == FINPRED_SDK_INVALID);
    finpred_sdk_host_v2 malformed = host;
    malformed.grants = (finpred_sdk_names_v2){1, NULL};
    assert(finpred_sdk_check_v2(p, &use, &malformed) == FINPRED_SDK_INVALID);
    return finpred_sdk_check_v2(p, &use, &host);
}
