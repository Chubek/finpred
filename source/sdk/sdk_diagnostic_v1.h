#ifndef FINPRED_SDK_DIAGNOSTIC_V1_H
#define FINPRED_SDK_DIAGNOSTIC_V1_H

#include "sdk_v2.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Result ABI v1, independent of the package manifest SDK and C package ABI. */
#define FINPRED_SDK_DIAG_NO_INDEX UINT32_MAX

#define FINPRED_SDK_REASON_NONE          UINT32_C(0)
#define FINPRED_SDK_REASON_NULL          UINT32_C(1)
#define FINPRED_SDK_REASON_INVALID_VALUE UINT32_C(2)
#define FINPRED_SDK_REASON_DUPLICATE     UINT32_C(3)
#define FINPRED_SDK_REASON_MISMATCH      UINT32_C(4)
#define FINPRED_SDK_REASON_MISSING       UINT32_C(5)
#define FINPRED_SDK_REASON_EXCEEDS       UINT32_C(6)
#define FINPRED_SDK_REASON_NOT_GRANTED   UINT32_C(7)
#define FINPRED_SDK_REASON_NOT_DECLARED  UINT32_C(8)
#define FINPRED_SDK_REASON_NOT_FOUND     UINT32_C(9)

#define FINPRED_SDK_SUBJECT_NONE     UINT32_C(0)
#define FINPRED_SDK_SUBJECT_PACKAGE  UINT32_C(1)
#define FINPRED_SDK_SUBJECT_USE      UINT32_C(2)
#define FINPRED_SDK_SUBJECT_HOST     UINT32_C(3)
#define FINPRED_SDK_SUBJECT_PRODUCER UINT32_C(4)
#define FINPRED_SDK_SUBJECT_CONSUMER UINT32_C(5)
#define FINPRED_SDK_SUBJECT_EDGE     UINT32_C(6)

#define FINPRED_SDK_FIELD_NONE               UINT32_C(0)
#define FINPRED_SDK_FIELD_NAME               UINT32_C(1)
#define FINPRED_SDK_FIELD_SDK_VERSION        UINT32_C(2)
#define FINPRED_SDK_FIELD_PACKAGE_VERSION    UINT32_C(3)
#define FINPRED_SDK_FIELD_KIND               UINT32_C(4)
#define FINPRED_SDK_FIELD_OUTPUT             UINT32_C(5)
#define FINPRED_SDK_FIELD_INPUTS             UINT32_C(6)
#define FINPRED_SDK_FIELD_DEPENDENCIES       UINT32_C(7)
#define FINPRED_SDK_FIELD_MODE               UINT32_C(8)
#define FINPRED_SDK_FIELD_EFFECT             UINT32_C(9)
#define FINPRED_SDK_FIELD_REQUESTED          UINT32_C(10)
#define FINPRED_SDK_FIELD_GRANTS             UINT32_C(11)
#define FINPRED_SDK_FIELD_CAPABILITIES       UINT32_C(12)
#define FINPRED_SDK_FIELD_CSV_ROWS           UINT32_C(13)
#define FINPRED_SDK_FIELD_BYTES_PER_INPUT    UINT32_C(14)
#define FINPRED_SDK_FIELD_ROOMS_PER_PROPERTY UINT32_C(15)
#define FINPRED_SDK_FIELD_MAXIMUM_ROOMS      UINT32_C(16)
#define FINPRED_SDK_FIELD_ADULTS             UINT32_C(17)
#define FINPRED_SDK_FIELD_CHILDREN           UINT32_C(18)
#define FINPRED_SDK_FIELD_SEARCH_BUDGET_MAX  UINT32_C(19)
#define FINPRED_SDK_FIELD_RUNS_PER_CALL      UINT32_C(20)
#define FINPRED_SDK_FIELD_DATA_ROWS          UINT32_C(21)
#define FINPRED_SDK_FIELD_COLUMNS            UINT32_C(22)
#define FINPRED_SDK_FIELD_OUTPUT_BYTES_MAX   UINT32_C(23)
#define FINPRED_SDK_FIELD_MAJOR              UINT32_C(24)
#define FINPRED_SDK_FIELD_UNIT               UINT32_C(25)
#define FINPRED_SDK_FIELD_CURRENCY           UINT32_C(26)
#define FINPRED_SDK_FIELD_STATES             UINT32_C(27)
#define FINPRED_SDK_FIELD_MAX_BYTES          UINT32_C(28)

typedef struct {
    finpred_sdk_status status;
    uint32_t reason, subject, field, index;
} finpred_sdk_diagnostic_v1;

/* Reports the first failure; success clears reason, subject and field.
 * index is zero-based for an offending list item, or NO_INDEX otherwise.
 * A missing dependency/capability indexes the compiled package list.
 * A missing host grant or undeclared capability indexes use->requested.
 * The result is caller-owned and holds no pointers or input text.
 * Each function sets *out and returns out->status, or returns INVALID if
 * out is NULL. Arguments obey the same lifetime rules as in sdk_v2.h. */
finpred_sdk_status finpred_sdk_check_diagnostic_v1(const char *name,
                                                  const finpred_sdk_use_v2 *use,
                                                  const finpred_sdk_host_v2 *host,
                                                  finpred_sdk_diagnostic_v1 *out);

finpred_sdk_status finpred_sdk_connect_ports_diagnostic_v1(const finpred_sdk_port_v2 *output,
                                                          const finpred_sdk_port_v2 *input,
                                                          finpred_sdk_diagnostic_v1 *out);

#ifdef __cplusplus
}
#endif
#endif
