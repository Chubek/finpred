#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "state.h"
#include "market.h"

#include "http/probe/supervised.h"
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { USAGE_ERROR = 2, UNCERTAIN = 3 };
enum command { INVALID, INIT, SOURCE_ADD, SOURCE_SHOW, PROFILE_ADD, PROFILE_SHOW,
               PROFILE_DISABLE, SCHEDULE, NEXT, DISPATCH, CANCEL, MARKET_PROFILE_ADD,
               JOE_PROFILE_ADD, RESULT_SHOW };

typedef struct {
    enum command command;
    const char *key, *source;
    int64_t clock;
    basis_kron_schedule schedule;
    uint64_t id;
} request;

static volatile sig_atomic_t interrupted;

static void interrupt(int sig)
{
    interrupted = sig;
}

static void usage(FILE *out)
{
    fputs("Usage: finpred-caravansary-jobs --state ABSOLUTE_DIR COMMAND\n"
          "  init\n"
          "  source-add SOURCE < fixture\n"
          "  source-show SOURCE\n"
          "  profile-add PROFILE SOURCE\n"
          "  market-profile-add PROFILE MANIFEST_SOURCE\n"
          "  joe-profile-add PROFILE PREDICTION_SOURCE\n"
          "  profile-show PROFILE\n"
          "  profile-disable PROFILE\n"
          "  schedule PROFILE --at UTC (--once UTC | --every SECONDS)\n"
          "  next\n"
          "  dispatch --at UTC\n"
          "  cancel ID\n"
          "  result-show ID DEADLINE_UTC\n"
          "UTC is YYYY-MM-DDTHH:MM:SSZ (1970 through 9999), supplied explicitly.\n", out);
}

static int error(const char *operation)
{
    int status = errno;
    fprintf(stderr, "caravansary-jobs: %s: %s\n", operation, strerror(status));
    return USAGE_ERROR;
}

static const char *change_name(int change)
{
    return change ? "uncertain" : "committed";
}

static request parse(int argc, char **argv)
{
    request r = {0};
    if (argc < 4 || strcmp(argv[1], "--state")) return r;
    const char *cmd = argv[3];
    if (argc == 4 && !strcmp(cmd, "init")) r.command = INIT;
    if (argc == 4 && !strcmp(cmd, "next")) r.command = NEXT;
    if (argc == 5 && job_key(argv[4])) {
        r.key = argv[4];
        if (!strcmp(cmd, "source-add")) r.command = SOURCE_ADD;
        if (!strcmp(cmd, "source-show")) r.command = SOURCE_SHOW;
        if (!strcmp(cmd, "profile-show")) r.command = PROFILE_SHOW;
        if (!strcmp(cmd, "profile-disable")) r.command = PROFILE_DISABLE;
    }
    if (argc == 6 && (!strcmp(cmd, "profile-add") || !strcmp(cmd, "market-profile-add") ||
                      !strcmp(cmd, "joe-profile-add")) &&
        job_key(argv[4]) && job_key(argv[5])) {
        r.key = argv[4];
        r.source = argv[5];
        r.command = !strcmp(cmd, "profile-add") ? PROFILE_ADD :
            !strcmp(cmd, "joe-profile-add") ? JOE_PROFILE_ADD : MARKET_PROFILE_ADD;
    }
    if (argc == 5 && !strcmp(cmd, "cancel") && job_number(argv[4], &r.id) && r.id)
        r.command = CANCEL;
    if (argc == 6 && !strcmp(cmd, "dispatch") && !strcmp(argv[4], "--at") &&
        job_parse_clock(argv[5], &r.clock)) r.command = DISPATCH;
    if (argc == 6 && !strcmp(cmd, "result-show") && job_number(argv[4], &r.id) && r.id &&
        job_parse_clock(argv[5], &r.clock)) r.command = RESULT_SHOW;
    if (argc == 9 && !strcmp(cmd, "schedule") && job_key(argv[4]) &&
        !strcmp(argv[5], "--at") && job_parse_clock(argv[6], &r.clock)) {
        r.key = argv[4];
        int64_t due;
        uint64_t period;
        if (!strcmp(argv[7], "--once") && job_parse_clock(argv[8], &due) && due >= r.clock) {
            r.schedule = (basis_kron_schedule){BASIS_KRON_ONCE, due, BASIS_KRON_PERSISTENT, 0};
            r.command = SCHEDULE;
        } else if (!strcmp(argv[7], "--every") && job_number(argv[8], &period) &&
                   period && period <= (uint64_t)(JOB_LAST_CLOCK - r.clock)) {
            r.schedule = (basis_kron_schedule){BASIS_KRON_EVERY, (int64_t)period,
                                               BASIS_KRON_FOR, JOB_LAST_CLOCK - r.clock};
            r.command = SCHEDULE;
        }
    }
    return r;
}

