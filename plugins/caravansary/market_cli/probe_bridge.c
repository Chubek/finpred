#define _GNU_SOURCE
#include "on1x_runtime.h"
#include "probe_wire.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/close_range.h>
#include <poll.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void close_fd(int *fd)
{
    if (*fd >= 0) close(*fd);
    *fd = -1;
}

static bool trusted_owner(const struct stat *st)
{
    return st->st_uid == 0 || st->st_uid == geteuid();
}

static int trusted_sibling(void)
{
    char path[PATH_MAX + 1];
    ssize_t length = readlink("/proc/self/exe", path, sizeof path - 1);
    if (length <= 0 || (size_t)length >= sizeof path - 1) return -1;
    path[length] = '\0';
    char *end = strrchr(path, '/');
    if (!end) return -1;
    if (end == path) ++end;
    *end = '\0';
    int dir = open(path, O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dir < 0) return -1;
    struct stat st;
    if (fstat(dir, &st) != 0 || !S_ISDIR(st.st_mode) || !trusted_owner(&st) ||
        (st.st_mode & (S_IWGRP | S_IWOTH))) {
        close(dir);
        return -1;
    }
    int program = openat(dir, CARAVANSARY_MARKET_PROBE_SIBLING,
                         O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    close(dir);
    if (program < 0) return -1;
    if (fstat(program, &st) != 0 || !S_ISREG(st.st_mode) || !trusted_owner(&st) ||
        !(st.st_mode & (S_IXUSR | S_IXGRP | S_IXOTH)) ||
        (st.st_mode & (S_IWGRP | S_IWOTH | S_ISUID | S_ISGID))) {
        close(program);
        return -1;
    }
    return program;
}

static int64_t monotonic_ms(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return -1;
    return (int64_t)t.tv_sec * INT64_C(1000) + t.tv_nsec / 1000000;
}

static int remaining_ms(int64_t end)
{
    int64_t now = monotonic_ms();
    if (now < 0 || now >= end) return 0;
    return (int)(end - now);
}

static bool nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) >= 0;
}

/* Drive both pipes independently: no hanging on pipe capacity even if the
 * companion rejects its input early. Do not follow a chosen path, inherit a
 * user environment, use the shell, or pass the capture as an argument. */
static bool exchange(int *in, int *out, const char *request, size_t length,
                     char *reply, size_t *reply_length, int64_t deadline)
{
    size_t sent = 0;
    const size_t cap = CARAVANSARY_MARKET_PROBE_OUTPUT_LIMIT;
    *reply_length = 0;
    if (!nonblocking(*in) || !nonblocking(*out)) return false;
    struct sigaction ignored = { .sa_handler = SIG_IGN };
    struct sigaction old;
    if (sigemptyset(&ignored.sa_mask) != 0 || sigaction(SIGPIPE, &ignored, &old) != 0) return false;
    bool success = false;
    while (*in >= 0 || *out >= 0) {
        struct pollfd fds[] = {{*in, POLLOUT, 0}, {*out, POLLIN, 0}};
        int wait = remaining_ms(deadline);
        if (wait <= 0) break;
        int ready = poll(fds, 2, wait);
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0) break;
        if (fds[0].revents != 0) {
            ssize_t n = write(*in, request + sent, length - sent);
            if (n > 0) {
                sent += (size_t)n;
                if (sent == length) close_fd(in);  /* EOF ends the request. */
            } else if (n == 0 || (errno != EAGAIN && errno != EINTR)) {
                break;
            }
        }
        if (fds[1].revents != 0) {
            ssize_t n = read(*out, reply + *reply_length, cap + 1 - *reply_length);
            if (n > 0) {
                *reply_length += (size_t)n;
                if (*reply_length > cap) break;
            } else if (n == 0) {
                close_fd(out);
            } else if (errno != EAGAIN && errno != EINTR) {
                break;
            }
        }
    }
    if (*in < 0 && *out < 0 && *reply_length > 0 &&
        !memchr(reply, '\0', *reply_length)) success = true;
    if (sigaction(SIGPIPE, &old, NULL) != 0) success = false;
    return success;
}

