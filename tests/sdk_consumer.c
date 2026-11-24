#include <finpred/sdk.h>
#include <finpred/sdk_v2.h>

#include <assert.h>
#include <inttypes.h>
#include <stdio.h>

static void connect_ports(void)
{
    const finpred_sdk_port_v2 producer = {
        .name = "out", .kind = "test.value", .unit = "minor", .currency = "EUR",
        .major = 1, .states = FINPRED_SDK_STATE_AVAILABLE | FINPRED_SDK_STATE_PARTIAL,
        .max_bytes = 32,
    };
    finpred_sdk_port_v2 consumer = producer;
    consumer.name = "in";
    consumer.states |= FINPRED_SDK_STATE_STALE;
    consumer.max_bytes = 64;
    assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == FINPRED_SDK_OK);
    assert(finpred_sdk_connect_ports_v2(&consumer, &producer) == FINPRED_SDK_INCOMPATIBLE);
    consumer.states = FINPRED_SDK_STATE_AVAILABLE;
    assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == FINPRED_SDK_INCOMPATIBLE);
    consumer.states = producer.states;
    consumer.max_bytes = 31;
    assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == FINPRED_SDK_INCOMPATIBLE);
    consumer.max_bytes = 64;
    consumer.currency = "none";
    assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == FINPRED_SDK_INCOMPATIBLE);
    consumer.major = 1000;
    assert(finpred_sdk_connect_ports_v2(&producer, &consumer) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_connect_ports_v2(NULL, &consumer) == FINPRED_SDK_INVALID);
}

int main(void)
{
    connect_ports();
    const finpred_sdk_plugin_v1 *plugin = NULL, *other;
    const finpred_sdk_descriptor_v1 *d;
    assert(finpred_sdk_lookup_v1(FINPRED_SDK_ABI_V1, "yieldcraft.percentile", &plugin) == FINPRED_SDK_OK);
    d = finpred_sdk_describe_v1(plugin);
    assert(d && !finpred_sdk_describe_v1(NULL));
    other = plugin;
    assert(finpred_sdk_lookup_v1(2, d->name, &other) == FINPRED_SDK_INCOMPATIBLE && !other);
    other = plugin;
    assert(finpred_sdk_lookup_v1(1, "unknown", &other) == FINPRED_SDK_NOT_FOUND && !other);
    assert(finpred_sdk_lookup_v1(1, NULL, &other) == FINPRED_SDK_INVALID && !other);
    assert(finpred_sdk_lookup_v1(1, d->name, NULL) == FINPRED_SDK_INVALID);

    const char *modes[] = {"recommendation", "analysis", "simulation"};
    for (size_t i = 0; i < sizeof(modes)/sizeof(modes[0]); ++i)
        assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, d->effect, modes[i], 0) == FINPRED_SDK_OK);
    assert(finpred_sdk_check_v1(plugin, "Action", d->output_contract, "pure", modes[0], 0) == FINPRED_SDK_INCOMPATIBLE);
    assert(finpred_sdk_check_v1(plugin, d->kind, "pricing.recommendation@2", "pure", modes[0], 0) == FINPRED_SDK_INCOMPATIBLE);
    assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, "publish", modes[0], 0) == FINPRED_SDK_DENIED);
    assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, "pure", "execution", 0) == FINPRED_SDK_DENIED);
    assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, "pure", "unknown", 0) == FINPRED_SDK_DENIED);
    assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, "pure", modes[0], UINT64_C(1) << 63) == FINPRED_SDK_DENIED);
    assert(finpred_sdk_check_v1(plugin, d->kind, d->output_contract, "pure", NULL, 0) == FINPRED_SDK_INVALID);
    assert(finpred_sdk_check_v1(NULL, d->kind, d->output_contract, "pure", modes[0], 0) == FINPRED_SDK_INVALID);

    printf("%" PRIu32 "\n%s\n%s\n%s\n%s\n", d->sdk_version, d->name, d->package_version, d->kind, d->effect);
    assert(d->required_capabilities == 0);
    for (uint32_t i = 0; i < d->input_count; ++i) puts(d->input_contracts[i]);
    puts(d->output_contract);
    printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\n",
           d->csv_rows, d->rooms_per_property, d->maximum_rooms, d->adults, d->children, d->search_budget_max);
    return 0;
}