static int open_kron(const char *path, basis_kron_vm **vm)
{
    char kron[PATH_MAX];
    int n = snprintf(kron, sizeof kron, "%s/kron", path);
    if (n < 0 || n >= (int)sizeof kron) {
        errno = ENAMETOOLONG;
        return -1;
    }
    return basis_kron_open(kron, vm);
}

static int init(const char *path)
{
    job_state state;
    int parent;
    if (job_state_begin_init(path, &state, &parent) < 0)
        return error("initialize private state (parent must exist; state must be new)");
    basis_kron_vm *vm = NULL;
    int clock = job_save_clock(&state, 0, true);
    int kron = clock == 0 ? open_kron(path, &vm) : clock;
    int rc;
    if (kron < 0) {
        rc = error("initialize clock or Kron (partial state may remain)");
    } else {
        int state_sync = fsync(state.root);
        int parent_sync = fsync(parent);
        rc = kron || state_sync < 0 || parent_sync < 0 ? UNCERTAIN : 0;
        printf("{\"kind\":\"caravansary.jobs.init@1\",\"status\":\"%s\"}\n", change_name(rc));
    }
    basis_kron_close(vm);
    job_state_close(&state);
    close(parent);
    return rc;
}

static int source_command(const job_state *state, request r)
{
    bool add = r.command == SOURCE_ADD;
    job_source source;
    int change = add ? job_source_add(state, r.key, STDIN_FILENO, &source)
                     : job_source_read(state, r.key, &source);
    if (change < 0) return error(add ? "add immutable source from stdin" : "read source");
    printf("{\"bytes\":%zu,\"kind\":\"caravansary.jobs.source@1\",\"sha256\":\"%s\","
           "\"source\":\"%s\"", source.bytes, source.sha256, r.key);
    if (add) printf(",\"status\":\"%s\"", change_name(change));
    puts("}");
    return change ? UNCERTAIN : 0;
}

static int profile_command(const job_state *state, request r)
{
    int change = 0;
    basis_http_probe_context keys;
    bool active;
    const char *source = r.source;
    const char *runner = JOB_RUNNER;
    if (r.command == PROFILE_ADD || r.command == MARKET_PROFILE_ADD || r.command == JOE_PROFILE_ADD) {
        if (r.command == MARKET_PROFILE_ADD) {
            if (job_market_check(state, source) < 0) return error("validate market manifest and inputs");
            runner = JOB_MARKET_RUNNER;
        }
        if (r.command == JOE_PROFILE_ADD) runner = JOB_JOE_RUNNER;
        change = job_profile_add(state, r.key, source, runner);
        if (change < 0) return error("add immutable profile");
        active = true;
    } else {
        if (job_profile_read(state, r.key, &keys, &active) < 0) return error("read profile");
        source = keys.probe;
        runner = keys.runner;
        if (r.command == PROFILE_DISABLE) {
            change = job_profile_disable(state, r.key);
            if (change < 0) return error("disable profile");
            active = false;
        }
    }
    printf("{\"active\":%s,\"kind\":\"caravansary.jobs.profile@1\",\"profile\":\"%s\","
           "\"runner\":\"%s\",\"source\":\"%s\"", active ? "true" : "false", r.key, runner, source);
    if (r.command != PROFILE_SHOW) printf(",\"status\":\"%s\"", change_name(change));
    puts("}");
    return change ? UNCERTAIN : 0;
}

static int authorize_schedule(void *user, const basis_http_probe_context *keys,
                              const basis_kron_schedule *schedule, int64_t clock)
{
    (void)schedule;
    (void)clock;
    return job_resolves(user, keys) && (strcmp(keys->runner, JOB_MARKET_RUNNER) ||
                                      job_market_check(user, keys->probe) == 0);
}

typedef struct {
    job_state *state;
    job_market_stage *stage;
    bool market_allowed;
    bool joe_allowed, joe_prediction;
    const char *result_status;
} dispatch_host;