static bool exited_before(int pidfd, int64_t deadline)
{
    struct pollfd process = { pidfd, POLLIN, 0 };
    for (;;) {
        int wait = remaining_ms(deadline);
        if (wait <= 0) return false;
        int ready = poll(&process, 1, wait);
        if (ready < 0 && errno == EINTR) continue;
        return ready > 0 && (process.revents & POLLIN);
    }
}

static void execute_companion(int program, int input, int output, pid_t parent)
{
    char *const argv[] = { CARAVANSARY_MARKET_PROBE_SIBLING, NULL };
    char *const env[] = { "LC_ALL=C", NULL };
    if (prctl(PR_SET_PDEATHSIG, (unsigned long)SIGKILL, 0UL, 0UL, 0UL) == 0 &&
        getppid() == parent &&
        prctl(PR_SET_NO_NEW_PRIVS, 1UL, 0UL, 0UL, 0UL) == 0 &&
        dup2(input, STDIN_FILENO) >= 0 && dup2(output, STDOUT_FILENO) >= 0 &&
        syscall(SYS_close_range, 3u, UINT_MAX, CLOSE_RANGE_CLOEXEC) == 0)
        fexecve(program, argv, env);
    _exit(126);
}

const char *caravansary_market_probe_forward(const char *envelope)
{
    const char *error = "fixed offline market probe failed or exceeded its limits";
    size_t length = strlen(envelope);
    if (length == 0 || length > CARAVANSARY_MARKET_PROBE_INPUT_LIMIT) {
        on1x_tool_fail("market probe input exceeds its byte limit");
        return "";
    }
    if (fcntl(STDIN_FILENO, F_GETFD) < 0 || fcntl(STDOUT_FILENO, F_GETFD) < 0 ||
        fcntl(STDERR_FILENO, F_GETFD) < 0) {
        on1x_tool_fail("market probe requires open standard streams");
        return "";
    }
    int program = trusted_sibling();
    if (program < 0) {
        on1x_tool_fail("missing or untrusted fixed market probe companion");
        return "";
    }
    char *reply = malloc(CARAVANSARY_MARKET_PROBE_OUTPUT_LIMIT + 1);
    int request[] = {-1, -1};
    int response[] = {-1, -1};
    int pidfd = -1;
    pid_t child = -1;
    size_t reply_length = 0;
    bool success = false;
    int64_t started = monotonic_ms();
    if (reply && started >= 0 && pipe2(request, O_CLOEXEC) == 0 &&
        pipe2(response, O_CLOEXEC) == 0) {
        pid_t parent = getpid();
        child = fork();
        if (child == 0) execute_companion(program, request[0], response[1], parent);
        if (child > 0) {
            close_fd(&request[0]);
            close_fd(&response[1]);
            const int64_t deadline = started + CARAVANSARY_MARKET_PROBE_TIMEOUT_MS;
            pidfd = (int)syscall(SYS_pidfd_open, child, 0);
            success = pidfd >= 0 &&
                      exchange(&request[1], &response[0], envelope, length, reply, &reply_length, deadline) &&
                      exited_before(pidfd, deadline);
        }
    }
    close_fd(&request[0]);
    close_fd(&request[1]);
    close_fd(&response[0]);
    close_fd(&response[1]);
    close_fd(&pidfd);
    close_fd(&program);
    if (child > 0) {
        if (!success) (void)kill(child, SIGKILL);
        int status = 0;
        pid_t reaped;
        do { reaped = waitpid(child, &status, 0); } while (reaped < 0 && errno == EINTR);
        success = success && reaped == child && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    }
    const char *value = "";
    if (success) {
        reply[reply_length] = '\0';
        value = on1x_text_slice(reply, 0, (int64_t)reply_length);
    }
    free(reply);
    if (!success) on1x_tool_fail(error);
    return value;
}
