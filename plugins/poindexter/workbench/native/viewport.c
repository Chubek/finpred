#define MULIB_IMPL_GRID
#define MULIB_IMPL_UTF8
#define MULIB_IMPL_STRBUF
#define MULIB_IMPL_TERMINFO
#define MULIB_IMPL_VTERM
#define MULIB_IMPL_TUI
#include "mulib-tui.h"

#include "viewport.h"

#include <limits.h>
#include <stdlib.h>

_Static_assert(CHAR_BIT == 8 && ' ' == 0x20 && '~' == 0x7e && '\n' == 0x0a,
               "viewport requires an ASCII-compatible octet C target");

struct px_viewport {
    mulib_tui_t tui;
    mulib_strbuf_t capture;
    size_t width;
    size_t height;
};

px_viewport_status px_viewport_create(size_t width, size_t height, px_viewport **out)
{
    px_viewport *view;

    if (!out)
        return PX_VIEWPORT_ARGUMENT;
    if (!width || width > PX_VIEWPORT_MAX_WIDTH || !height || height > PX_VIEWPORT_MAX_HEIGHT)
        return PX_VIEWPORT_LIMIT;
    view = malloc(sizeof(*view));
    if (!view)
        return PX_VIEWPORT_BACKEND;
    if (!mulib_tui_init(&view->tui, width, height)) {
        mulib_tui_free(&view->tui);
        free(view);
        return PX_VIEWPORT_BACKEND;
    }
    mulib_strbuf_init(&view->capture);
    view->width = width;
    view->height = height;
    *out = view;
    return PX_VIEWPORT_OK;
}

px_viewport_status px_viewport_set_text(px_viewport *view, const char *text, size_t length)
{
    size_t start = 0;
    mulib_term_style_t style = mulib_term_style_default();

    if (!view || (!text && length))
        return PX_VIEWPORT_ARGUMENT;
    if (length > PX_VIEWPORT_MAX_TEXT_BYTES)
        return PX_VIEWPORT_LIMIT;
    for (size_t i = 0; i < length; ++i) {
        unsigned char c = (unsigned char)text[i];
        if (c != '\n' && (c < 0x20 || c > 0x7e))
            return PX_VIEWPORT_TEXT;
    }

    /* There are no fallible draw operations with a live framebuffer,
     * a valid default style, and already validated printable ASCII. */
    (void)mulib_tui_clear(&view->tui, style);
    for (size_t row = 0; row < view->height && start < length; ++row) {
        size_t end = start;
        while (end < length && text[end] != '\n')
            ++end;
        if (end > start) {
            mulib_tui_rect_t line = {0, row, view->width, 1};
            (void)mulib_tui_text(&view->tui, line, text + start, end - start, style);
        }
        start = end < length ? end + 1 : end;
    }
    return PX_VIEWPORT_OK;
}

px_viewport_status px_viewport_render(px_viewport *view, px_viewport_bytes *out)
{
    mulib_strbuf_t next;

    if (!view || !out)
        return PX_VIEWPORT_ARGUMENT;
    mulib_strbuf_init(&next);
    if (!mulib_tui_render(&view->tui, NULL, &next)) {
        mulib_strbuf_free(&next);
        return PX_VIEWPORT_BACKEND;
    }
    mulib_strbuf_free(&view->capture);
    if (next.length == 0)
        mulib_strbuf_free(&next);
    view->capture = next;
    *out = (px_viewport_bytes){view->capture.data, view->capture.length};
    return PX_VIEWPORT_OK;
}

void px_viewport_destroy(px_viewport *view)
{
    if (view) {
        mulib_strbuf_free(&view->capture);
        mulib_tui_free(&view->tui);
        free(view);
    }
}
