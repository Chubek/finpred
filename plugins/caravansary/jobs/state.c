#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "state.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define SOURCE_VERSION "CVSOURCE1 "
#define PROFILE_VERSION "CVPROFILE1 "
#define CLOCK_VERSION "CVCLOCK1 "
#define REVOKED_RECORD "CVREVOKED1\n"
#define SOURCE_HEADER (sizeof SOURCE_VERSION - 1 + 65)
#define DIR_FLAGS (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
#define FILE_FLAGS (O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)

static int fail(int error)
{
    errno = error;
    return -1;
}

static int close_error(int fd, int error)
{
    if (fd >= 0) close(fd);
    return fail(error);
}

static bool alnum_ascii(unsigned char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

bool job_key(const char *s)
{
    if (!alnum_ascii((unsigned char)s[0])) return false;
    for (size_t i = 1; s[i]; ++i) {
        unsigned char c = (unsigned char)s[i];
        if (i >= BASIS_HTTP_PROBE_KEY_MAX || (!alnum_ascii(c) && c != '_' && c != '-'))
            return false;
    }
    return true;
}

bool job_number(const char *s, uint64_t *out)
{
    uint64_t n = 0;
    if (!s[0] || (s[0] == '0' && s[1])) return false;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9' || n > (UINT64_MAX - (unsigned)(*s - '0')) / 10)
            return false;
        n = n * 10 + (unsigned)(*s - '0');
    }
    *out = n;
    return true;
}

bool job_format_clock(int64_t seconds, char out[21])
{
    time_t encoded = (time_t)seconds;
    struct tm tm;
    if (seconds < 0 || seconds > JOB_LAST_CLOCK || (int64_t)encoded != seconds ||
        !gmtime_r(&encoded, &tm)) return false;
    return snprintf(out, 21, "%04d-%02d-%02dT%02d:%02d:%02dZ",
                    tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                    tm.tm_hour, tm.tm_min, tm.tm_sec) == 20;
}

static int digits(const char *s, size_t n)
{
    int result = 0;
    for (size_t i = 0; i < n; ++i) {
        if (s[i] < '0' || s[i] > '9') return -1;
        result = result * 10 + s[i] - '0';
    }
    return result;
}

bool job_parse_clock(const char *s, int64_t *out)
{
    if (strlen(s) != 20 || s[4] != '-' || s[7] != '-' || s[10] != 'T' ||
        s[13] != ':' || s[16] != ':' || s[19] != 'Z') return false;
    int year = digits(s, 4), month = digits(s + 5, 2), day = digits(s + 8, 2);
    int hour = digits(s + 11, 2), min = digits(s + 14, 2), sec = digits(s + 17, 2);
    if (year < 1970 || month < 1 || month > 12 || day < 1 || day > 31 ||
        hour < 0 || hour > 23 || min < 0 || min > 59 || sec < 0 || sec > 59) return false;
    struct tm tm = {.tm_year = year - 1900, .tm_mon = month - 1, .tm_mday = day,
                    .tm_hour = hour, .tm_min = min, .tm_sec = sec};
    time_t value = timegm(&tm);
    char canonical[21];
    if (!job_format_clock((int64_t)value, canonical) || strcmp(s, canonical)) return false;
    *out = (int64_t)value;
    return true;
}

/* Every pathname component is stable against principals other than root and
 * euid. Sticky shared ancestors (e.g. /tmp) are OK if every child is trusted. */
static int check_directory(int fd, bool private)
{
    struct stat s;
    if (fstat(fd, &s) < 0) return -1;
    if (!S_ISDIR(s.st_mode)) return fail(ENOTDIR);
    if (private) {
        if (s.st_uid != geteuid() || (s.st_mode & 07777) != 0700) return fail(EACCES);
    } else if ((s.st_uid != 0 && s.st_uid != geteuid()) ||
               ((s.st_mode & 0022) && !(s.st_mode & S_ISVTX))) return fail(EACCES);
    return 0;
}

