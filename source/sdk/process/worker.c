/* Optional Linux x86-64 supervisor for one offline, static ELF worker. */
#define _GNU_SOURCE
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if !defined(__linux__) || !defined(__x86_64__) || defined(__ILP32__)
#error "Worker profile requires Linux x86-64"
#endif

enum { max_message = 65536, max_executable = 8 * 1024 * 1024, deadline_ms = 2000 };
static const char version[] = "finpred.offline-worker@1\n";
static unsigned char message[max_message + 1];

/* Everything not listed is denied, including the x32 syscall number space.
 * Only the two protocol descriptors are authorized for data I/O. */
#define SC_ALLOW SECCOMP_RET_ALLOW
#define SC_DENY (SECCOMP_RET_ERRNO | EPERM)
#define SC_ARG0 offsetof(struct seccomp_data, args[0])
#define ALLOW(n) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_##n, 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SC_ALLOW)
#define ALLOW_FD(n, fd) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_##n, 0, 4), \
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, SC_ARG0), \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (fd), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SC_ALLOW), \
    BPF_STMT(BPF_RET | BPF_K, SC_DENY)
static const struct sock_filter rules[] = {
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
    ALLOW_FD(read, STDIN_FILENO),
    ALLOW_FD(write, STDOUT_FILENO),
    ALLOW(execve), /* Bubblewrap enters /worker with the filter already installed. */
    ALLOW(exit), ALLOW(exit_group),
    ALLOW(arch_prctl), ALLOW(set_tid_address), ALLOW(set_robust_list), ALLOW(rseq),
    ALLOW(brk), ALLOW(mprotect), ALLOW(munmap), ALLOW(mremap), ALLOW(madvise),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_mmap, 0, 4),
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[3])),
    BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, MAP_ANONYMOUS, 0, 1),
    BPF_STMT(BPF_RET | BPF_K, SC_ALLOW),
    BPF_STMT(BPF_RET | BPF_K, SC_DENY),
    ALLOW(rt_sigaction), ALLOW(rt_sigprocmask), ALLOW(rt_sigreturn),
    ALLOW(getrandom), ALLOW(clock_gettime), ALLOW(getpid), ALLOW(gettid),
    BPF_STMT(BPF_RET | BPF_K, SC_DENY)
};

static ssize_t read_again(int fd, void *bytes, size_t len)
{
    ssize_t n;
    do { n = read(fd, bytes, len); } while (n == -1 && errno == EINTR);
    return n;
}

static int write_all(int fd, const void *bytes, size_t len)
{
    const unsigned char *p = bytes;
    while (len) {
        ssize_t n = write(fd, p, len);
        if (n == -1 && errno == EINTR) continue;
        if (n <= 0) return 0;
        p += n;
        len -= (size_t)n;
    }
    return 1;
}

static int sealed(int fd)
{
    return lseek(fd, 0, SEEK_SET) == 0 &&
        fcntl(fd, F_ADD_SEALS, F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE) == 0;
}

