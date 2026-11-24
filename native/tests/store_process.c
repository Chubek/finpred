#define _GNU_SOURCE
#include "store.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)

/* Test-only checkpoints around real syscalls. No production hooks. */
static const char *checkpoint;
static unsigned file_syncs, dir_syncs;
static struct stat last_file_sync, last_dir_sync;

ssize_t __real_write(int fd, const void *buf, size_t size);
int __real_fsync(int fd);
int __real_linkat(int olddir, const char *oldname, int newdir, const char *newname, int flags);

static int at(const char *name)
{
    return checkpoint && strcmp(checkpoint, name) == 0;
}

static void pause_at(const char *name)
{
    if (!at(name)) return;
    checkpoint = NULL;
    CHECK(puts(name) >= 0 && fflush(stdout) == 0);
    CHECK(getchar() == 'r');
}

ssize_t __wrap_write(int fd, const void *buf, size_t size)
{
    if (!at("partial-write")) return __real_write(fd, buf, size);
    CHECK(size > 1);
    ssize_t wrote = __real_write(fd, buf, size / 2);
    CHECK(wrote == (ssize_t)(size / 2));
    pause_at("partial-write");
    return wrote;
}

int __wrap_fsync(int fd)
{
    struct stat st;
    CHECK(fstat(fd, &st) == 0);
    int is_dir = S_ISDIR(st.st_mode);
    if (is_dir) ++dir_syncs;
    else ++file_syncs;
    int rc = __real_fsync(fd);
    if (rc == 0) {
        if (is_dir) last_dir_sync = st;
        else last_file_sync = st;
        pause_at(is_dir ? "dir-synced" : "file-synced");
    }
    return rc;
}

int __wrap_linkat(int olddir, const char *oldname, int newdir, const char *newname, int flags)
{
    int rc = __real_linkat(olddir, oldname, newdir, newname, flags);
    if (rc == 0) pause_at("linked");
    return rc;
}

static const char artifact_id[] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static const char run_id[] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

static void expect_sync_targets(int root, fp_kind kind, const char *id)
{
    const char *dir = kind == FP_RUN ? "runs" : "artifacts";
    char path[96];
    int n = snprintf(path, sizeof path, "%s/%s%s.txt", dir, kind == FP_RUN ? "" : "blake3-", id);
    CHECK(n >= 0 && (size_t)n < sizeof path);
    struct stat installed, destination;
    CHECK(file_syncs && dir_syncs);
    CHECK(fstatat(root, path, &installed, AT_SYMLINK_NOFOLLOW) == 0);
    CHECK(fstatat(root, dir, &destination, AT_SYMLINK_NOFOLLOW) == 0);
    CHECK(installed.st_dev == last_file_sync.st_dev && installed.st_ino == last_file_sync.st_ino);
    CHECK(destination.st_dev == last_dir_sync.st_dev && destination.st_ino == last_dir_sync.st_ino);
}

int main(int argc, char **argv)
{
    CHECK(argc >= 3);
    int root = atoi(argv[1]);
    const char *op = argv[2];
    int reader = strcmp(op, "read") == 0;
    fp_store *store = NULL;
    CHECK(fp_store_open(root, reader ? FP_READER : FP_WRITER, &store).status == FP_OK);
    if (strcmp(op, "provision") == 0) {
        CHECK(argc == 3);
        fp_store_close(store);
        CHECK(close(root) == 0);
        return 0;
    }
    if (reader) CHECK(file_syncs == 0 && dir_syncs == 0);
    file_syncs = dir_syncs = 0; /* Count the object operation, not writer open. */

    CHECK(argc == 5 || argc == 6);
    CHECK(strcmp(argv[3], "run") == 0 || strcmp(argv[3], "artifact") == 0);
    fp_kind kind = strcmp(argv[3], "run") == 0 ? FP_RUN : FP_ARTIFACT;
    CHECK(strcmp(argv[4], "same") == 0 || strcmp(argv[4], "different") == 0);
    int different = strcmp(argv[4], "different") == 0;
    const char *id = kind == FP_RUN ? run_id : artifact_id;
    size_t size = kind == FP_RUN ? FP_RUN_SIZE : 16384;
    char payload[16384];
    memset(payload, kind == FP_RUN ? 'm' : 'a', size);
    if (kind == FP_RUN) memcpy(payload, artifact_id, sizeof artifact_id - 1);
    /* Conflict is equal-length and differs only at the final byte. */
    if (different) payload[size - 1] = '!';

    if (reader) {
        CHECK(argc == 5);
        char *bytes = NULL;
        size_t got = 0;
        fp_result r = fp_store_read(store, kind, id, &bytes, &got);
        if (r.status == FP_MISSING) {
            CHECK(!bytes && !got);
            puts("missing");
        } else {
            CHECK(r.status == FP_OK && got == size && bytes[got] == '\0');
            CHECK(memcmp(bytes, payload, size) == 0);
            puts("complete");
        }
        free(bytes);
        CHECK(file_syncs == 0 && dir_syncs == 0);
    } else {
        CHECK(strcmp(op, "install") == 0);
        if (argc == 6) checkpoint = argv[5];
        fp_result r = fp_store_install(store, kind, id, payload, size);
        CHECK(!checkpoint);
        if (r.status == FP_CONFLICT) {
            CHECK(r.name == FP_EXISTING);
            printf("conflict");
        } else {
            CHECK(r.status == FP_OK && (r.name == FP_CREATED || r.name == FP_EXISTING));
            expect_sync_targets(root, kind, id);
            printf("%s", r.name == FP_CREATED ? "created" : "identical");
        }
        printf(" %u %u\n", file_syncs, dir_syncs);
    }
    fp_store_close(store);
    CHECK(close(root) == 0);
    return 0;
}
