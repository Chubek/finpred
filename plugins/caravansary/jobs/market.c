#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "market.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>

#define CAPTURE_MAX 65536u
#define RESULT_MAX (2u * 1024u * 1024u)
#define NOFOLLOW_DIR (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)

typedef struct {
    unsigned char *manifest;
    char *source, *fixture, *provider, *url, *observed, *as_of;
    const char *capture_digest;
    unsigned char *script, *capture;
    size_t script_size, capture_size;
} market_input;

static int fail(int error)
{
    errno = error;
    return -1;
}

static void input_close(market_input *in)
{
    int error = errno;
    free(in->manifest);
    free(in->script);
    free(in->capture);
    errno = error;
}

/* Exact ASCII word followed by delimiter, no collapsing or extra whitespace. */
static char *word(char **rest, char delim)
{
    char *begin = *rest, *p = begin;
    while (*p != delim && *p >= 33 && *p <= 126) ++p;
    if (*p != delim || p == begin) return NULL;
    *p = 0;
    *rest = p + 1;
    return begin;
}

static bool safe_url(const char *s, const char *provider)
{
    char prefix[32];
    int n = snprintf(prefix, sizeof prefix, "https://%s.example/", provider);
    return !strncmp(s, prefix, (size_t)n) && s[n] && strlen(s) <= 512 &&
           strlen(s) == strspn(s, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                                  "0123456789:/?&=%._-+");
}

static int bound_source(const job_state *state, const char *name, const char *digest,
                        unsigned char **bytes, size_t *size, size_t cap)
{
    if (!job_key(name) || strlen(digest) != 64 || strspn(digest, "0123456789abcdef") != 64)
        return fail(EINVAL);
    job_source info;
    if (job_source_bytes(state, name, &info, bytes) < 0) return -1;
    if (info.bytes > cap) return fail(EFBIG);
    if (strcmp(info.sha256, digest)) return fail(EILSEQ);
    *size = info.bytes;
    return 0;
}

static int input_open(const job_state *state, const char *manifest, market_input *in)
{
    *in = (market_input){0};
    job_source record;
    if (job_source_bytes(state, manifest, &record, &in->manifest) < 0) return -1;
    if (record.bytes > 1024 || memchr(in->manifest, 0, record.bytes)) return fail(EINVAL);
    char *rest = (char *)in->manifest;
    const char *magic = word(&rest, '\n');
    if (!magic || strcmp(magic, "CVSCRAPE1")) return fail(EINVAL);
    in->source = word(&rest, ' ');
    in->fixture = word(&rest, ' ');
    in->provider = word(&rest, ' ');
    in->url = word(&rest, ' ');
    in->observed = word(&rest, ' ');
    in->as_of = word(&rest, '\n');
    const char *script = word(&rest, ' '), *script_sha = word(&rest, '\n');
    const char *capture = word(&rest, ' '), *capture_sha = word(&rest, '\n');
    int64_t observed, as_of;
    if (!in->source || !in->fixture || !in->provider || !in->url || !in->observed ||
        !in->as_of || !script || !script_sha || !capture || !capture_sha || *rest ||
        !job_key(in->source) || !job_key(in->fixture) ||
        (strcmp(in->provider, "agoda") && strcmp(in->provider, "booking")) ||
        !safe_url(in->url, in->provider) || !job_parse_clock(in->observed, &observed) ||
        !job_parse_clock(in->as_of, &as_of) || observed > as_of ||
        !strcmp(manifest, script) || !strcmp(manifest, capture) || !strcmp(script, capture))
        return fail(EINVAL);
    if (bound_source(state, script, script_sha, &in->script, &in->script_size, JOB_FIXTURE_MAX) < 0 ||
        bound_source(state, capture, capture_sha, &in->capture, &in->capture_size, CAPTURE_MAX) < 0)
        return -1;
    in->capture_digest = capture_sha;
    if (memchr(in->script, 0, in->script_size) || memchr(in->capture, 0, in->capture_size))
        return fail(EINVAL);
    return 0;
}

int job_market_check(const job_state *state, const char *manifest)
{
    market_input in;
    int rc = input_open(state, manifest, &in);
    input_close(&in);
    return rc;
}

int job_market_stage_open(const job_state *state, const char *path, job_market_stage *stage)
{
    stage->fd = -1;
    stage->name[0] = 0;
    uint64_t nonce;
    if (getentropy(&nonce, sizeof nonce) < 0) return -1;
    snprintf(stage->name, sizeof stage->name, ".dispatch.%016" PRIx64, nonce);
    int n = snprintf(stage->path, sizeof stage->path, "%s/%s", path, stage->name);
    if (n < 0 || n >= (int)sizeof stage->path) return fail(ENAMETOOLONG);
    if (mkdirat(state->root, stage->name, 0700) < 0) return -1;
    stage->fd = openat(state->root, stage->name, NOFOLLOW_DIR);
    if (stage->fd < 0) {
        int error = errno;
        unlinkat(state->root, stage->name, AT_REMOVEDIR);
        return fail(error);
    }
    return 0;
}

