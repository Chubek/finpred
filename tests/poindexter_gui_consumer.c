/* Exercise the actual window host's app and rendering code without an X server.
 * --window additionally presents that same framebuffer to a private X server. */
#define main poindexter_gui_main
#include "../plugins/poindexter/gui/main.c"
#undef main

#include <assert.h>
#include <sys/stat.h>

static uint32_t pixel(const App *a, int x, int y)
{
    return a->surface.pixels[(size_t)y * a->surface.stride + x];
}

static void click(App *a, int x, int y)
{
    XWindow no_window = {0};
    XEvent e = {0};
    e.xbutton.type = ButtonPress;
    e.xbutton.x = x;
    e.xbutton.y = y;
    e.xbutton.button = Button1;
    assert(app_event(a, &no_window, &e));
    e.xbutton.type = ButtonRelease;
    assert(app_event(a, &no_window, &e));
}

static void enter(App *a, const char *text)
{
    key(a, XK_Return, 0, 0);
    assert(a->editing);
    key(a, XK_End, 0, 0);
    while (a->cursor) key(a, XK_BackSpace, 0, 0);
    for (; *text; ++text) key(a, NoSymbol, 0, *text);
    key(a, XK_Return, 0, 0);
    assert(!a->editing);
}

static int window_smoke(const char *worker, const char *book)
{
    App a = {0};
    XWindow w = {0};
    assert(app_open(&a, worker, book));
    assert(window_open(&w, a.status));
    assert(frame(&a, NULL, 0));
    present(&w, &a.surface);
    XSync(w.display, False);
    XImage *readback = XGetImage(w.display, w.window, 0, 0, WIDTH, HEIGHT, AllPlanes, ZPixmap);
    assert(readback);
    assert(XGetPixel(readback, 0, 0) == (background & 0xffffffu));
    assert(XGetPixel(readback, LEFT + 1, TOP + CELL_H + 1) == (selected & 0xffffffu));
    XDestroyImage(readback);
    window_close(&w);
    app_close(&a);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 4 && !strcmp(argv[1], "--window")) return window_smoke(argv[2], argv[3]);
    assert(argc == 7);
    const char *worker = argv[1], *book = argv[2], *bad = argv[3];
    const char *link = argv[4], *fifo = argv[5], *empty = argv[6];
    struct stat before, after;
    assert(!stat(book, &before));
    App a = {0};
    assert(app_open(&a, worker, book));
    assert(!strcmp(a.view.cells[0][2], "-400"));
    assert(!strcmp(a.view.cells[1][3], "a|\"b"));
    assert(frame(&a, NULL, 0));
    assert(pixel(&a, 0, 0) == background);
    assert(pixel(&a, LEFT + 1, TOP + CELL_H + 1) == selected);
    unsigned ink = 0;
    for (int y = TOP + CELL_H + 2; y < TOP + 2 * CELL_H - 2; ++y)
        for (int x = LEFT + 3; x < LEFT + CELL_W - 3; ++x)
            if (pixel(&a, x, y) == a.ui.theme.text) ++ink;
    assert(ink > 10); /* ImmGTK drew the On1x cell result with the real font. */

    mgx_event canceled[] = {{.type = MGX_EVENT_MOTION, .x = LEFT + CELL_W + 5, .y = TOP + CELL_H + 5},
                            {.type = MGX_EVENT_BUTTON, .down = 1},
                            {.type = MGX_EVENT_MOTION, .x = 0, .y = 0},
                            {.type = MGX_EVENT_BUTTON, .down = 0}};
    assert(frame(&a, canceled, sizeof canceled / sizeof *canceled));
    assert(a.row == 0 && a.col == 0);
    click(&a, LEFT + CELL_W + 5, TOP + CELL_H + 5);
    assert(a.col == 1 && !strcmp(a.view.source, "17100"));

    key(&a, XK_Return, 0, 0);
    assert(a.editing);
    key(&a, NoSymbol, 0, '0');
    key(&a, XK_s, ControlMask, 0);
    assert(strstr(a.status, "before saving"));
    key(&a, XK_Escape, 0, 0);
    assert(!a.editing && !a.dirty);
    assert(!strcmp(a.view.source, "17100"));
    enter(&a, "=1/0");
    assert(!strcmp(a.view.value, "#DIV/0!"));
    enter(&a, "=17000+50");
    assert(a.dirty && !strcmp(a.view.value, "17050") && !strcmp(a.view.cells[0][2], "-450"));
    assert(!stat(book, &after));
    assert(before.st_ino == after.st_ino && before.st_mtim.tv_sec == after.st_mtim.tv_sec &&
           before.st_mtim.tv_nsec == after.st_mtim.tv_nsec);

    PxFrame unused;
    char error[PX_ERROR];
    assert(!px_edit(&a.session, 0, 1, "bad\ninput", &unused, error));
    assert(strstr(error, "printable ASCII"));
    assert(!px_frame(&a.session, 64, 0, &unused, error));
    char long_text[PX_SOURCE + 2];
    memset(long_text, 'x', sizeof long_text - 1);
    long_text[sizeof long_text - 1] = '\0';
    assert(!px_edit(&a.session, 0, 1, long_text, &unused, error));

    key(&a, XK_End, 0, 0);
    assert(a.row == 63 && a.col == 15 && !strcmp(a.view.cells[3][3], "99"));
    key(&a, XK_Home, 0, 0);
    assert(a.row == 0 && a.col == 0 && !strcmp(a.view.cells[0][2], "-450"));
    assert(frame(&a, NULL, 0));
    click(&a, save_button.x + 2, save_button.y + 2);
    assert(!a.dirty && !strcmp(a.status, "Workbook saved."));
    app_close(&a);

    PxSession s;
    assert(!px_open(&s, worker, bad, error) && strstr(error, "invalid workbook header"));
    assert(!px_open(&s, worker, link, error) && strstr(error, "regular"));
    assert(!px_open(&s, worker, fifo, error) && strstr(error, "regular"));
    assert(!px_open(&s, "/nonexistent-poindexter-worker", book, error) && strstr(error, "worker failed"));
    assert(px_open(&s, worker, empty, error));
    assert(px_frame(&s, 0, 0, &unused, error) && unused.value[0] == '\0');
    assert(access(empty, F_OK) == -1);
    assert(!symlink(book, empty));
    assert(!px_save(&s, error) && strstr(error, "regular"));
    assert(!unlink(empty));
    assert(px_save(&s, error));
    px_close(&s);
    assert(!stat(empty, &after) && S_ISREG(after.st_mode));
    return 0;
}
