#define _GNU_SOURCE
#include "store.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/magic.h>
#include <linux/openat2.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <unistd.h>

struct fp_store { int dirs[2]; fp_access access; };

enum { FP_TRANSFER_RETRIES = 3 };

/* Linux read/write return EINTR only when no bytes were transferred. Bound
 * retries across the entire transfer, including the read's EOF probe. */
static int retry_transfer(ssize_t count, unsigned *retries)
{
    if (count >= 0 || errno != EINTR || *retries == 0) return 0;
    --*retries;
    return 1;
}

static ssize_t read_transfer(int fd, void *buf, size_t size, unsigned *retries)
{
    ssize_t count;
    do { count = read(fd, buf, size); } while (retry_transfer(count, retries));
    return count;
}

static fp_result result(fp_status status, fp_phase phase, fp_name_state name)
{
    return (fp_result){status, phase, name};
}

static fp_status sys_status(int e)
{
    switch (e) {
    case ENOENT: return FP_MISSING;
    case ELOOP: case EXDEV: case ENOTDIR: return FP_SCOPE;
    case EACCES: case EPERM: return FP_DENIED;
    case ENOSYS: case EOPNOTSUPP: return FP_UNSUPPORTED;
    default: return FP_IO;
    }
}

static int beneath(int dir, const char *name, int flags, unsigned mode)
{
    struct open_how how = { .flags = flags | O_CLOEXEC, .mode = mode,
        .resolve = RESOLVE_BENEATH | RESOLVE_NO_XDEV |
                   RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS };
    return (int)syscall(SYS_openat2, dir, name, &how, sizeof how);
}

static fp_status check_inode(int fd, int directory, int private_root)
{
    struct stat st;
    if (fstat(fd, &st) < 0) return FP_IO;
    if (directory ? !S_ISDIR(st.st_mode) : (!S_ISREG(st.st_mode) || st.st_nlink != 1))
        return FP_SCOPE;
    if (st.st_uid != geteuid() || (st.st_mode & (private_root ? 0077 : 0022)))
        return FP_SCOPE;
    return FP_OK;
}

void fp_store_close(fp_store *s)
{
    if (!s) return;
    for (int i = 0; i < 2; ++i)
        if (s->dirs[i] >= 0) close(s->dirs[i]);
    free(s);
}

fp_result fp_store_open(int root_fd, fp_access access, fp_store **out)
{
    if (!out) return result(FP_INVALID, FP_VALIDATE, FP_UNCHANGED);
    *out = NULL;
    if (root_fd < 0 || (access != FP_READER && access != FP_WRITER))
        return result(FP_INVALID, FP_VALIDATE, FP_UNCHANGED);
    int root = beneath(root_fd, ".", O_RDONLY | O_DIRECTORY, 0);
    if (root < 0) return result(sys_status(errno), FP_OPEN, FP_UNCHANGED);
    fp_status status = check_inode(root, 1, 1);
    fp_phase phase = FP_OPEN;
    struct statfs fs;
    fp_store *s = NULL;
    if (status != FP_OK) goto done;
    if (fstatfs(root, &fs) < 0) { status = FP_IO; goto done; }
    if (fs.f_type != EXT4_SUPER_MAGIC && fs.f_type != BTRFS_SUPER_MAGIC &&
        fs.f_type != XFS_SUPER_MAGIC) { status = FP_UNSUPPORTED; goto done; }
    if (statfs("/proc/self/fd", &fs) < 0 || fs.f_type != PROC_SUPER_MAGIC) {
        status = FP_UNSUPPORTED; goto done;
    }
    s = malloc(sizeof *s);
    if (!s) { status = FP_IO; goto done; }
    *s = (fp_store){ .dirs = {-1, -1}, .access = access };
    const char *names[] = {"artifacts", "runs"};
    for (int i = 0; i < 2; ++i) {
        if (access == FP_WRITER && mkdirat(root, names[i], 0700) < 0 && errno != EEXIST) {
            status = sys_status(errno); goto done;
        }
        s->dirs[i] = beneath(root, names[i], O_RDONLY | O_DIRECTORY, 0);
        if (s->dirs[i] < 0) { status = sys_status(errno); goto done; }
        status = check_inode(s->dirs[i], 1, 0);
        if (status != FP_OK) goto done;
    }
    if (access == FP_WRITER && fsync(root) < 0) { status = FP_IO; phase = FP_DIR_SYNC; }
done:
    if (close(root) < 0 && status == FP_OK) { status = FP_IO; phase = FP_CLOSE; }
    if (status == FP_OK) *out = s;
    else fp_store_close(s);
    return result(status, phase, FP_UNCHANGED);
}