static int authorize_attempt(void *user, const basis_http_probe_invocation *invocation)
{
    dispatch_host *host = user;
    const basis_http_probe_context *keys = &invocation->keys;
    if (interrupted || !invocation->scheduled || !invocation->occurrence_id ||
        invocation->deadline < 0 || invocation->deadline > JOB_LAST_CLOCK ||
        !job_resolves(host->state, keys)) return 0;
    bool market = !strcmp(keys->runner, JOB_MARKET_RUNNER);
    bool joe = !strcmp(keys->runner, JOB_JOE_RUNNER);
    if (!market && !joe) return 1;
    if ((market && !host->market_allowed) || (joe && !host->joe_allowed) || host->stage->fd < 0) {
        host->result_status = "unavailable";
        return 0;
    }
    if (market && job_market_check(host->state, keys->probe) < 0) return 0;
    host->joe_prediction = joe;
    host->result_status = "not_committed";
    return 1;
}

static int save_clock(const job_state *state, int64_t now)
{
    int change = job_save_clock(state, now, false);
    if (change < 0) return error("advance explicit clock (check stored clock and nondecreasing order)");
    if (change) {
        fputs("caravansary-jobs: clock may have advanced without confirmed durability; "
              "Kron unchanged\n", stderr);
        return UNCERTAIN;
    }
    return 0;
}

static int schedule_job(basis_kron_vm *vm, job_state *state, request r)
{
    basis_http_probe_context keys;
    bool active;
    if (job_profile_read(state, r.key, &keys, &active) < 0) return error("resolve schedule profile");
    if (!active || !job_resolves(state, &keys)) {
        errno = EACCES;
        return error("authorize schedule profile and source");
    }
    if (basis_kron_validate_schedule(&r.schedule, r.clock) < 0) return error("validate schedule");
    if (!strcmp(keys.runner, JOB_MARKET_RUNNER)) {
        if (job_market_check(state, keys.probe) < 0) return error("resolve approved market inputs");
        char executable[PATH_MAX];
        if (job_sibling_path(JOB_MARKET_RUNNER_EXE, executable) < 0 ||
            job_sibling_path(JOB_MARKET_EXE, executable) < 0)
            return error("resolve trusted installed market runner and workflow");
    }
    if (!strcmp(keys.runner, JOB_JOE_RUNNER)) {
        char executable[PATH_MAX];
        if (job_sibling_path(JOB_JOE_RUNNER_EXE, executable) < 0 ||
            job_sibling_path(JOB_JOE_EXE, executable) < 0)
            return error("resolve trusted Joe Litty Rooms runner and predictor");
    }
    int rc = save_clock(state, r.clock);
    if (rc) return rc;
    uint64_t id;
    basis_kron_change change =
        basis_http_probe_schedule(vm, &r.schedule, r.clock, &keys, authorize_schedule, state, &id);
    if (change < 0) return error("persist schedule");
    char due[21];
    bool once = r.schedule.cadence == BASIS_KRON_ONCE;
    if (!job_format_clock(r.schedule.seconds + (once ? 0 : r.clock), due)) {
        errno = EOVERFLOW;
        return error("format committed schedule deadline");
    }
    printf("{\"cadence\":\"%s\",\"deadline\":\"%s\",\"id\":\"%" PRIu64 "\","
           "\"kind\":\"caravansary.jobs.schedule@1\",\"profile\":\"%s\",\"status\":\"%s\"}\n",
           once ? "once" : "every", due, id, r.key, change_name(change));
    return change ? UNCERTAIN : 0;
}

static int next_job(basis_kron_vm *vm)
{
    int64_t deadline;
    basis_kron_next_status next = basis_kron_next(vm, &deadline);
    if (next < 0) return error("read next deadline");
    if (next == BASIS_KRON_EMPTY)
        puts("{\"deadline\":null,\"kind\":\"caravansary.jobs.next@1\"}");
    else {
        char due[21];
        if (!job_format_clock(deadline, due)) {
            errno = EOVERFLOW;
            return error("format next deadline");
        }
        printf("{\"deadline\":\"%s\",\"kind\":\"caravansary.jobs.next@1\"}\n", due);
    }
    return 0;
}

static int cancel_job(basis_kron_vm *vm, uint64_t id)
{
    basis_kron_change change = basis_kron_pull(vm, id);
    if (change < 0) return error("cancel pending promise");
    printf("{\"id\":\"%" PRIu64 "\",\"kind\":\"caravansary.jobs.cancel@1\",\"status\":\"%s\"}\n",
           id, change_name(change));
    return change ? UNCERTAIN : 0;
}

