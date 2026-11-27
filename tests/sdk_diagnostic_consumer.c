#include <finpred/sdk_diagnostic_v1.h>

#include <assert.h>
#include <stddef.h>

_Static_assert(sizeof(finpred_sdk_diagnostic_v1) == 20, "diagnostics v1 layout");
_Static_assert(offsetof(finpred_sdk_diagnostic_v1, index) == 16, "diagnostics v1 index");

static const char name[] = "dragnet.frozen_csv";
static const char *const inputs[] = {"hospitality.scenario@1", "finpred.offers.csv@1"};
static const char *const wrong[] = {"hospitality.scenario@1", "finpred.offers.csv@2"};
static const char *const deps[] = {"finpred.core@1", "yieldcraft.asof-whole-stay-property-min@1"};
static const char *const requested[] = {"network"};
static const char *const duplicate[] = {"network", "network"};
static const char *const null_item[] = {"network", NULL};

static void expect(finpred_sdk_diagnostic_v1 d, finpred_sdk_status status, uint32_t reason,
                   uint32_t subject, uint32_t field, uint32_t index)
{
    assert(d.status == status);
    assert(d.reason == reason);
    assert(d.subject == subject);
    assert(d.field == field);
    assert(d.index == index);
}

#define EXPECT(d, status, reason, subject, field, index) \
    expect(d, FINPRED_SDK_##status, FINPRED_SDK_REASON_##reason, \
           FINPRED_SDK_SUBJECT_##subject, FINPRED_SDK_FIELD_##field, index)
#define NO_INDEX FINPRED_SDK_DIAG_NO_INDEX

static void check_package(void)
{
    const finpred_sdk_plugin_v2 *plugin;
    finpred_sdk_diagnostic_v1 d;
    finpred_sdk_use_v2 use = {
        .sdk_version = 1, .package_version = "1.0.0", .kind = "Source",
        .output = "hospitality.offer@1", .mode = "analysis", .effect = "pure",
        .inputs = {2, inputs}
    };
    finpred_sdk_host_v2 host = {.dependencies = {2, deps},
        .ceilings = {.csv_rows = 512, .bytes_per_input = 2000000}};
    assert(finpred_sdk_lookup_v2(2, name, &plugin) == FINPRED_SDK_OK);
    assert(finpred_sdk_check_diagnostic_v1(name, &use, &host, NULL) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_check_diagnostic_v1(NULL, NULL, NULL, &d) == FINPRED_SDK_INVALID);
    EXPECT(d, INVALID, NULL, PACKAGE, NAME, NO_INDEX);
    assert(finpred_sdk_check_diagnostic_v1("unknown", NULL, NULL, &d) == FINPRED_SDK_NOT_FOUND);
    EXPECT(d, NOT_FOUND, NOT_FOUND, PACKAGE, NAME, NO_INDEX);
    assert(finpred_sdk_check_diagnostic_v1(name, NULL, &host, &d) == FINPRED_SDK_INVALID);
    EXPECT(d, INVALID, NULL, USE, NONE, NO_INDEX);
    assert(finpred_sdk_check_diagnostic_v1(name, &use, NULL, &d) == FINPRED_SDK_INVALID);
    EXPECT(d, INVALID, NULL, HOST, NONE, NO_INDEX);

#define PACKAGE(code, reason, subject, field, index) do { \
        assert(finpred_sdk_check_diagnostic_v1(name, &use, &host, &d) == FINPRED_SDK_##code); \
        expect(d, FINPRED_SDK_##code, FINPRED_SDK_REASON_##reason, \
               FINPRED_SDK_SUBJECT_##subject, FINPRED_SDK_FIELD_##field, index); \
        assert(finpred_sdk_check_v2(plugin, &use, &host) == d.status); \
    } while (0)
    use.inputs.items = wrong;
    use.mode = "execution";
    host.dependencies.count = 1;
    host.ceilings.bytes_per_input--;
    host.grants = (finpred_sdk_names_v2){2, duplicate};
    PACKAGE(INVALID, DUPLICATE, HOST, GRANTS, 1);
    host.grants.items = null_item;
    PACKAGE(INVALID, NULL, HOST, GRANTS, 1);
    host.grants.items = NULL;
    PACKAGE(INVALID, NULL, HOST, GRANTS, NO_INDEX);
    host.grants.count = 17;
    PACKAGE(INVALID, INVALID_VALUE, HOST, GRANTS, NO_INDEX);
    host.grants.count = 0;
    PACKAGE(INCOMPATIBLE, MISSING, HOST, DEPENDENCIES, 1);
    host.dependencies.count = 2;
    PACKAGE(INCOMPATIBLE, EXCEEDS, HOST, BYTES_PER_INPUT, NO_INDEX);
    host.ceilings.bytes_per_input++;
    PACKAGE(INCOMPATIBLE, MISMATCH, USE, INPUTS, 1);
    use.inputs.items = inputs;
    PACKAGE(DENIED, MISMATCH, USE, MODE, NO_INDEX);
    use.mode = "analysis";
    use.requested = (finpred_sdk_names_v2){1, requested};
    PACKAGE(DENIED, NOT_GRANTED, HOST, GRANTS, 0);
    host.grants = use.requested;
    PACKAGE(DENIED, NOT_DECLARED, PACKAGE, CAPABILITIES, 0);
    use.requested.count = 0;
    PACKAGE(OK, NONE, NONE, NONE, NO_INDEX);
#undef PACKAGE
}

static void check_ports(void)
{
    finpred_sdk_port_v2 producer = {"out", "value", "minor", "EUR", 1, 3, 32};
    finpred_sdk_port_v2 consumer = {"in", "value", "minor", "EUR", 1, 31, 64};
    finpred_sdk_diagnostic_v1 d;
    assert(finpred_sdk_connect_ports_diagnostic_v1(&producer, &consumer, NULL) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_connect_ports_diagnostic_v1(NULL, &consumer, &d) == FINPRED_SDK_INVALID);
    EXPECT(d, INVALID, NULL, PRODUCER, NONE, NO_INDEX);

#define EDGE(code, reason, subject, field) do { \
        assert(finpred_sdk_connect_ports_diagnostic_v1(&producer, &consumer, &d) == FINPRED_SDK_##code); \
        expect(d, FINPRED_SDK_##code, FINPRED_SDK_REASON_##reason, \
               FINPRED_SDK_SUBJECT_##subject, FINPRED_SDK_FIELD_##field, NO_INDEX); \
        assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == d.status); \
    } while (0)
    producer.name = NULL;
    consumer.states = 0;
    EDGE(INVALID, NULL, PRODUCER, NAME);
    producer.name = "out";
    EDGE(INVALID, INVALID_VALUE, CONSUMER, STATES);
    consumer.states = 1;
    consumer.major = 2;
    consumer.max_bytes = 31;
    EDGE(INCOMPATIBLE, MISMATCH, EDGE, MAJOR);
    consumer.major = 1;
    EDGE(INCOMPATIBLE, EXCEEDS, EDGE, MAX_BYTES);
    consumer.max_bytes = 32;
    EDGE(INCOMPATIBLE, MISMATCH, EDGE, STATES);
    consumer.states = 3;
    EDGE(OK, NONE, NONE, NONE);
#undef EDGE
}

int main(void)
{
    check_package();
    check_ports();
    return 0;
}
