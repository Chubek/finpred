#define _GNU_SOURCE
#include "store.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)

/* Test binary only: fail the next selected barrier, or a write after 2 bytes. */
static int fail_sync_dir = -1, write_fault, sync_count;
int __real_fsync(int fd);
ssize_t __real_write(int fd, const void *buf, size_t n);
int __wrap_fsync(int fd)
{
    struct stat st;
    CHECK(fstat(fd, &st) == 0);
    ++sync_count;
    if (fail_sync_dir == !!S_ISDIR(st.st_mode)) {
        fail_sync_dir = -1; errno = EIO; return -1;
    }
    return __real_fsync(fd);
}
ssize_t __wrap_write(int fd, const void *buf, size_t n)
{
    if (write_fault == 1) { write_fault = 2; return __real_write(fd, buf, n > 2 ? 2 : n); }
    if (write_fault == 2) { write_fault = 0; errno = ENOSPC; return -1; }
    return __real_write(fd, buf, n);
}

static const char *id = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
static const char *second = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static const char *leaf = "blake3-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef.txt";

static void no_entries(int fd)
{
    DIR *d = fdopendir(openat(fd, ".", O_RDONLY | O_DIRECTORY));
    CHECK(d != NULL);
    struct dirent *e;
    while ((e = readdir(d))) CHECK(!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."));
    CHECK(closedir(d) == 0);
}

static void expect_read(fp_store *s, fp_kind kind, const char *key, const char *expected, size_t n)
{
    char *text; size_t len;
    CHECK(fp_store_read(s, kind, key, &text, &len).status == FP_OK);
    CHECK(len == n && !memcmp(text, expected, n) && text[n] == '\0');
    free(text);
}

static void expect_bad(fp_store *s, fp_status status)
{
    char *text; size_t len = 55;
    CHECK(fp_store_read(s, FP_ARTIFACT, id, &text, &len).status == status);
    CHECK(!text && !len);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, "abc", 3).status == status);
}

static void contention(fp_store *s)
{
    int gate[2];
    CHECK(pipe(gate) == 0);
    pid_t kids[6];
    for (int i = 0; i < 6; ++i) {
        kids[i] = fork(); CHECK(kids[i] >= 0);
        if (!kids[i]) {
            char byte;
            close(gate[1]);
            if (read(gate[0], &byte, 1) != 1) _exit(10);
            fp_result r = fp_store_install(s, FP_ARTIFACT, second, i % 2 ? "one" : "two", 3);
            _exit(r.status == FP_CONFLICT ? 2 :
                  r.status == FP_OK && r.name == FP_CREATED ? 0 :
                  r.status == FP_OK && r.name == FP_EXISTING ? 1 : 10);
        }
    }
    close(gate[0]);
    CHECK(write(gate[1], "xxxxxx", 6) == 6);
    close(gate[1]);
    int counts[] = {0,0,0};
    for (int i = 0; i < 6; ++i) {
        int status;
        CHECK(waitpid(kids[i], &status, 0) == kids[i]);
        CHECK(WIFEXITED(status) && WEXITSTATUS(status) < 3);
        ++counts[WEXITSTATUS(status)];
    }
    CHECK(counts[0] == 1 && counts[1] == 2 && counts[2] == 3);
}

/* Test client only: read through a reader grant and install into a separate
 * writer grant. The Python fixture supplies all artifact keys before run keys. */
