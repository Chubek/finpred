#include "viewport.h"

#include "mulib-vterm.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(expr)                                                        \
    do {                                                                   \
        if (!(expr)) {                                                     \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expr);      \
            exit(EXIT_FAILURE);                                            \
        }                                                                  \
    } while (0)

static void render_into(px_viewport *view, mulib_vterm_t *screen)
{
    px_viewport_bytes bytes;
    CHECK(px_viewport_render(view, &bytes) == PX_VIEWPORT_OK);
    CHECK(bytes.length > 0 && bytes.data != NULL);
    CHECK(mulib_vterm_feed(screen, bytes.data, bytes.length));
}

static void check_no_change(px_viewport *view)
{
    px_viewport_bytes bytes = {"sentinel", 8};
    CHECK(px_viewport_render(view, &bytes) == PX_VIEWPORT_OK);
    CHECK(bytes.data == NULL && bytes.length == 0);
}

static void check_row(const mulib_vterm_t *screen, size_t row, const char *expected)
{
    CHECK(strlen(expected) == screen->grid.width);
    for (size_t x = 0; expected[x]; ++x) {
        const mulib_term_cell_t *cell = mulib_vterm_cell(screen, x, row);
        CHECK(cell && cell->codepoint == (unsigned char)expected[x]);
    }
}

static void test_frame(void)
{
    px_viewport *view = NULL;
    px_viewport_bytes bytes;
    mulib_vterm_t screen;
    const char text[] = "ABCDEextra\n12\nXYZ?!tail\nhidden";
    /* Fixture for the pinned ANSI fallback including the bottom-right cell. */
    const char ansi[] = "\033[0m\033[39;49m\033[1;1HABCDE\033[2;1H12   "
                        "\033[3;1HXYZ?!\033[0m\033[39;49m\033[?25l";
    const char same_visible[] = "ABCDE!\n12\nXYZ?!\nnot on screen";
    const char shorter[] = "AB\n\nuvw";

    CHECK(px_viewport_create(5, 3, &view) == PX_VIEWPORT_OK);
    CHECK(mulib_vterm_init(&screen, 5, 3));
    CHECK(px_viewport_set_text(view, text, sizeof(text) - 1) == PX_VIEWPORT_OK);
    CHECK(px_viewport_render(view, &bytes) == PX_VIEWPORT_OK);
    CHECK(bytes.length == sizeof(ansi) - 1 && bytes.data);
    CHECK(memcmp(bytes.data, ansi, bytes.length) == 0);
    CHECK(mulib_vterm_feed(&screen, bytes.data, bytes.length));
    check_row(&screen, 0, "ABCDE");
    check_row(&screen, 1, "12   ");
    check_row(&screen, 2, "XYZ?!");
    check_no_change(view);

    CHECK(px_viewport_set_text(view, same_visible, sizeof(same_visible) - 1) == PX_VIEWPORT_OK);
    check_no_change(view);
    CHECK(px_viewport_set_text(view, shorter, sizeof(shorter) - 1) == PX_VIEWPORT_OK);
    render_into(view, &screen);
    check_row(&screen, 0, "AB   ");
    check_row(&screen, 1, "     ");
    check_row(&screen, 2, "uvw  ");
    CHECK(px_viewport_set_text(view, NULL, 0) == PX_VIEWPORT_OK);
    render_into(view, &screen);
    for (size_t row = 0; row < 3; ++row)
        check_row(&screen, row, "     ");
    check_no_change(view);
    mulib_vterm_free(&screen);
    px_viewport_destroy(view);
}