static fp_status key(const fp_store *s, fp_kind kind, const char *id, char name[80])
{
    if (!s || (kind != FP_ARTIFACT && kind != FP_RUN) || !id || strnlen(id, 65) != 64)
        return FP_INVALID;
    for (size_t i = 0; i < 64; ++i) {
        char c = id[i];
        if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) return FP_INVALID;
    }
    snprintf(name, 80, "%s%s.txt", kind == FP_RUN ? "" : "blake3-", id);
    return FP_OK;
}

static fp_status length_ok(fp_kind kind, size_t n)
{
    if (n > FP_ARTIFACT_MAX) return FP_LIMIT;
    return kind == FP_RUN && n != FP_RUN_SIZE ? FP_INVALID : FP_OK;
}

/* Trusted host procfs, used only with a live fd that we own. Opening O_PATH
 * first lets us reject devices and FIFOs before opening anything for data.
 * Reopening this descriptor cannot resolve to a substituted directory entry. */
static void proc_name(int fd, char path[64])
{
    snprintf(path, 64, "/proc/self/fd/%d", fd);
}

/* Read or compare the existing pinned inode. A successful compare for install
 * also completes file and directory sync, including for legacy entries. */
static fp_result existing(int dir, const char *name, fp_kind kind, char **out,
                          size_t *size, const char *compare, size_t expected)
{
    int pin = beneath(dir, name, O_PATH | O_NOFOLLOW, 0);
    if (pin < 0) return result(sys_status(errno), FP_OPEN, FP_UNCHANGED);
    fp_result r = result(check_inode(pin, 0, 0), FP_OPEN, FP_EXISTING);
    int fd = -1;
    char *value = NULL;
    if (r.status != FP_OK) goto done;
    char path[64];
    proc_name(pin, path);
    fd = open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOATIME);
    if (fd < 0) { r.status = FP_IO; goto done; }
    struct stat st;
    r.phase = FP_READ;
    if (fstat(fd, &st) < 0) { r.status = FP_IO; goto done; }
    if (st.st_size < 0 || st.st_size > (off_t)FP_ARTIFACT_MAX) { r.status = FP_LIMIT; goto done; }
    size_t n = (size_t)st.st_size;
    if (compare && n != expected) { r.status = FP_CONFLICT; goto done; }
    r.status = length_ok(kind, n);
    if (r.status != FP_OK) goto done;
    if (!compare && !(value = malloc(n + 1))) { r.status = FP_IO; goto done; }
    char scratch[8192];
    size_t pos = 0;
    unsigned retries = FP_TRANSFER_RETRIES;
    while (pos < n) {
        size_t count = n-pos < sizeof scratch ? n-pos : sizeof scratch;
        char *dest = compare ? scratch : value + pos;
        ssize_t got = read_transfer(fd, dest, count, &retries);
        if (got <= 0) { r.status = FP_IO; goto done; }
        if (compare && memcmp(dest, compare + pos, (size_t)got)) { r.status = FP_CONFLICT; goto done; }
        if (!compare && memchr(dest, 0, (size_t)got)) { r.status = FP_INVALID; goto done; }
        pos += (size_t)got;
    }
    if (read_transfer(fd, scratch, 1, &retries) != 0) { r.status = FP_IO; goto done; }
    if (compare) {
        r.phase = FP_FILE_SYNC;
        if (fsync(fd) < 0) { r.status = FP_IO; goto done; }
        r.phase = FP_DIR_SYNC;
        if (fsync(dir) < 0) { r.status = FP_IO; goto done; }
    } else {
        value[n] = '\0';
        *size = n;
    }