static int copy_objects(int argc, char **argv)
{
    fp_store *reader, *writer;
    CHECK(argc > 5 && fp_store_open(atoi(argv[2]), FP_READER, &reader).status == FP_OK);
    CHECK(fp_store_open(atoi(argv[3]), FP_WRITER, &writer).status == FP_OK);
    for (int i = 4; i < argc; ++i) {
        const char *arg = argv[i];
        fp_kind kind = arg[0] == 'a' ? FP_ARTIFACT : FP_RUN;
        char *data; size_t size;
        CHECK(fp_store_read(reader, kind, arg + 1, &data, &size).status == FP_OK);
        fp_result r = fp_store_install(writer, kind, arg + 1, data, size);
        CHECK(r.status == FP_OK && r.name == FP_CREATED);
        free(data);
    }
    fp_store_close(writer);
    fp_store_close(reader);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "copy")) return copy_objects(argc, argv);
    CHECK(argc == 2);
    int root = atoi(argv[1]);
    fp_store *s = NULL, *reader = NULL;
    CHECK(fp_store_open(root, FP_READER, &s).status == FP_MISSING && !s);
    no_entries(root);
    CHECK(symlinkat(".", root, "artifacts") == 0);
    CHECK(fp_store_open(root, FP_WRITER, &s).status == FP_SCOPE && !s);
    CHECK(unlinkat(root, "artifacts", 0) == 0);
    CHECK(fchmod(root, 0770) == 0);
    CHECK(fp_store_open(root, FP_WRITER, &s).status == FP_SCOPE && !s);
    CHECK(fchmod(root, 0700) == 0);
    CHECK(fp_store_open(root, FP_WRITER, &s).status == FP_OK);
    int dir = openat(root, "artifacts", O_RDONLY | O_DIRECTORY);
    CHECK(dir >= 0);
    CHECK(mkfifoat(dir, leaf, 0600) == 0);
    expect_bad(s, FP_SCOPE);
    CHECK(unlinkat(dir, leaf, 0) == 0);
    CHECK(symlinkat("absent", dir, leaf) == 0);
    expect_bad(s, FP_SCOPE);
    CHECK(unlinkat(dir, leaf, 0) == 0);
    int file = openat(root, "sentinel", O_CREAT | O_EXCL | O_WRONLY, 0600);
    CHECK(file >= 0 && write(file, "abc", 3) == 3 && close(file) == 0);
    CHECK(linkat(root, "sentinel", dir, leaf, 0) == 0);
    expect_bad(s, FP_SCOPE);
    CHECK(unlinkat(dir, leaf, 0) == 0);

    CHECK(fp_store_install(s, FP_ARTIFACT, "../", "a", 1).status == FP_INVALID);
    CHECK(fp_store_install(s, FP_RUN, id, "a", 1).status == FP_INVALID);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, "a\0b", 3).status == FP_INVALID);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, "a", FP_ARTIFACT_MAX+1).status == FP_LIMIT);
    write_fault = 1;
    fp_result r = fp_store_install(s, FP_ARTIFACT, id, "abc", 3);
    CHECK(r.status == FP_IO && r.phase == FP_WRITE && r.name == FP_UNCHANGED);
    no_entries(dir);
    fail_sync_dir = 0;
    r = fp_store_install(s, FP_ARTIFACT, id, "abc", 3);
    CHECK(r.status == FP_IO && r.phase == FP_FILE_SYNC && r.name == FP_UNCHANGED);
    no_entries(dir);
    fail_sync_dir = 1;
    r = fp_store_install(s, FP_ARTIFACT, id, "abc", 3);
    CHECK(r.status == FP_IO && r.phase == FP_DIR_SYNC && r.name == FP_CREATED);
    expect_read(s, FP_ARTIFACT, id, "abc", 3);
    fail_sync_dir = 0;
    r = fp_store_install(s, FP_ARTIFACT, id, "abc", 3);
    CHECK(r.status == FP_IO && r.phase == FP_FILE_SYNC && r.name == FP_EXISTING);
    sync_count = 0;
    r = fp_store_install(s, FP_ARTIFACT, id, "abc", 3);
    CHECK(r.status == FP_OK && r.name == FP_EXISTING && sync_count == 2);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, "abX", 3).status == FP_CONFLICT);
    sync_count = 0;
    CHECK(fp_store_open(root, FP_READER, &reader).status == FP_OK);
    CHECK(fp_store_install(reader, FP_ARTIFACT, id, "abc", 3).status == FP_DENIED);
    expect_read(reader, FP_ARTIFACT, id, "abc", 3);
    CHECK(sync_count == 0);
    fp_store_close(reader);
    contention(s);

    CHECK(unlinkat(dir, leaf, 0) == 0);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, "", 0).status == FP_OK);
    expect_read(s, FP_ARTIFACT, id, "", 0);
    file = openat(dir, leaf, O_WRONLY);
    CHECK(file >= 0 && write(file, "a\0b", 3) == 3 && close(file) == 0);
    char *invalid; size_t invalid_size;
    CHECK(fp_store_read(s, FP_ARTIFACT, id, &invalid, &invalid_size).status == FP_INVALID);
    CHECK(!invalid && !invalid_size);
    CHECK(unlinkat(dir, leaf, 0) == 0);
    char *max = malloc(FP_ARTIFACT_MAX);
    CHECK(max != NULL);
    memset(max, 'x', FP_ARTIFACT_MAX);
    CHECK(fp_store_install(s, FP_ARTIFACT, id, max, FP_ARTIFACT_MAX).status == FP_OK);
    expect_read(s, FP_ARTIFACT, id, max, FP_ARTIFACT_MAX);
    free(max);
    file = openat(dir, leaf, O_WRONLY);
    CHECK(file >= 0 && ftruncate(file, FP_ARTIFACT_MAX+1) == 0 && close(file) == 0);
    expect_bad(s, FP_LIMIT);
    char manifest[FP_RUN_SIZE];
    memset(manifest, 'm', sizeof manifest);
    CHECK(fp_store_install(s, FP_RUN, id, manifest, sizeof manifest).status == FP_OK);
    expect_read(s, FP_RUN, id, manifest, sizeof manifest);
    close(dir);
    fp_store_close(s);
    puts("native_store_contract_ok=true");
    return 0;
}