static int snapshot(int fd, size_t cap)
{
    int out = memfd_create("finpred-executable", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    unsigned char buf[8192];
    size_t used = 0;
    if (out < 0) return -1;
    for (;;) {
        ssize_t n = read_again(fd, buf, sizeof(buf));
        if (n == 0 && used && sealed(out)) return out;
        if (n <= 0 || (size_t)n > cap - used || !write_all(out, buf, (size_t)n)) break;
        used += (size_t)n;
    }
    close(out);
    return -1;
}

static int static_elf(int fd)
{
    /* Verify the sealed snapshot, not the mutable input pathname. */
    Elf64_Ehdr eh;
    struct stat st;
    if (fstat(fd, &st) || pread(fd, &eh, sizeof(eh), 0) != (ssize_t)sizeof(eh) ||
        memcmp(eh.e_ident, ELFMAG, SELFMAG) || eh.e_ident[EI_CLASS] != ELFCLASS64 ||
        eh.e_ident[EI_DATA] != ELFDATA2LSB || eh.e_machine != EM_X86_64 ||
        eh.e_type != ET_EXEC || eh.e_phentsize != sizeof(Elf64_Phdr) ||
        eh.e_phnum == 0 || eh.e_phnum > 128 ||
        eh.e_phoff > (uint64_t)st.st_size ||
        (uint64_t)eh.e_phnum * sizeof(Elf64_Phdr) > (uint64_t)st.st_size - eh.e_phoff)
        return 0;
    for (uint16_t i = 0; i < eh.e_phnum; ++i) {
        Elf64_Phdr ph;
        off_t at = (off_t)(eh.e_phoff + (uint64_t)i * sizeof(ph));
        if (pread(fd, &ph, sizeof(ph), at) != (ssize_t)sizeof(ph) || ph.p_type == PT_INTERP)
            return 0;
    }
    return 1;
}

static int framing(const unsigned char *data, size_t n)
{
    return n >= sizeof(version) - 1 && n <= max_message &&
        memcmp(data, version, sizeof(version) - 1) == 0;
}

static int resource_limit(int r, rlim_t value)
{
    struct rlimit lim = {value, value};
    return setrlimit(r, &lim) == 0;
}

static void child(pid_t supervisor, int input, int output, int executable, int filter)
{
    /* Cover the interval before Bubblewrap installs its parent-death guard. */
    if (prctl(PR_SET_PDEATHSIG, (unsigned long)SIGKILL, 0L, 0L, 0L) != 0 ||
        getppid() != supervisor)
        _exit(125);

    /* Temporary descriptors are above all of the chosen destination numbers. */
    int binary = fcntl(executable, F_DUPFD_CLOEXEC, 5);
    int seccomp = fcntl(filter, F_DUPFD_CLOEXEC, 5);
    if (binary < 0 || seccomp < 0 ||
        dup2(input, STDIN_FILENO) < 0 || dup2(output, STDOUT_FILENO) < 0 ||
        dup2(binary, 3) != 3 || dup2(seccomp, 4) != 4 ||
        syscall(SYS_close_range, 5u, ~0u, 0u) != 0 ||
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0L, 0L, 0L) != 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1L, 0L, 0L, 0L) != 0 ||
        !resource_limit(RLIMIT_AS, 128 * 1024 * 1024) ||
        !resource_limit(RLIMIT_CPU, 1) || !resource_limit(RLIMIT_CORE, 0) ||
        !resource_limit(RLIMIT_NOFILE, 64)) {
        fputs("offline worker: could not constrain sandbox launcher\n", stderr);
        _exit(125);
    }

    char *const args[] = {
        "/usr/bin/bwrap", "--unshare-all", "--unshare-user", "--disable-userns", "--cap-drop", "ALL",
        "--clearenv", "--die-with-parent", "--new-session", "--as-pid-1",
        "--perms", "0555", "--ro-bind-data", "3", "/worker", "--remount-ro", "/",
        "--seccomp", "4", "--", "/worker", NULL,
    };
    char *const env[] = {NULL};
    /* Only launcher diagnostics can reach stderr; seccomp denies worker I/O on fd 2. */
    execve(args[0], args, env);
    perror("offline worker: execve /usr/bin/bwrap");
    _exit(125);
}

