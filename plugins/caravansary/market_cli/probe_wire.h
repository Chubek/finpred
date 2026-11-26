#ifndef CARAVANSARY_MARKET_PROBE_WIRE_H
#define CARAVANSARY_MARKET_PROBE_WIRE_H

/* The UTF-8 input contains one canonical JSON request, at most 64 KiB of
 * HTML before JSON escapes, and its separately constructed host grant. */
#define CARAVANSARY_MARKET_PROBE_INPUT_LIMIT (512u * 1024u)
#define CARAVANSARY_MARKET_PROBE_OUTPUT_LIMIT (2u * 1024u * 1024u)
#define CARAVANSARY_MARKET_PROBE_TIMEOUT_MS 5000
#define CARAVANSARY_MARKET_PROBE_SIBLING "finpred-caravansary-market-probe-v1"

#endif