static const char *process_state(basis_daemon_state state)
{
    switch (state) {
    case BASIS_DAEMON_IDLE: return "idle";
    case BASIS_DAEMON_RUNNING: return "running";
    case BASIS_DAEMON_EXITED: return "exited";
    case BASIS_DAEMON_SIGNALED: return "signaled";
    case BASIS_DAEMON_STOPPED: return "stopped";
    case BASIS_DAEMON_START_FAILED: return "start_failed";
    case BASIS_DAEMON_START_TIMEOUT: return "start_timeout";
    case BASIS_DAEMON_RUN_TIMEOUT: return "run_timeout";
    case BASIS_DAEMON_STOP_TIMEOUT: return "stop_timeout";
    case BASIS_DAEMON_FAILED: return "failed";
    }
    return "unknown";
}

static void print_attempt(const basis_http_probe_job_result *attempt)
{
    if (!attempt->has_daemon_event) {
        fputs("null", stdout);
        return;
    }
    printf("{\"exit_code\":%d,\"signal\":%d,\"state\":\"%s\",\"status\":%d,\"system_error\":%d}",
           attempt->daemon_event.exit_code, attempt->daemon_event.term_signal,
           process_state(attempt->daemon_event.state), attempt->daemon_status,
           attempt->daemon_event.system_error);
}

static int report_dispatch(basis_kron_dispatch_status status, const basis_kron_result *result,
                           const basis_http_probe_job_result *attempt, const char *result_status,
                           bool result_error, bool result_uncertain)
{
    if (status < 0) return error("dispatch Kron occurrence");
    if (status == BASIS_KRON_IDLE) {
        puts("{\"deadline\":null,\"id\":null,\"kind\":\"caravansary.jobs.dispatch@1\","
             "\"outcome\":\"idle\",\"process\":null}");
        return 0;
    }
    const char *outcome = "failed";
    switch (result->disposition) {
    case BASIS_KRON_EXPIRED: outcome = "expired"; break;
    case BASIS_KRON_DENIED:
        outcome = attempt->status == BASIS_HTTP_PROBE_JOB_INVALID ? "failed" : "denied";
        break;
    case BASIS_KRON_RAN: outcome = "ran"; break;
    case BASIS_KRON_RUN_FAILED: break;
    case BASIS_KRON_NOT_RUN_UNCERTAIN: outcome = "uncertain"; break;
    }
    if (result_error) outcome = "failed";
    if (result_uncertain) outcome = "uncertain";
    char due[21];
    if (!job_format_clock(result->deadline, due)) {
        errno = EOVERFLOW;
        return error("format consumed occurrence deadline");
    }
    printf("{\"deadline\":\"%s\",\"id\":\"%" PRIu64 "\",\"kind\":\"caravansary.jobs.dispatch@1\","
           "\"outcome\":\"%s\",\"process\":", due, result->id, outcome);
    print_attempt(attempt);
    if (result_status) printf(",\"result_status\":\"%s\"", result_status);
    puts("}");
    return status == BASIS_KRON_CONSUMED_UNCERTAIN || result_uncertain ? UNCERTAIN : 0;
}