void job_market_stage_close(const job_state *state, job_market_stage *stage)
{
    if (stage->fd < 0) return;
    int error = errno;
    int input = openat(stage->fd, "input", NOFOLLOW_DIR);
    if (input >= 0) {
        unlinkat(input, "script.caf", 0);
        unlinkat(input, "grants.json", 0);
        unlinkat(input, "capture.html", 0);
        close(input);
        unlinkat(stage->fd, "input", AT_REMOVEDIR);
    }
    unlinkat(stage->fd, "reply", 0);
    close(stage->fd);
    unlinkat(state->root, stage->name, AT_REMOVEDIR);
    stage->fd = -1;
    errno = error;
}

static int create_file(int dir, const char *name)
{
    return openat(dir, name, O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC | O_WRONLY, 0600);
}

static int prepare_file(int dir, const char *name, const void *data, size_t size)
{
    int fd = create_file(dir, name);
    if (fd < 0) return -1;
    int rc = job_write_all(fd, data, size);
    int error = errno;
    int closed = close(fd);
    return rc < 0 ? fail(error) : closed;
}

int job_market_exec(const job_state *state, const char *manifest)
{
    char executable[PATH_MAX];
    if (job_sibling_path(JOB_MARKET_EXE, executable) < 0) return -1;
    market_input in;
    int rc = input_open(state, manifest, &in);
    if (rc < 0) {
        input_close(&in);
        return -1;
    }
    /* All interpolated strings have been restricted to safe ASCII. The
     * grants file is generated by trusted code, not taken from the script. */
    char grants[2048];
    int n = snprintf(grants, sizeof grants,
        "{\"grants\":[{\"fixture\":\"%s\",\"observed_at\":\"%s\",\"operations\":[\"scrape\"],"
        "\"path\":\"capture.html\",\"provider\":\"%s\",\"provider_operation\":\"profile\","
        "\"sha256\":\"%s\",\"source\":\"%s\",\"source_url\":\"%s\"}],"
        "\"kind\":\"caravansary.host-grants@1\"}\n",
        in.fixture, in.observed, in.provider, in.capture_digest, in.source, in.url);
    int dir = -1, input = -1, reply = -1;
    if (n < 0 || n >= (int)sizeof grants) { errno = EOVERFLOW; goto finished; }
    dir = open(".", NOFOLLOW_DIR);
    if (dir < 0 || mkdirat(dir, "input", 0700) < 0) goto finished;
    input = openat(dir, "input", NOFOLLOW_DIR);
    if (input < 0 ||
        prepare_file(input, "script.caf", in.script, in.script_size) < 0 ||
        prepare_file(input, "capture.html", in.capture, in.capture_size) < 0 ||
        prepare_file(input, "grants.json", grants, (size_t)n) < 0) goto finished;
    reply = create_file(dir, "reply");
    if (reply < 0 || dup2(reply, STDOUT_FILENO) < 0) goto finished;
    struct rlimit limit;
    if (getrlimit(RLIMIT_FSIZE, &limit) < 0) goto finished;
    if (limit.rlim_cur > RESULT_MAX) {
        limit.rlim_cur = RESULT_MAX;
        if (setrlimit(RLIMIT_FSIZE, &limit) < 0) goto finished;
    }
    /* The Supervisor still owns the exact same foreground child after exec.
     * No arbitrary arguments or executable are selected by the manifest. */
    char *const args[] = {executable, "scrape", "input/script.caf", "--source", in.source,
                          "--input-root", "input", "--host-grants", "input/grants.json",
                          "--as-of", in.as_of, NULL};
    char *const env[] = {"LC_ALL=C", "TZ=UTC", NULL};
    execve(executable, args, env);
finished:
    {
        int error = errno;
        if (dir >= 0) close(dir);
        if (input >= 0) close(input);
        if (reply >= 0) close(reply);
        errno = error;
    }
    input_close(&in);
    return -1;
}

static void result_name(char name[64], uint64_t id, int64_t deadline)
{
    snprintf(name, 64, "%" PRIu64 "-%" PRId64 ".json", id, deadline);
}

int job_market_commit(const job_state *state, const job_market_stage *stage, uint64_t id,
                      int64_t deadline)
{
    char *reply = malloc(RESULT_MAX + 1);
    if (!reply) return -1;
    size_t n;
    int rc = job_read_private(stage->fd, "reply", reply, RESULT_MAX + 1, &n);
    if (!rc && (n < 3 || reply[0] != '{' || reply[n - 2] != '}' || reply[n - 1] != '\n' ||
                memchr(reply, 0, n) || memchr(reply, '\n', n - 1) ||
                !memmem(reply, n, "\"kind\":\"caravansary.market.scrape@1\"",
                        sizeof "\"kind\":\"caravansary.market.scrape@1\"" - 1)))
        rc = fail(EINVAL);
    if (!rc) {
        char name[64];
        result_name(name, id, deadline);
        rc = job_publish(state->results, name, reply, n, false);
    }
    int error = errno;
    free(reply);
    errno = error;
    return rc;
}

int job_market_show(const job_state *state, uint64_t id, int64_t deadline)
{
    char *reply = malloc(RESULT_MAX + 1), name[64];
    if (!reply) return -1;
    result_name(name, id, deadline);
    size_t n;
    int rc = job_read_private(state->results, name, reply, RESULT_MAX + 1, &n);
    if (!rc) rc = job_write_all(STDOUT_FILENO, reply, n);
    int error = errno;
    free(reply);
    errno = error;
    return rc;
}