done:
    if (fd >= 0 && close(fd) < 0 && r.status == FP_OK) { r.status = FP_IO; r.phase = FP_CLOSE; }
    close(pin);
    if (!compare && r.status == FP_OK) *out = value;
    else { free(value); if (size) *size = 0; }
    return r;
}

fp_result fp_store_read(const fp_store *s, fp_kind kind, const char *id, char **out, size_t *size)
{
    if (!out || !size) return result(FP_INVALID, FP_VALIDATE, FP_UNCHANGED);
    *out = NULL;
    *size = 0;
    char name[80];
    fp_status status = key(s, kind, id, name);
    if (status != FP_OK) return result(status, FP_VALIDATE, FP_UNCHANGED);
    return existing(s->dirs[kind], name, kind, out, size, NULL, 0);
}

fp_result fp_store_install(const fp_store *s, fp_kind kind, const char *id,
                           const char *data, size_t size)
{
    char name[80];
    fp_status status = key(s, kind, id, name);
    if (status != FP_OK || !data) return result(FP_INVALID, FP_VALIDATE, FP_UNCHANGED);
    if (s->access != FP_WRITER) return result(FP_DENIED, FP_VALIDATE, FP_UNCHANGED);
    status = length_ok(kind, size);
    if (status != FP_OK) return result(status, FP_VALIDATE, FP_UNCHANGED);
    if (memchr(data, 0, size)) return result(FP_INVALID, FP_VALIDATE, FP_UNCHANGED);
    int dir = s->dirs[kind];
    fp_result r = existing(dir, name, kind, NULL, NULL, data, size);
    if (r.status != FP_MISSING) return r;
    int fd = beneath(dir, ".", O_TMPFILE | O_RDWR, 0600);
    if (fd < 0) return result(sys_status(errno), FP_OPEN, FP_UNCHANGED);
    r = result(FP_OK, FP_WRITE, FP_UNCHANGED);
    /* O_TMPFILE applies the process umask. Set the owner-only mode on our
     * unnamed inode before syncing it, so success never publishes mode 0000. */
    if (fchmod(fd, 0600) < 0) { r.status = FP_IO; goto done; }
    unsigned retries = FP_TRANSFER_RETRIES;
    for (size_t pos = 0; pos < size;) {
        ssize_t count = write(fd, data + pos, size - pos);
        if (retry_transfer(count, &retries)) continue;
        if (count <= 0) { r.status = FP_IO; goto done; }
        pos += (size_t)count;
    }
    r.phase = FP_FILE_SYNC;
    if (fsync(fd) < 0) { r.status = FP_IO; goto done; }
    /* linkat creates only if absent. The unnamed stage dies on close if
     * another writer wins, or on any failure before this point. */
    char path[64];
    proc_name(fd, path);
    r.phase = FP_INSTALL;
    if (linkat(AT_FDCWD, path, dir, name, AT_SYMLINK_FOLLOW) < 0) {
        if (errno == EEXIST) r = existing(dir, name, kind, NULL, NULL, data, size);
        else {
            r.status = sys_status(errno);
            if (r.status == FP_IO) r.name = FP_UNCERTAIN;
        }
        goto done;
    }
    r.name = FP_CREATED;
    r.phase = FP_DIR_SYNC;
    if (fsync(dir) < 0) r.status = FP_IO;
done:
    if (close(fd) < 0 && r.status == FP_OK) { r.status = FP_IO; r.phase = FP_CLOSE; }
    return r;
}