static int dispatch_job(basis_kron_vm *vm, job_state *state, const char *path, int64_t clock)
{
    char executable[PATH_MAX], market_runner[PATH_MAX], joe_runner[PATH_MAX], workflow[PATH_MAX];
    if (job_sibling_path(JOB_RUNNER_EXE, executable) < 0)
        return error("resolve trusted installed fixture runner");
    bool have_market_runner = job_sibling_path(JOB_MARKET_RUNNER_EXE, market_runner) == 0;
    bool have_market = have_market_runner && job_sibling_path(JOB_MARKET_EXE, workflow) == 0;
    bool have_joe_runner = job_sibling_path(JOB_JOE_RUNNER_EXE, joe_runner) == 0;
    bool have_joe = have_joe_runner && job_sibling_path(JOB_JOE_EXE, workflow) == 0;
    job_market_stage stage = {.fd = -1};
    int64_t earliest;
    basis_kron_next_status next = basis_kron_next(vm, &earliest);
    if (next < 0) return error("check Kron deadline");
    if ((have_market || have_joe) && next == BASIS_KRON_READY && earliest <= clock &&
        job_market_stage_open(state, path, &stage) < 0) return error("stage private workflow attempt");
    struct sigaction action = {.sa_handler = interrupt};
    if (sigemptyset(&action.sa_mask) < 0 || sigaction(SIGINT, &action, NULL) < 0 ||
        sigaction(SIGTERM, &action, NULL) < 0)
    {
        job_market_stage_close(state, &stage);
        return error("install dispatch shutdown handlers");
    }
    basis_daemon_supervisor *owner = NULL;
    if (basis_daemon_create_supervisor(&owner) != BASIS_DAEMON_OK) {
        errno = EIO;
        job_market_stage_close(state, &stage);
        return error("create daemon supervisor");
    }
    int rc = save_clock(state, clock);
    if (!rc && !interrupted) {
        basis_daemon_runner runners[3] = {{JOB_RUNNER, executable, path}};
        size_t count = 1;
        const char *cwd = stage.fd >= 0 ? stage.path : path;
        if (have_market_runner)
            runners[count++] = (basis_daemon_runner){JOB_MARKET_RUNNER, market_runner, cwd};
        if (have_joe_runner)
            runners[count++] = (basis_daemon_runner){JOB_JOE_RUNNER, joe_runner, cwd};
        dispatch_host user = {.state = state, .stage = &stage,
                              .market_allowed = have_market, .joe_allowed = have_joe};
        const basis_http_probe_supervised_host host = {
            owner, runners, count,
            /* Reserve room for W6's bounded 5 s local Probe call and startup. */
            {1000, (have_market || have_joe) ? 7000u : 2000u, 100, 1000}, &user, authorize_attempt
        };
        basis_http_probe_job_result attempt = {0};
        basis_kron_result result = {0};
        basis_kron_dispatch_status status = basis_http_probe_dispatch(vm, clock, &host, &result, &attempt);
        int dispatch_errno = errno;
        if (attempt.has_daemon_event && attempt.daemon_event.child_owned) {
            fputs("caravansary-jobs: retaining supervisor until child cleanup completes\n", stderr);
            basis_daemon_event event;
            do {
                (void)basis_daemon_stop(owner, 0, host.limits.reap_ms, &event);
            } while (event.child_owned);
        }
        bool result_error = user.result_status && !strcmp(user.result_status, "unavailable");
        bool result_uncertain = false;
        if (status == BASIS_KRON_CONSUMED && result.disposition == BASIS_KRON_RAN && user.result_status) {
            int committed = job_market_commit(state, &stage, result.id, result.deadline,
                                              user.joe_prediction);
            if (committed < 0) {
                (void)error("commit workflow artifact after consumed occurrence");
                user.result_status = "failed";
                result_error = true;
            } else {
                user.result_status = change_name(committed);
                result_uncertain = committed > 0;
            }
        }
        errno = dispatch_errno;
        rc = report_dispatch(status, &result, &attempt, user.result_status, result_error, result_uncertain);
    }
    job_market_stage_close(state, &stage);
    if (basis_daemon_destroy_supervisor(&owner) != BASIS_DAEMON_OK && !rc) {
        errno = EIO;
        rc = error("destroy daemon supervisor");
    }
    return rc ? rc : interrupted ? 128 + interrupted : 0;
}

static int ordinary(const char *path, request r)
{
    job_state state;
    if (job_state_open(path, &state) < 0)
        return error("open owner-only state (a command may already own this state)");
    int rc;
    if (r.command == SOURCE_ADD || r.command == SOURCE_SHOW) rc = source_command(&state, r);
    else if (r.command == PROFILE_ADD || r.command == PROFILE_SHOW || r.command == PROFILE_DISABLE ||
             r.command == MARKET_PROFILE_ADD || r.command == JOE_PROFILE_ADD)
        rc = profile_command(&state, r);
    else if (r.command == RESULT_SHOW)
        rc = job_market_show(&state, r.id, r.clock) < 0 ? error("read occurrence result") : 0;
    else {
        basis_kron_vm *vm = NULL;
        int opened = job_check_snapshot(&state) < 0 ? -1 : open_kron(path, &vm);
        if (opened < 0) rc = error("open existing private Kron snapshot");
        else if (opened > 0) {
            fputs("caravansary-jobs: Kron snapshot initialization uncertain\n", stderr);
            rc = UNCERTAIN;
        } else {
            switch (r.command) {
            case NEXT: rc = next_job(vm); break;
            case SCHEDULE: rc = schedule_job(vm, &state, r); break;
            case DISPATCH: rc = dispatch_job(vm, &state, path, r.clock); break;
            case CANCEL: rc = cancel_job(vm, r.id); break;
            default: rc = USAGE_ERROR; break;
            }
        }
        basis_kron_close(vm);
    }
    job_state_close(&state);
    return rc;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--help")) {
        usage(stdout);
        return 0;
    }
    request r = parse(argc, argv);
    if (r.command == INVALID) {
        usage(stderr);
        return USAGE_ERROR;
    }
    umask(0077);
    int rc = r.command == INIT ? init(argv[2]) : ordinary(argv[2], r);
    if (fflush(stdout) == EOF && !rc) return error("write reply (command may have committed)");
    return rc;
}
