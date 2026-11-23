#ifndef PX_VIEWPORT_H
#define PX_VIEWPORT_H

#include <stddef.h>

#define PX_VIEWPORT_MAX_WIDTH 240u
#define PX_VIEWPORT_MAX_HEIGHT 80u
#define PX_VIEWPORT_MAX_TEXT_BYTES 32768u

typedef struct px_viewport px_viewport;

typedef enum px_viewport_status {
    PX_VIEWPORT_OK = 0,
    PX_VIEWPORT_ARGUMENT,
    PX_VIEWPORT_LIMIT,
    PX_VIEWPORT_TEXT,
    PX_VIEWPORT_BACKEND
} px_viewport_status;

typedef struct px_viewport_bytes {
    const char *data;
    size_t length;
} px_viewport_bytes;

/* On success, *out owns a new fixed-size blank viewport. On error, *out
 * is unchanged. The caller must not lose ownership of another viewport. */
px_viewport_status px_viewport_create(size_t width, size_t height, px_viewport **out);

/* Replace the entire pending frame. Accepts printable ASCII and LF only;
 * NULL is allowed at length zero. Lines clip on the right, without wrap.
 * Rejected input leaves the pending frame and any captured bytes unchanged. */
px_viewport_status px_viewport_set_text(px_viewport *view, const char *text, size_t length);

/* Capture the ANSI diff in memory. No change yields {NULL, 0}. A nonempty
 * result is borrowed until the next successful render or destroy on view.
 * Failure preserves *out, the previous capture, and the frame for retry. */
px_viewport_status px_viewport_render(px_viewport *view, px_viewport_bytes *out);

/* Release the owning pointer exactly once; NULL is a no-op. */
void px_viewport_destroy(px_viewport *view);

#endif
