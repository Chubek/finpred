#define _POSIX_C_SOURCE 200809L
#include "worksheet.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

enum { BOOK_LIMIT = 210000, FRAME_LIMIT = 2048 };
static const char empty_book[] = "poindexter-workbook@1\n";

static bool fail(char error[PX_ERROR], const char *message)
{
    snprintf(error, PX_ERROR, "%s", message);
    return false;
}

static char *join(const char *left, const char *suffix)
{
    size_t n = strlen(left), m = strlen(suffix);
    char *p = malloc(n + m + 1);
    if (p) {
        memcpy(p, left, n);
        memcpy(p + n, suffix, m + 1);
    }
    return p;
}

static bool write_all(int fd, const char *p, size_t size)
{
    while (size) {
        ssize_t n = write(fd, p, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        p += n;
        size -= (size_t)n;
    }
    return true;
}

static bool copy_book(int in, int out)
{
    struct stat st;
    if (fstat(in, &st) || !S_ISREG(st.st_mode) || st.st_size > BOOK_LIMIT)
        return false;
    size_t total = 0;
    char buf[4096];
    for (;;) {
        ssize_t n = read(in, buf, sizeof buf);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 || total + (size_t)n > BOOK_LIMIT) return false;
        if (!n) return total == (size_t)st.st_size;
        if (!write_all(out, buf, (size_t)n)) return false;
        total += (size_t)n;
    }
}