/* Walk all but the final component with fd-relative O_NOFOLLOW. */
static int open_parent(const char *path, char leaf[NAME_MAX + 1])
{
    if (path[0] != '/' || !path[1] || strlen(path) >= PATH_MAX) return fail(EINVAL);
    int fd = open("/", DIR_FLAGS);
    if (fd < 0) return -1;
    if (check_directory(fd, false) < 0) return close_error(fd, errno);
    for (const char *part = path + 1; ; ) {
        const char *slash = strchr(part, '/');
        size_t n = slash ? (size_t)(slash - part) : strlen(part);
        if (!n || n > NAME_MAX || (n == 1 && part[0] == '.') ||
            (n == 2 && part[0] == '.' && part[1] == '.')) return close_error(fd, EINVAL);
        memcpy(leaf, part, n);
        leaf[n] = 0;
        if (!slash) return fd;
        int next = openat(fd, leaf, DIR_FLAGS);
        if (next < 0) return close_error(fd, errno);
        close(fd);
        fd = next;
        if (check_directory(fd, false) < 0) return close_error(fd, errno);
        part = slash + 1;
    }
}

int job_sibling_path(const char *expected, char out[PATH_MAX])
{
    ssize_t n = readlink("/proc/self/exe", out, PATH_MAX - 1);
    if (n < 0) return -1;
    if (n == PATH_MAX - 1) return fail(ENAMETOOLONG);
    out[n] = 0;
    char *slash = strrchr(out, '/');
    if (!slash || (size_t)(slash - out) + 2 + strlen(expected) > PATH_MAX)
        return fail(ENAMETOOLONG);
    strcpy(slash + 1, expected);
    char leaf[NAME_MAX + 1];
    int parent = open_parent(out, leaf);
    if (parent < 0) return -1;
    struct stat directory, s;
    if (fstat(parent, &directory) < 0) return close_error(parent, errno);
    /* A sticky ancestor such as /tmp is fine, but the deployment directory
     * itself must not let other users place missing companions. */
    if (directory.st_mode & 0022) return close_error(parent, EACCES);
    if (fstatat(parent, leaf, &s, AT_SYMLINK_NOFOLLOW) < 0) return close_error(parent, errno);
    close(parent);
    if (!S_ISREG(s.st_mode) || (s.st_uid != geteuid() && s.st_uid != 0) ||
        (s.st_mode & 06022) || !(s.st_mode & 0111) || access(out, X_OK) < 0)
        return fail(EACCES);
    return 0;
}

static int open_private_dir(int parent, const char *name)
{
    int fd = openat(parent, name, DIR_FLAGS);
    if (fd >= 0 && check_directory(fd, true) < 0) return close_error(fd, errno);
    return fd;
}

void job_state_close(job_state *state)
{
    int error = errno;
    int *fds[] = {&state->sources, &state->profiles, &state->revoked,
                  &state->results, &state->kron, &state->root};
    for (size_t i = 0; i < sizeof fds / sizeof *fds; ++i) {
        if (*fds[i] >= 0) close(*fds[i]);
        *fds[i] = -1;
    }
    errno = error;
}

static int open_components(job_state *state, bool child)
{
    if ((state->sources = open_private_dir(state->root, "sources")) < 0 ||
        (state->profiles = open_private_dir(state->root, "profiles")) < 0 ||
        (state->revoked = open_private_dir(state->root, "revoked")) < 0 ||
        (!child && ((state->kron = open_private_dir(state->root, "kron")) < 0 ||
                    (state->results = open_private_dir(state->root, "results")) < 0))) {
        job_state_close(state);
        return -1;
    }
    return 0;
}

int job_state_child(job_state *state, bool market)
{
    *state = (job_state){-1, -1, -1, -1, -1, -1};
    char path[PATH_MAX], leaf[NAME_MAX + 1];
    if (!getcwd(path, sizeof path)) return -1;
    /* Market execution uses a unique attempt directory under the state. */
    if (market) {
        char *slash = strrchr(path, '/');
        int stage = open(".", DIR_FLAGS);
        if (stage < 0) return -1;
        int valid = check_directory(stage, true);
        close(stage);
        if (valid < 0 || !slash || strncmp(slash + 1, ".dispatch.", 10) ||
            strlen(slash + 11) != 16 || strspn(slash + 11, "0123456789abcdef") != 16)
            return fail(EACCES);
        *slash = 0;
    }
    int parent = open_parent(path, leaf);
    if (parent < 0) return -1;
    state->root = open_private_dir(parent, leaf);
    int error = errno;
    close(parent);
    if (state->root < 0) return fail(error);
    /* Resolve current state from the actual cwd, not caller-supplied keys. */
    struct stat current, opened;
    if (stat(market ? ".." : ".", &current) < 0 || fstat(state->root, &opened) < 0 ||
        current.st_dev != opened.st_dev || current.st_ino != opened.st_ino) {
        job_state_close(state);
        return fail(EACCES);
    }
    return open_components(state, true);
}