static int64_t now_ms(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -1;
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int supervise(pid_t pid, int pipe, int64_t deadline)
{
    size_t used = 0;
    int status, reached_eof = 0;
    for (;;) {
        int64_t now = now_ms();
        if (now < 0 || now >= deadline) break;
        /* Reap only after EOF; success must include complete framed output. */
        if (reached_eof) {
            pid_t result = waitpid(pid, &status, WNOHANG);
            if (result == pid) {
                return WIFEXITED(status) && WEXITSTATUS(status) == 0 &&
                    framing(message, used) && write_all(STDOUT_FILENO, message, used);
            }
            if (result == -1 && errno != EINTR) return 0;
            (void)poll(NULL, 0, 5);
            continue;
        }
        struct pollfd p = {pipe, POLLIN, 0};
        int ready = poll(&p, 1, (int)(deadline - now));
        if (ready == -1 && errno == EINTR) continue;
        if (ready <= 0) break;
        ssize_t n = read(pipe, message + used, sizeof(message) - used);
        if (n == -1 && errno == EINTR) continue;
        if (n < 0) break;
        used += (size_t)n;
        if (used > max_message) break;
        reached_eof = n == 0;
    }
    (void)kill(pid, SIGKILL);
    while (waitpid(pid, &status, 0) == -1 && errno == EINTR) {}
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2 || argv[1][0] != '/') {
        fputs("usage: finpred-offline-worker /absolute/static-elf < framed-request\n", stderr);
        return 2;
    }
    if (getuid() == 0 || getuid() != geteuid() || getgid() != getegid()) {
        fputs("offline worker: run under ordinary unprivileged credentials\n", stderr);
        return 2;
    }

    /* Require that the launching host supplied the three standard channels. */
    for (int fd = 0; fd < 3; ++fd)
        if (fcntl(fd, F_GETFD) < 0) return 2;
    /* An exec caller may have ignored SIGCHLD or blocked signals. Own the
     * child lifecycle rather than inheriting that process-management policy. */
    struct sigaction reap = {.sa_handler = SIG_DFL};
    sigset_t signals;
    if (sigemptyset(&reap.sa_mask) != 0 || sigaction(SIGCHLD, &reap, NULL) != 0 ||
        sigemptyset(&signals) != 0 || sigprocmask(SIG_SETMASK, &signals, NULL) != 0)
        return 2;
    int source = open(argv[1], O_PATH | O_CLOEXEC | O_NOFOLLOW);
    struct stat st;
    int binary = -1;
    if (source >= 0) {
        if (fstat(source, &st) == 0 && S_ISREG(st.st_mode) && st.st_size > 0 &&
            st.st_size <= max_executable) {
            char procfd[64];
            int n = snprintf(procfd, sizeof(procfd), "/proc/self/fd/%d", source);
            if (n > 0 && (size_t)n < sizeof(procfd)) {
                int reader = open(procfd, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
                if (reader >= 0) {
                    binary = snapshot(reader, max_executable);
                    close(reader);
                }
            }
        }
        close(source);
    }
    if (binary < 0 || !static_elf(binary)) {
        fputs("offline worker: invalid executable snapshot\n", stderr);
        return 2;
    }
    size_t used = 0;
    while (used <= max_message) {
        ssize_t n = read_again(STDIN_FILENO, message + used, sizeof(message) - used);
        if (n < 0) return 2;
        if (n == 0) break;
        used += (size_t)n;
    }
    if (!framing(message, used)) {
        fputs("offline worker: invalid request frame\n", stderr);
        return 2;
    }
    int input = memfd_create("finpred-request", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    int filter = memfd_create("finpred-seccomp", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    int output[2];
    if (input < 0 || filter < 0 ||
        !write_all(input, message, used) || !sealed(input) ||
        !write_all(filter, rules, sizeof(rules)) || !sealed(filter) ||
        pipe2(output, O_CLOEXEC) != 0)
        return 2;
    int64_t start = now_ms();
    if (start < 0) return 2;
    pid_t supervisor = getpid();
    pid_t pid = fork();
    if (pid < 0) return 2;
    if (pid == 0) child(supervisor, input, output[1], binary, filter);
    close(output[1]);
    close(input);
    close(binary);
    close(filter);
    if (supervise(pid, output[0], start + deadline_ms)) return 0;
    fputs("offline worker: isolation setup, worker, or response rejected\n", stderr);
    return 1;
}
