#ifndef FINPRED_NATIVE_TEMPORAL_H
#define FINPRED_NATIVE_TEMPORAL_H

#include "store.h"
#include <stdint.h>

#define FP_TEMPORAL_MAX_ROWS 64
#define FP_TEMPORAL_MAX_KEYS 32

typedef enum {
    FP_TEMPORAL_QUERY, FP_TEMPORAL_CATALOG, FP_TEMPORAL_PARENT, FP_TEMPORAL_COMMIT
} fp_temporal_stage;

typedef struct {
    fp_temporal_stage stage;
    fp_result detail;
    /* Empty until the canonical commit is known, then its BLAKE3 hex ID.
     * An ID is not a publication receipt; check detail.status and stage. */
    char commit_id[65];
} fp_temporal_result;

/* The store and input arrays are borrowed. Keys must be ascending, unique,
 * nonzero. Cutoffs are independent, inclusive nonnegative Unix seconds.
 * The catalog and every named parent must already exist. */
fp_temporal_result fp_temporal_publish(const fp_store *store, const char *catalog_id,
                                      int64_t effective_cutoff, int64_t knowledge_cutoff,
                                      const uint64_t *keys, size_t key_count);

/* Read-only recomputation from an independently pinned commit ID. Success
 * verifies bytes, not the durability of a previous publication. */
fp_temporal_result fp_temporal_replay(const fp_store *store, const char *commit_id);

/* Explicitly complete a visible commit after verifying the same bytes as
 * replay. If the commit is absent, resubmit the original publish arguments. */
fp_temporal_result fp_temporal_resume(const fp_store *store, const char *commit_id);

#endif