static int admin_open(const char *path, job_state *state, int *init_parent)
{
    *state = (job_state){-1, -1, -1, -1, -1, -1};
    char leaf[NAME_MAX + 1];
    if (strlen(path) + sizeof "/.dispatch.0123456789abcdef/input/capture.html" > PATH_MAX)
        return fail(ENAMETOOLONG);
    int parent = open_parent(path, leaf);
    if (parent < 0) return -1;
    if (init_parent && mkdirat(parent, leaf, 0700) < 0) return close_error(parent, errno);
    state->root = open_private_dir(parent, leaf);
    if (state->root < 0) return close_error(parent, errno);
    if (flock(state->root, LOCK_EX | LOCK_NB) < 0 ||
        (init_parent && (mkdirat(state->root, "sources", 0700) < 0 ||
                         mkdirat(state->root, "profiles", 0700) < 0 ||
                         mkdirat(state->root, "revoked", 0700) < 0 ||
                         mkdirat(state->root, "kron", 0700) < 0 ||
                         mkdirat(state->root, "results", 0700) < 0))) {
        job_state_close(state);
        return close_error(parent, errno);
    }
    if (open_components(state, false) < 0) return close_error(parent, errno);
    if (init_parent) *init_parent = parent;
    else close(parent);
    return 0;
}

int job_state_open(const char *path, job_state *state)
{
    return admin_open(path, state, NULL);
}

int job_state_begin_init(const char *path, job_state *state, int *parent)
{
    return admin_open(path, state, parent);
}

static int open_private_file(int dir, const char *name)
{
    int fd = openat(dir, name, FILE_FLAGS);
    if (fd < 0) return -1;
    struct stat s;
    if (fstat(fd, &s) < 0) return close_error(fd, errno);
    if (!S_ISREG(s.st_mode) || s.st_uid != geteuid() || s.st_nlink != 1 ||
        (s.st_mode & 07777) != 0600) return close_error(fd, EACCES);
    return fd;
}

int job_check_snapshot(const job_state *state)
{
    int fd = open_private_file(state->kron, "events.kvdb");
    return fd < 0 ? -1 : close(fd);
}

static int read_all(int fd, void *out, size_t capacity, size_t *length)
{
    unsigned char *bytes = out;
    size_t used = 0;
    while (used < capacity) {
        ssize_t n = read(fd, bytes + used, capacity - used);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return -1;
        if (!n) break;
        used += (size_t)n;
    }
    if (used == capacity) return fail(EFBIG);
    *length = used;
    return 0;
}

int job_read_private(int dir, const char *name, void *out, size_t capacity, size_t *length)
{
    int fd = open_private_file(dir, name);
    if (fd < 0) return -1;
    if (read_all(fd, out, capacity, length) < 0) return close_error(fd, errno);
    return close(fd);
}