static int open_local(const char *name)
{
    return open(name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
}

static int above_stdio(int fd)
{
    if (fd < 0 || fd > STDERR_FILENO) return fd;
    int moved = fcntl(fd, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
    close(fd);
    return moved;
}

static bool worker_run(PxSession *s, const char *op, const char *input,
                       const char *output, int row, int col, const char *text,
                       char error[PX_ERROR])
{
    char operation[32], cell[24], value[PX_SOURCE + sizeof "PX_VALUE="];
    char rows[16], cols[16];
    if (strlen(text) > PX_SOURCE) return fail(error, "A cell holds at most 192 bytes.");
    char *book = join("PX_BOOK=", input);
    char *log = join(s->dir, "/error");
    int out = book && log ?
        above_stdio(open(output, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600)) : -1;
    int diag = out >= 0 ?
        above_stdio(open(log, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0600)) : -1;
    int nil = diag >= 0 ? above_stdio(open("/dev/null", O_RDONLY | O_CLOEXEC)) : -1;
    bool ok = false;
    if (nil < 0) {
        fail(error, "Could not prepare worksheet worker.");
        goto done;
    }
    snprintf(operation, sizeof operation, "PX_OP=%s", op);
    snprintf(cell, sizeof cell, "PX_CELL=%c%d", 'A' + col, row + 1);
    snprintf(rows, sizeof rows, "PX_ROWS=%d", PX_PAGE_ROWS);
    snprintf(cols, sizeof cols, "PX_COLS=%d", PX_PAGE_COLS);
    snprintf(value, sizeof value, "PX_VALUE=%s", text);
    char *const args[] = {(char *)s->worker, NULL};
    char *const env[] = {operation, cell, book, rows, cols, value, NULL};
    pid_t pid = fork();
    if (pid == 0) {
        if (dup2(nil, STDIN_FILENO) < 0 || dup2(out, STDOUT_FILENO) < 0 ||
            dup2(diag, STDERR_FILENO) < 0) _exit(126);
        execve(s->worker, args, env);
        _exit(127);
    }
    if (pid < 0) {
        fail(error, "Could not start worksheet worker.");
        goto done;
    }
    int status;
    pid_t waited;
    do { waited = waitpid(pid, &status, 0); } while (waited < 0 && errno == EINTR);
    ok = waited == pid && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    if (!ok) {
        ssize_t n = lseek(diag, 0, SEEK_SET) < 0 ? -1 : read(diag, error, PX_ERROR - 1);
        size_t i = 0;
        while (n > 0 && i < (size_t)n &&
               (unsigned char)error[i] >= 32 && (unsigned char)error[i] <= 126) ++i;
        if (i) error[i] = '\0';
        else fail(error, "Worksheet worker failed (check POINDEXTER_EXE).");
    }
done:
    if (nil >= 0) close(nil);
    if (diag >= 0) close(diag);
    if (out >= 0) close(out);
    free(log);
    free(book);
    return ok;
}

void px_close(PxSession *s)
{
    if (!s->dir) return;
    const char *names[] = {"/input", "/current", "/candidate", "/frame", "/error"};
    for (size_t i = 0; i < sizeof names / sizeof *names; ++i) {
        char *p = join(s->dir, names[i]);
        if (p) {
            unlink(p);
            free(p);
        }
    }
    rmdir(s->dir);
    free(s->dir);
    s->dir = NULL;
}

bool px_open(PxSession *s, const char *worker, const char *book, char error[PX_ERROR])
{
    *s = (PxSession){.worker = worker, .book = book};
    const char *tmp = getenv("TMPDIR");
    s->dir = join(tmp && *tmp ? tmp : "/tmp", "/poindexter-gui.XXXXXXXX");
    if (!s->dir || !mkdtemp(s->dir)) {
        free(s->dir);
        s->dir = NULL;
        return fail(error, "Could not make private worksheet directory.");
    }
    char *input = join(s->dir, "/input"), *current = join(s->dir, "/current");
    int out = input && current ? open(input, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600) : -1;
    int in = out >= 0 ? open_local(book) : -1;
    bool copied = out >= 0 && (in >= 0 ? copy_book(in, out) :
        errno == ENOENT && write_all(out, empty_book, sizeof empty_book - 1));
    if (out >= 0 && close(out)) copied = false;
    if (in >= 0) close(in);
    bool ok = copied ? worker_run(s, "check", input, current, 0, 0, "", error) :
        fail(error, "Expected a regular local workbook of at most 210000 bytes.");
    free(input);
    free(current);
    if (!ok) px_close(s);
    return ok;
}

/* Consume the worker's bounded `frame` presentation, not the workbook format.
   Fields may themselves contain |, spaces or quote characters. */
static bool frame_read(const char *path, int row, int col, PxFrame *frame)
{
    FILE *f = fopen(path, "rb");
    if (!f) return false;
    char buf[FRAME_LIMIT];
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    bool ok = feof(f) && !ferror(f);
    fclose(f);
    if (!ok || memchr(buf, '\0', n)) return false;
    for (size_t i = 0; i < n; ++i)
        if (buf[i] != '\n' && ((unsigned char)buf[i] < 32 || (unsigned char)buf[i] > 126))
            return false;
    buf[n] = '\0';
    int r0 = row / PX_PAGE_ROWS * PX_PAGE_ROWS;
    int nr = PX_ROWS - r0 < PX_PAGE_ROWS ? PX_ROWS - r0 : PX_PAGE_ROWS;
    char *p = buf, *end;
    const size_t width = 5 + PX_PAGE_COLS * (2 + PX_FIELD);
    *frame = (PxFrame){0};
    for (int r = -1; r < nr; ++r) {
        end = strchr(p, '\n');
        if (!end || (size_t)(end - p) != width) return false;
        for (int c = 0; c < PX_PAGE_COLS; ++c) {
            const char *field = p + 5 + c * (2 + PX_FIELD);
            if (field[0] != '|' || (field[1] != ' ' && field[1] != '>')) return false;
            if (r >= 0) {
                size_t len = PX_FIELD;
                while (len && field[1 + len] == ' ') --len;
                memcpy(frame->cells[r][c], field + 2, len);
            }
        }
        p = end + 1;
    }
    char prefix[20];
    snprintf(prefix, sizeof prefix, "\n%c%d  fx: ", 'A' + col, row + 1);
    size_t k = strlen(prefix);
    if (strncmp(p, prefix, k)) return false;
    p += k;
    end = strchr(p, '\n');
    if (!end || end - p > PX_SOURCE) return false;
    memcpy(frame->source, p, (size_t)(end - p));
    p = end + 1;
    if (strncmp(p, "Value: ", 7)) return false;
    p += 7;
    end = strchr(p, '\n');
    if (!end || end - p > PX_SOURCE || end[1]) return false;
    memcpy(frame->value, p, (size_t)(end - p));
    return true;
}

static bool load_frame(PxSession *s, const char *input, int row, int col, PxFrame *f,
                       char error[PX_ERROR])
{
    char *output = join(s->dir, "/frame");
    bool ok = output ? worker_run(s, "frame", input, output, row, col, "", error) :
        fail(error, "Could not prepare worksheet view.");
    if (ok && !frame_read(output, row, col, f))
        ok = fail(error, "Worksheet worker returned an invalid grid frame.");
    free(output);
    return ok;
}

static bool valid_cell(int row, int col, char error[PX_ERROR])
{
    return (row >= 0 && row < PX_ROWS && col >= 0 && col < PX_COLS) ||
        fail(error, "Cell is outside A1:P64.");
}

bool px_frame(PxSession *s, int row, int col, PxFrame *f, char error[PX_ERROR])
{
    if (!valid_cell(row, col, error)) return false;
    char *path = join(s->dir, "/current");
    bool ok = path ? load_frame(s, path, row, col, f, error) :
        fail(error, "Could not prepare worksheet view.");
    free(path);
    return ok;
}

bool px_edit(PxSession *s, int row, int col, const char *text, PxFrame *f,
             char error[PX_ERROR])
{
    if (!valid_cell(row, col, error)) return false;
    char *current = join(s->dir, "/current"), *next = join(s->dir, "/candidate");
    bool ok = current && next ? worker_run(s, "edit", current, next, row, col, text, error) :
        fail(error, "Could not prepare worksheet edit.");
    if (ok) ok = load_frame(s, next, row, col, f, error);
    if (ok && rename(next, current)) ok = fail(error, "Could not accept worksheet edit.");
    free(current);
    free(next);
    return ok;
}

bool px_save(PxSession *s, char error[PX_ERROR])
{
    struct stat st;
    if (lstat(s->book, &st) ? errno != ENOENT : !S_ISREG(st.st_mode))
        return fail(error, "Save requires a regular local workbook path.");
    char *current = join(s->dir, "/current"), *stage = join(s->book, ".tmp.XXXXXXXX");
    int in = current && stage ? open_local(current) : -1;
    int out = in >= 0 ? mkstemp(stage) : -1;
    bool ok = false;
    if (out >= 0) {
        ok = copy_book(in, out);
        if (close(out)) ok = false;
        if (ok) ok = rename(stage, s->book) == 0;
        if (!ok) unlink(stage);
    }
    if (in >= 0) close(in);
    free(current);
    free(stage);
    return ok || fail(error, "Could not save the selected workbook.");
}
