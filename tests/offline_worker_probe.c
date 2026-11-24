#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

static const char version[] = "finpred.offline-worker@1\n";
static char contents[65536];

static int emit(const char *p, size_t size)
{
    while (size) {
        ssize_t n = write(1, p, size);
        if (n <= 0) return 0;
        p += n;
        size -= (size_t)n;
    }
    return 1;
}

int main(void)
{
    size_t used = 0;
    while (used < sizeof(contents)) {
        ssize_t n = read(0, contents + used, sizeof(contents) - used);
        if (n < 0) return 3;
        if (n == 0) break;
        used += (size_t)n;
    }
    if (used < sizeof(version)) return 3;
    switch (contents[sizeof(version) - 1]) {
    case 'E':
        return !emit(contents, used);
    case 'R':
        if (getenv("FINPRED_WORKER_TEST_SECRET") != NULL ||
            open("/worker", O_WRONLY) != -1 || errno != EPERM ||
            open("/etc/passwd", O_RDONLY) != -1 || errno != EPERM ||
            socket(AF_INET, SOCK_STREAM, 0) != -1 || errno != EPERM ||
            fork() != -1 || errno != EPERM ||
            write(2, "diagnostic", 10) != -1 || errno != EPERM ||
            read(57, contents, 1) != -1 || errno != EPERM ||
            mmap(NULL, 4096, PROT_READ, MAP_PRIVATE, 57, 0) != MAP_FAILED || errno != EPERM ||
            mmap(NULL, 256 * 1024 * 1024, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0) != MAP_FAILED || errno != ENOMEM)
            return 4;
        return !(emit(version, sizeof(version) - 1) && emit("restricted\n", 11));
    case 'F':
        if (!emit(contents, used)) return 4;
        return 5;
    case 'B':
        return !emit("invalid\n", 8);
    case 'L':
        return !(emit(contents, used) && emit(contents, sizeof(contents)));
    case 'T':
        for (;;) {}
    default:
        return 3;
    }
}