int job_write_all(int fd, const void *data, size_t length)
{
    const unsigned char *bytes = data;
    while (length) {
        ssize_t n = write(fd, bytes, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return n < 0 ? -1 : fail(EIO);
        bytes += n;
        length -= (size_t)n;
    }
    return 0;
}

int job_publish(int dir, const char *name, const void *data, size_t size, bool replace)
{
    char stage[40];
    uint64_t nonce;
    if (getentropy(&nonce, sizeof nonce) < 0) return -1;
    snprintf(stage, sizeof stage, ".stage.%016" PRIx64, nonce);
    int fd = openat(dir, stage, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    int rc = job_write_all(fd, data, size);
    if (rc == 0) rc = fsync(fd);
    int error = errno;
    int closed = close(fd);
    if (!rc && closed < 0) { rc = -1; error = errno; }
    if (!rc && renameat2(dir, stage, dir, name, replace ? 0u : RENAME_NOREPLACE) < 0) {
        rc = -1;
        error = errno;
    }
    if (rc < 0) {
        unlinkat(dir, stage, 0);
        return fail(error);
    }
    return fsync(dir) < 0 ? 1 : 0;
}

static bool sha256(const unsigned char *bytes, size_t n, char hex[65])
{
    unsigned char hash[32];
    unsigned size;
    if (EVP_Digest(bytes, n, hash, &size, EVP_sha256(), NULL) != 1 || size != sizeof hash)
        return false;
    for (size_t i = 0; i < sizeof hash; ++i)
        snprintf(hex + 2 * i, 3, "%02x", (unsigned)hash[i]);
    return true;
}

int job_source_add(const job_state *state, const char *source, int input, job_source *out)
{
    if (!job_key(source)) return fail(EINVAL);
    unsigned char *data = malloc(SOURCE_HEADER + JOB_FIXTURE_MAX + 1);
    if (!data) return -1;
    int rc = read_all(input, data + SOURCE_HEADER, JOB_FIXTURE_MAX + 1, &out->bytes);
    if (!rc && !out->bytes) rc = fail(EINVAL);
    if (!rc && !sha256(data + SOURCE_HEADER, out->bytes, out->sha256)) rc = fail(EIO);
    if (!rc) {
        memcpy(data, SOURCE_VERSION, sizeof SOURCE_VERSION - 1);
        memcpy(data + sizeof SOURCE_VERSION - 1, out->sha256, 64);
        data[SOURCE_HEADER - 1] = '\n';
        rc = job_publish(state->sources, source, data, SOURCE_HEADER + out->bytes, false);
    }
    int error = errno;
    free(data);
    errno = error;
    return rc;
}

int job_source_bytes(const job_state *state, const char *source, job_source *out,
                     unsigned char **fixture)
{
    if (!job_key(source)) return fail(EINVAL);
    unsigned char *data = malloc(SOURCE_HEADER + JOB_FIXTURE_MAX + 1);
    if (!data) return -1;
    size_t length;
    int rc = job_read_private(state->sources, source, data, SOURCE_HEADER + JOB_FIXTURE_MAX + 1,
                              &length);
    if (!rc && (length <= SOURCE_HEADER || memcmp(data, SOURCE_VERSION, sizeof SOURCE_VERSION - 1)
                || data[SOURCE_HEADER - 1] != '\n')) rc = fail(EINVAL);
    if (!rc) {
        out->bytes = length - SOURCE_HEADER;
        if (!sha256(data + SOURCE_HEADER, out->bytes, out->sha256)) rc = fail(EIO);
        else if (memcmp(data + sizeof SOURCE_VERSION - 1, out->sha256, 64)) rc = fail(EILSEQ);
    }
    int error = errno;
    if (!rc && fixture) {
        memmove(data, data + SOURCE_HEADER, out->bytes);
        data[out->bytes] = 0;
        *fixture = data;
    } else free(data);
    errno = error;
    return rc;
}

int job_source_read(const job_state *state, const char *source, job_source *out)
{
    return job_source_bytes(state, source, out, NULL);
}

static int read_profile(const job_state *state, const char *profile, basis_http_probe_context *keys,
                        bool *active, char *expected)
{
    if (!job_key(profile)) return fail(EINVAL);
    char data[sizeof PROFILE_VERSION + 2 * BASIS_HTTP_PROBE_KEY_MAX + 68];
    size_t n;
    if (job_read_private(state->profiles, profile, data, sizeof data, &n) < 0) return -1;
    const size_t prefix_len = sizeof PROFILE_VERSION - 1;
    if (n <= prefix_len + 2 || memchr(data, 0, n) ||
        memcmp(data, PROFILE_VERSION, prefix_len) || data[n - 1] != '\n')
        return fail(EINVAL);
    data[n - 1] = 0;
    char *digest_sep = strrchr(data, ' ');
    if (!digest_sep || strlen(digest_sep + 1) != 64 ||
        strspn(digest_sep + 1, "0123456789abcdef") != 64) return fail(EINVAL);
    *digest_sep = 0;
    if (expected) strcpy(expected, digest_sep + 1);
    char *space = strchr(data + prefix_len, ' ');
    if (!space || (strcmp(space + 1, JOB_RUNNER) && strcmp(space + 1, JOB_MARKET_RUNNER) &&
                   strcmp(space + 1, JOB_JOE_RUNNER)))
        return fail(EINVAL);
    *space = 0;
    const char *source = data + prefix_len;
    if (!job_key(source)) return fail(EINVAL);
    *keys = (basis_http_probe_context){0};
    strcpy(keys->probe, source);
    strcpy(keys->runner, space + 1);
    strcpy(keys->context, profile);

    char marker[sizeof REVOKED_RECORD];
    if (job_read_private(state->revoked, profile, marker, sizeof marker, &n) < 0) {
        if (errno != ENOENT) return -1;
        *active = true;
    } else {
        if (n != sizeof REVOKED_RECORD - 1 || memcmp(marker, REVOKED_RECORD, n)) return fail(EINVAL);
        *active = false;
    }
    return 0;
}

int job_profile_read(const job_state *state, const char *profile, basis_http_probe_context *keys,
                     bool *active)
{
    return read_profile(state, profile, keys, active, NULL);
}

int job_profile_add(const job_state *state, const char *profile, const char *source, const char *runner)
{
    job_source verified;
    if (!job_key(profile) || (strcmp(runner, JOB_RUNNER) && strcmp(runner, JOB_MARKET_RUNNER) &&
                             strcmp(runner, JOB_JOE_RUNNER)))
        return fail(EINVAL);
    if (job_source_read(state, source, &verified) < 0) return -1;
    char data[sizeof PROFILE_VERSION + 2 * BASIS_HTTP_PROBE_KEY_MAX + 68];
    int n = snprintf(data, sizeof data, PROFILE_VERSION "%s %s %s\n", source, runner, verified.sha256);
    return job_publish(state->profiles, profile, data, (size_t)n, false);
}

int job_profile_disable(const job_state *state, const char *profile)
{
    basis_http_probe_context keys;
    bool active;
    if (job_profile_read(state, profile, &keys, &active) < 0) return -1;
    if (!active) return fsync(state->revoked) < 0 ? 1 : 0;
    return job_publish(state->revoked, profile, REVOKED_RECORD, sizeof REVOKED_RECORD - 1, false);
}

bool job_resolves(const job_state *state, const basis_http_probe_context *keys)
{
    basis_http_probe_context registered;
    bool active;
    job_source source;
    char expected[65];
    return read_profile(state, keys->context, &registered, &active, expected) == 0 && active &&
           !strcmp(keys->runner, registered.runner) &&
           !strcmp(keys->probe, registered.probe) &&
           job_source_read(state, registered.probe, &source) == 0 && !strcmp(source.sha256, expected);
}

int job_save_clock(const job_state *state, int64_t now, bool initialize)
{
    char previous[sizeof CLOCK_VERSION + 21];
    size_t n;
    bool exists = job_read_private(state->root, "clock", previous, sizeof previous, &n) == 0;
    if (exists) {
        const size_t prefix = sizeof CLOCK_VERSION - 1;
        int64_t floor;
        if (n != prefix + 21 || memchr(previous, 0, n) || previous[n - 1] != '\n' ||
            memcmp(previous, CLOCK_VERSION, prefix)) return fail(EINVAL);
        previous[n - 1] = 0;
        if (!job_parse_clock(previous + prefix, &floor)) return fail(EINVAL);
        if (now < floor) return fail(ERANGE);
        if (now == floor) return fsync(state->root) < 0 ? 1 : 0;
    } else if (errno != ENOENT || !initialize) {
        return -1;
    }
    char clock[21];
    if (!job_format_clock(now, clock)) return fail(EINVAL);
    char data[sizeof previous];
    int size = snprintf(data, sizeof data, CLOCK_VERSION "%s\n", clock);
    return job_publish(state->root, "clock", data, (size_t)size, exists);
}
