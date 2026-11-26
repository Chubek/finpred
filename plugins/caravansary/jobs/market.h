#ifndef CARAVANSARY_JOBS_MARKET_H
#define CARAVANSARY_JOBS_MARKET_H

#include "state.h"

typedef struct {
    int fd;
    char name[27];
    char path[PATH_MAX];
} job_market_stage;

/* Check approved manifest syntax and every referenced source identity. */
int job_market_check(const job_state *state, const char *manifest);
int job_market_stage_open(const job_state *state, const char *path, job_market_stage *stage);
void job_market_stage_close(const job_state *state, job_market_stage *stage);
int job_market_exec(const job_state *state, const char *manifest);
int job_market_commit(const job_state *state, const job_market_stage *stage, uint64_t id,
                      int64_t deadline);
int job_market_show(const job_state *state, uint64_t id, int64_t deadline);

#endif
