#ifndef CARAVANSARY_JOBS_STATE_H
#define CARAVANSARY_JOBS_STATE_H

#include <linux/limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "http/probe/context.h"

#define JOB_RUNNER "fixture-check-v1"
#define JOB_RUNNER_EXE "finpred-caravansary-jobs-runner-v1"
#define JOB_MARKET_RUNNER "market-scrape-v1"
#define JOB_MARKET_RUNNER_EXE "finpred-caravansary-jobs-runner-market-v1"
#define JOB_MARKET_EXE "finpred-caravansary-market"
#define JOB_JOE_RUNNER "joe-litty-rooms-v1"
#define JOB_JOE_RUNNER_EXE "finpred-caravansary-jobs-runner-joe-v1"
#define JOB_JOE_EXE "finpred-joe-litty-rooms-v1"
#define JOB_FIXTURE_MAX (1024u * 1024u)
#define JOB_LAST_CLOCK INT64_C(253402300799)

typedef struct {
    int root, sources, profiles, revoked, kron, results;
} job_state;

typedef struct {
    char sha256[65];
    size_t bytes;
} job_source;

bool job_key(const char *s);
/* A nonnegative canonical decimal in [0, UINT64_MAX]. */
bool job_number(const char *s, uint64_t *out);
bool job_parse_clock(const char *s, int64_t *out);
bool job_format_clock(int64_t seconds, char out[21]);

/* Reject unsafe/noncanonical paths; return an absolute deployment binding. */
int job_sibling_path(const char *expected, char out[PATH_MAX]);
/* Exclusive process-owned lock for all admin and Kron operations. */
int job_state_open(const char *path, job_state *state);
int job_state_begin_init(const char *path, job_state *state, int *parent);
/* Child's checked cwd; read-only and deliberately does not take the lock. */
int job_state_child(job_state *state, bool market);
void job_state_close(job_state *state);
int job_check_snapshot(const job_state *state);

/* Mutation: 0 durable, 1 visible but directory sync failed, -1 pre-commit. */
int job_source_add(const job_state *state, const char *source, int input, job_source *out);
int job_profile_add(const job_state *state, const char *profile, const char *source,
                    const char *runner);
int job_profile_disable(const job_state *state, const char *profile);
int job_save_clock(const job_state *state, int64_t now, bool initialize);

int job_source_read(const job_state *state, const char *source, job_source *out);
int job_source_bytes(const job_state *state, const char *source, job_source *out,
                     unsigned char **fixture);
int job_profile_read(const job_state *state, const char *profile, basis_http_probe_context *keys,
                     bool *active);
bool job_resolves(const job_state *state, const basis_http_probe_context *keys);
int job_read_private(int dir, const char *name, void *out, size_t capacity, size_t *length);
int job_write_all(int fd, const void *data, size_t length);
int job_publish(int dir, const char *name, const void *data, size_t size, bool replace);

#endif
