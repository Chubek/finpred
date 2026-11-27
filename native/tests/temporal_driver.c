#define _GNU_SOURCE
#include "temporal.h"
#include "mulib-cryptohash.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *pause_at;
static unsigned fail_sync, syncs, links;
static int tracking, trace;

static void trace_inode(const char *event, int fd)
{
    struct stat st;
    if (fstat(fd, &st)) _exit(91);
    printf("%s %ju\n", event, (uintmax_t)st.st_ino);
}

static void checkpoint(const char *name)
{
    if (pause_at && !strcmp(pause_at, name)) {
        puts(name);
        if (fflush(stdout) || getchar() == EOF) _exit(90);
    }
}

int __real_fsync(int fd);
int __wrap_fsync(int fd)
{
    if (!tracking) return __real_fsync(fd);
    char step[32];
    ++syncs;
    snprintf(step, sizeof step, "before-sync-%u", syncs);
    checkpoint(step);
    if (syncs == fail_sync) {
        errno = EIO;
        return -1;
    }
    int rc = __real_fsync(fd);
    if (!rc) {
        if (trace) trace_inode("sync", fd);
        snprintf(step, sizeof step, "after-sync-%u", syncs);
        checkpoint(step);
    }
    return rc;
}

int __real_linkat(int olddir, const char *oldname, int newdir, const char *newname, int flags);
int __wrap_linkat(int olddir, const char *oldname, int newdir, const char *newname, int flags)
{
    int rc = __real_linkat(olddir, oldname, newdir, newname, flags);
    if (tracking && !rc) {
        ++links;
        if (trace) {
            struct stat st;
            if (fstatat(newdir, newname, &st, AT_SYMLINK_NOFOLLOW)) _exit(91);
            printf("link %ju\n", (uintmax_t)st.st_ino);
        }
        checkpoint("after-link");
    }
    return rc;
}

static int hash_input(void)
{
    unsigned char block[4096], digest[32];
    mulib_blake3_ctx ctx;
    if (!mulib_blake3_init(&ctx)) return 2;
    for (;;) {
        size_t n = fread(block, 1, sizeof block, stdin);
        if (n && !mulib_blake3_update(&ctx, block, n)) return 2;
        if (n < sizeof block) break;
    }
    if (ferror(stdin) || !mulib_blake3_final(&ctx, digest, sizeof digest)) return 2;
    for (size_t i = 0; i < sizeof digest; ++i) printf("%02x", (unsigned)digest[i]);
    putchar('\n');
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "hash")) return hash_input();
    if (argc < 3) return 2;
    const char *mode = argv[2];
    int read_only = !strcmp(mode, "replay") || !strcmp(mode, "readonly-resume");
    fp_store *s;
    fp_result open_result = fp_store_open(atoi(argv[1]), read_only ? FP_READER : FP_WRITER, &s);
    if (open_result.status != FP_OK) return 3;
    if (!strcmp(mode, "provision")) {
        fp_store_close(s);
        return 0;
    }
    if (argc < 4) return 2;
    const char *fault = getenv("FP_TEST_FAIL_SYNC");
    if (fault) fail_sync = (unsigned)strtoul(fault, NULL, 10);
    pause_at = getenv("FP_TEST_PAUSE");
    trace = getenv("FP_TEST_TRACE") != NULL;
    tracking = 1;
    fp_temporal_result r;
    if (!strcmp(mode, "publish") && argc >= 7 && argc - 6 <= FP_TEMPORAL_MAX_KEYS + 1) {
        uint64_t keys[FP_TEMPORAL_MAX_KEYS + 1];
        for (int i = 6; i < argc; ++i) keys[i-6] = strtoumax(argv[i], NULL, 10);
        r = fp_temporal_publish(s, argv[3], strtoimax(argv[4], NULL, 10),
                                strtoimax(argv[5], NULL, 10), keys, (size_t)(argc - 6));
    } else if ((!strcmp(mode, "resume") || !strcmp(mode, "readonly-resume")) && argc == 4) {
        r = fp_temporal_resume(s, argv[3]);
    } else if (!strcmp(mode, "replay") && argc == 4) {
        r = fp_temporal_replay(s, argv[3]);
    } else {
        fp_store_close(s);
        return 2;
    }
    fp_store_close(s);
    const char *const stages[] = {"query", "catalog", "parent", "commit"};
    const char *const statuses[] = {"ok", "invalid", "denied", "scope", "missing",
                                    "conflict", "limit", "unsupported", "io"};
    const char *const phases[] = {"validate", "open", "read", "write", "file-sync",
                                  "install", "dir-sync", "close"};
    const char *const names[] = {"unchanged", "existing", "created", "uncertain"};
    printf("%s %s %s %s %u %u %s\n", stages[r.stage], statuses[r.detail.status],
           phases[r.detail.phase], names[r.detail.name], syncs, links,
           *r.commit_id ? r.commit_id : "-");
    return 0;
}