static void test_rejection(void)
{
    px_viewport *view = NULL;
    px_viewport_bytes first, untouched = {"sentinel", 8};
    const char *sentinel = untouched.data;
    char saved[128];
    mulib_vterm_t screen;

    CHECK(px_viewport_create(4, 2, &view) == PX_VIEWPORT_OK);
    CHECK(mulib_vterm_init(&screen, 4, 2));
    CHECK(px_viewport_set_text(view, "KEEP\nTHIS", 9) == PX_VIEWPORT_OK);
    CHECK(px_viewport_render(view, &first) == PX_VIEWPORT_OK);
    CHECK(first.data && first.length && first.length <= sizeof(saved));
    memcpy(saved, first.data, first.length);
    CHECK(mulib_vterm_feed(&screen, first.data, first.length));
    CHECK(px_viewport_set_text(view, "NEXT\nHERE", 9) == PX_VIEWPORT_OK);

    CHECK(px_viewport_set_text(NULL, "X", 1) == PX_VIEWPORT_ARGUMENT);
    CHECK(px_viewport_set_text(view, NULL, 1) == PX_VIEWPORT_ARGUMENT);
    CHECK(px_viewport_set_text(view, "X", SIZE_MAX) == PX_VIEWPORT_LIMIT);
    CHECK(px_viewport_set_text(view, "Z\0Y", 3) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "Z\tY", 3) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "Z\rY", 3) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "Z\x7f", 2) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "Z\xc2", 2) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "ZZZZ\xc3\xa9", 6) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_set_text(view, "ZZZZ\nZZZZ\n\x1b[2J", 14) == PX_VIEWPORT_TEXT);
    CHECK(px_viewport_render(NULL, &untouched) == PX_VIEWPORT_ARGUMENT);
    CHECK(untouched.data == sentinel && untouched.length == 8);
    CHECK(px_viewport_render(view, NULL) == PX_VIEWPORT_ARGUMENT);
    CHECK(memcmp(first.data, saved, first.length) == 0);

    render_into(view, &screen);
    check_row(&screen, 0, "NEXT");
    check_row(&screen, 1, "HERE");
    CHECK(px_viewport_set_text(view, "other\0", 6) == PX_VIEWPORT_TEXT);
    check_no_change(view);
    mulib_vterm_free(&screen);
    px_viewport_destroy(view);
}

static void test_bounds(void)
{
    static char text[PX_VIEWPORT_MAX_TEXT_BYTES];
    px_viewport *view = NULL;
    px_viewport *slot;
    mulib_vterm_t screen;
    const size_t width = PX_VIEWPORT_MAX_WIDTH, height = PX_VIEWPORT_MAX_HEIGHT;
    const mulib_term_cell_t *cell;

    CHECK(px_viewport_create(width, height, &view) == PX_VIEWPORT_OK);
    slot = view;
    CHECK(px_viewport_create(1, 1, NULL) == PX_VIEWPORT_ARGUMENT);
    CHECK(px_viewport_create(0, 1, &slot) == PX_VIEWPORT_LIMIT && slot == view);
    CHECK(px_viewport_create(1, 0, &slot) == PX_VIEWPORT_LIMIT && slot == view);
    CHECK(px_viewport_create(width + 1, 1, &slot) == PX_VIEWPORT_LIMIT && slot == view);
    CHECK(px_viewport_create(1, height + 1, &slot) == PX_VIEWPORT_LIMIT && slot == view);
    CHECK(px_viewport_create(SIZE_MAX, SIZE_MAX, &slot) == PX_VIEWPORT_LIMIT && slot == view);
    CHECK(px_viewport_set_text(view, text, sizeof(text) + 1) == PX_VIEWPORT_LIMIT);

    memset(text, 'X', sizeof(text));
    for (size_t row = 0; row < height; ++row)
        text[row * (width + 1) + width] = '\n';
    CHECK(px_viewport_set_text(view, text, sizeof(text)) == PX_VIEWPORT_OK);
    CHECK(mulib_vterm_init(&screen, width, height));
    render_into(view, &screen);
    cell = mulib_vterm_cell(&screen, width - 1, height - 1);
    CHECK(cell && cell->codepoint == 'X');
    check_no_change(view);
    mulib_vterm_free(&screen);
    px_viewport_destroy(view);
    px_viewport_destroy(NULL);
}

int main(int argc, char **argv)
{
    CHECK(argc == 2);
    if (strcmp(argv[1], "frame") == 0)
        test_frame();
    else if (strcmp(argv[1], "rejection") == 0)
        test_rejection();
    else if (strcmp(argv[1], "bounds") == 0)
        test_bounds();
    else
        CHECK(0);
    return EXIT_SUCCESS;
}
