/* Read the graph declaration once, without following a final symlink or
   waiting on a FIFO. Never pass untrusted binary bytes through the text ABI. */
#define _POSIX_C_SOURCE 200809L
#include "on1x_runtime.h"

#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

enum { GRAPH_SOURCE_MAX = 4096 };

const char *finpred_graph_read(const char *path)
{
    if (!*path)
        return "input_open";
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (fd < 0)
        return "input_open";

    struct stat info;
    const char *reason = NULL;
    unsigned char bytes[GRAPH_SOURCE_MAX + 1];
    size_t size = 0;
    if (fstat(fd, &info) != 0)
        reason = "input_read";
    else if (!S_ISREG(info.st_mode))
        reason = "input_type";
    else if (info.st_size > GRAPH_SOURCE_MAX)
        reason = "size";

    /* Stop at limit+1 even if the regular file grows after fstat. */
    while (!reason && size < sizeof bytes) {
        ssize_t n = read(fd, bytes + size, sizeof bytes - size);
        if (n == 0)
            break;
        if (n < 0) {
            if (errno == EINTR)
                continue;
            reason = "input_read";
        } else {
            size += (size_t)n;
        }
    }
    if (close(fd) != 0 && !reason)
        reason = "input_read";
    if (reason)
        return reason;
    if (size == 0 || size > GRAPH_SOURCE_MAX)
        return "size";
    if (info.st_size != (off_t)size)
        return "input_read";

    /* Newline tags data; no diagnostic starts with it. On an invalid byte,
       return a tab tag and the safe prefix so the host can locate the byte. */
    char wire[GRAPH_SOURCE_MAX + 2];
    wire[0] = '\n';
    size_t i = 0;
    for (; i < size; ++i) {
        unsigned char c = bytes[i];
        if (c != '\n' && (c < 32 || c > 126)) {
            wire[0] = '\t';
            break;
        }
        wire[i + 1] = (char)c;
    }
    wire[i + 1] = '\0';
    return on1x_text_slice(wire, 0, (int64_t)i + 1);
}
