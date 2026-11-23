#define _POSIX_C_SOURCE 200809L
#include "worksheet.h"
#include "mulib-immgtk-native.h"

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

enum {
    WIDTH = 720, HEIGHT = 480, LEFT = 44, TOP = 112,
    CELL_W = 166, CELL_H = 24, EDIT_VISIBLE = 45
};
static const uint32_t background = 0xff141b24, selected = 0xff285c86;
static const mgx_rect save_button = {542, 8, 78, 28};
static const mgx_rect quit_button = {628, 8, 80, 28};

typedef struct {
    PxSession session;
    PxFrame view;
    int row, col;
    bool editing, dirty, quit_pending, done;
    char text[PX_SOURCE + 1], status[PX_ERROR];
    size_t cursor;
    mulib_immgtk_native_t ui;
    mgx_surface surface;
    mulib_glx_font_t font;
} App;

static void message(App *app, const char *s)
{
    snprintf(app->status, sizeof app->status, "%s", s);
}

static bool app_open(App *app, const char *worker, const char *book)
{
    mulib_immgtk_native_init(&app->ui);
    app->ui.font = &app->font;
    app->ui.theme.font_size = 16;
    if (!mulib_immgtk_native_limits(&app->ui, 64, 64, 16, 128) ||
        !mulib_glx_font_builtin(&app->font) || !mgx_surface_init(&app->surface, WIDTH, HEIGHT)) {
        message(app, "Could not initialize ImmGTK.");
        return false;
    }
    if (!px_open(&app->session, worker, book, app->status) ||
        !px_frame(&app->session, 0, 0, &app->view, app->status)) return false;
    message(app, "Local working copy. Changes are not saved automatically.");
    return true;
}

static void app_close(App *app)
{
    px_close(&app->session);
    mulib_immgtk_native_free(&app->ui);
    mulib_glx_font_free(&app->font);
    mgx_surface_free(&app->surface);
}

static void select_cell(App *app, int row, int col)
{
    if (row < 0 || row >= PX_ROWS || col < 0 || col >= PX_COLS ||
        (row == app->row && col == app->col)) return;
    PxFrame next;
    if (!px_frame(&app->session, row, col, &next, app->status)) return;
    if (row / PX_PAGE_ROWS != app->row / PX_PAGE_ROWS ||
        col / PX_PAGE_COLS != app->col / PX_PAGE_COLS)
        mulib_immgtk_native_invalidate(&app->ui);
    app->view = next;
    app->row = row;
    app->col = col;
    message(app, "Enter to edit the selected cell.");
}

static void edit(App *app)
{
    if (!app->editing) {
        strcpy(app->text, app->view.source);
        app->cursor = strlen(app->text);
        app->editing = true;
        message(app, "Editing source. Enter applies; Esc cancels.");
        return;
    }
    PxFrame next;
    if (!px_edit(&app->session, app->row, app->col, app->text, &next, app->status)) return;
    app->view = next;
    app->editing = false;
    app->dirty = true;
    message(app, "Updated and recalculated. Save to keep changes.");
}

static void save(App *app)
{
    if (app->editing) {
        message(app, "Apply or cancel the cell edit before saving.");
        return;
    }
    if (px_save(&app->session, app->status)) {
        app->dirty = false;
        message(app, "Workbook saved.");
    }
}

static void quit(App *app)
{
    if ((!app->dirty && !app->editing) || app->quit_pending) app->done = true;
    else {
        app->quit_pending = true;
        message(app, "Unsaved changes. Quit again to discard.");
    }
}

static void key(App *app, KeySym sym, unsigned int mods, char ch)
{
    if ((mods & ControlMask) && (sym == XK_q || sym == XK_Q)) {
        quit(app);
        return;
    }
    app->quit_pending = false;
    if ((mods & ControlMask) && (sym == XK_s || sym == XK_S)) {
        save(app);
        return;
    }
    if (mods & (ControlMask | Mod1Mask)) return;
    if (sym == XK_Return || sym == XK_KP_Enter || sym == XK_F2) {
        edit(app);
        return;
    }
    if (!app->editing) {
        if (sym == XK_Left) select_cell(app, app->row, app->col - 1);
        if (sym == XK_Right) select_cell(app, app->row, app->col + 1);
        if (sym == XK_Up) select_cell(app, app->row - 1, app->col);
        if (sym == XK_Down) select_cell(app, app->row + 1, app->col);
        if (sym == XK_Page_Up) select_cell(app, mgx_max(0, app->row - PX_PAGE_ROWS), app->col);
        if (sym == XK_Page_Down) select_cell(app, mgx_min(PX_ROWS - 1, app->row + PX_PAGE_ROWS), app->col);
        if (sym == XK_Home) select_cell(app, 0, 0);
        if (sym == XK_End) select_cell(app, PX_ROWS - 1, PX_COLS - 1);
        return;
    }
    size_t n = strlen(app->text), p = app->cursor;
    if (sym == XK_Escape) {
        app->editing = false;
        message(app, "Cell edit canceled.");
    } else if (sym == XK_Home) app->cursor = 0;
    else if (sym == XK_End) app->cursor = n;
    else if (sym == XK_Left && p) --app->cursor;
    else if (sym == XK_Right && p < n) ++app->cursor;
    else if (sym == XK_BackSpace && p) {
        memmove(app->text + p - 1, app->text + p, n - p + 1);
        --app->cursor;
    } else if (sym == XK_Delete && p < n) {
        memmove(app->text + p, app->text + p + 1, n - p);
    } else if (ch >= 32 && ch <= 126) {
        if (n >= PX_SOURCE) message(app, "A cell holds at most 192 bytes.");
        else {
            memmove(app->text + p + 1, app->text + p, n - p + 1);
            app->text[p] = ch;
            ++app->cursor;
        }
    }
}

/* Process native ImmGTK hit testing, then redraw if a widget changes the view.
   The same path draws the GUI smoke fixture without an X11 connection. */
static bool frame(App *app, const mgx_event *events, size_t count)
{
    mulib_immgtk_native_t *g = &app->ui;
    if (!mulib_immgtk_native_begin_events(g, &app->surface, events, count)) return false;
    mig_rect(g, (mgx_rect){0, 0, WIDTH, HEIGHT}, background);
    mig_label(g, (mgx_rect){12, 8, 520, 28},
              app->dirty ? "Poindexter  /  Worksheet *" : "Poindexter  /  Worksheet");
    bool saved = mig_button(g, "save", "Save", save_button, !app->editing);
    bool closed = mig_button(g, "quit", "Quit", quit_button, 1);

    char bar[PX_SOURCE + 24];
    size_t start = app->editing && app->cursor >= EDIT_VISIBLE ?
        app->cursor - EDIT_VISIBLE + 1 : 0;
    snprintf(bar, sizeof bar, "%c%d  fx: %s", 'A' + app->col, app->row + 1,
             app->editing ? app->text + start : app->view.source);
    mgx_rect formula = {12, 44, WIDTH - 24, 30};
    mig_rect(g, formula, app->editing ? selected : g->theme.panel);
    mig_label(g, formula, bar);
    if (app->editing) {
        /* Built-in ASCII font at size 16 advances by 12 pixels. */
        int prefix = app->row < 9 ? 8 : 9;
        int x = formula.x + g->theme.padding + 12 * (prefix + (int)(app->cursor - start));
        mig_rect(g, (mgx_rect){x, 68, 10, 2}, g->theme.text);
    }
    snprintf(bar, sizeof bar, "Value: %s", app->view.value);
    mig_label(g, (mgx_rect){12, 76, WIDTH - 24, 28}, bar);

    int r0 = app->row / PX_PAGE_ROWS * PX_PAGE_ROWS;
    int c0 = app->col / PX_PAGE_COLS * PX_PAGE_COLS;
    int row = -1, col = -1;
    for (int c = 0; c < PX_PAGE_COLS; ++c) {
        char label[] = {(char)('A' + c0 + c), '\0'};
        mig_label(g, (mgx_rect){LEFT + c * CELL_W, TOP, CELL_W, CELL_H}, label);
    }
    for (int r = 0; r < PX_PAGE_ROWS && r0 + r < PX_ROWS; ++r) {
        char label[16];
        int y = TOP + (r + 1) * CELL_H;
        snprintf(label, sizeof label, "%d", r0 + r + 1);
        mig_label(g, (mgx_rect){12, y, LEFT - 12, CELL_H}, label);
        for (int c = 0; c < PX_PAGE_COLS; ++c) {
            uint64_t id = 100 + (uint64_t)((r0 + r) * PX_COLS + c0 + c);
            mgx_rect rect = {LEFT + c * CELL_W, y, CELL_W - 1, CELL_H - 1};
            if (mig_interact(g, id, rect, !app->editing)) {
                row = r0 + r;
                col = c0 + c;
            }
            bool sel = app->row == r0 + r && app->col == c0 + c;
            mig_rect(g, rect, sel ? selected : g->hot == id ? g->theme.hover : g->theme.panel);
            mig_label(g, rect, app->view.cells[r][c]);
        }
    }
    mig_label(g, (mgx_rect){12, 426, WIDTH - 24, 24},
              "Arrows: move   Enter: edit   Ctrl+S: save");
    mig_label(g, (mgx_rect){12, 452, WIDTH - 24, 24}, app->status);
    mulib_immgtk_native_end(g);
    if (g->error) return false;
    if (closed || saved || row >= 0) {
        if (closed) quit(app);
        else {
            app->quit_pending = false;
            if (saved) save(app);
            else select_cell(app, row, col);
        }
        return frame(app, NULL, 0);
    }
    return true;
}

typedef struct {
    Display *display;
    Window window;
    XImage *image;
    Atom protocols, wm_delete;
    GC gc;
} XWindow;

static void window_close(XWindow *x)
{
    if (!x->display) return;
    if (x->image) XDestroyImage(x->image);
    if (x->gc) XFreeGC(x->display, x->gc);
    if (x->window) XDestroyWindow(x->display, x->window);
    XCloseDisplay(x->display);
}

static bool window_open(XWindow *x, char error[PX_ERROR])
{
    x->display = XOpenDisplay(NULL);
    if (!x->display) {
        snprintf(error, PX_ERROR, "Cannot open X11 display.");
        return false;
    }
    snprintf(error, PX_ERROR, "Could not create Poindexter X11 window.");
    int fd = ConnectionNumber(x->display);
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) == -1) return false;
    int screen = DefaultScreen(x->display);
    Visual *visual = DefaultVisual(x->display, screen);
    int depth = DefaultDepth(x->display, screen);
    if (visual->class != TrueColor || visual->red_mask != 0xff0000 ||
        visual->green_mask != 0xff00 || visual->blue_mask != 0xff) {
        snprintf(error, PX_ERROR, "X11 requires a standard 24-bit RGB TrueColor visual.");
        return false;
    }
    x->window = XCreateSimpleWindow(x->display, RootWindow(x->display, screen),
                                     0, 0, WIDTH, HEIGHT, 0, 0, background & 0xffffff);
    if (!x->window) return false;
    x->gc = XCreateGC(x->display, x->window, 0, NULL);
    if (!x->gc) return false;
    x->image = XCreateImage(x->display, visual, (unsigned)depth, ZPixmap,
                            0, NULL, WIDTH, HEIGHT, 32, 0);
    if (!x->image) return false;
    x->image->data = calloc(HEIGHT, (size_t)x->image->bytes_per_line);
    if (!x->image->data) return false;
    XSizeHints hints = {.flags = PMinSize | PMaxSize, .min_width = WIDTH,
                        .min_height = HEIGHT, .max_width = WIDTH, .max_height = HEIGHT};
    XSetWMNormalHints(x->display, x->window, &hints);
    XStoreName(x->display, x->window, "Poindexter Worksheet");
    x->protocols = XInternAtom(x->display, "WM_PROTOCOLS", False);
    x->wm_delete = XInternAtom(x->display, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(x->display, x->window, &x->wm_delete, 1);
    XSelectInput(x->display, x->window, ExposureMask | KeyPressMask | FocusChangeMask |
                 ButtonPressMask | ButtonReleaseMask);
    XMapWindow(x->display, x->window);
    return true;
}

static void present(XWindow *x, const mgx_surface *surface)
{
    const uint32_t *pixels = surface->pixels;
    for (int y = 0; y < HEIGHT; ++y)
        for (int col = 0; col < WIDTH; ++col)
            XPutPixel(x->image, col, y, pixels[(size_t)y * surface->stride + col] & 0xffffffu);
    XPutImage(x->display, x->window, x->gc, x->image, 0, 0, 0, 0, WIDTH, HEIGHT);
    XFlush(x->display);
}

static bool app_event(App *app, XWindow *x, XEvent *event)
{
    mgx_event feed[2] = {0};
    size_t count = 0;
    if (event->type == KeyPress) {
        KeySym sym = NoSymbol;
        char bytes[8];
        int n = XLookupString(&event->xkey, bytes, sizeof bytes, &sym, NULL);
        key(app, sym, event->xkey.state, n == 1 ? bytes[0] : '\0');
    } else if ((event->type == ButtonPress || event->type == ButtonRelease) &&
               event->xbutton.button == Button1) {
        feed[0] = (mgx_event){.type = MGX_EVENT_MOTION, .x = event->xbutton.x, .y = event->xbutton.y};
        feed[1] = (mgx_event){.type = MGX_EVENT_BUTTON, .down = event->type == ButtonPress};
        count = 2;
    } else if (event->type == FocusOut || event->type == FocusIn) {
        feed[0] = (mgx_event){.type = MGX_EVENT_FOCUS, .down = event->type == FocusIn};
        count = 1;
    } else if (event->type == ClientMessage && event->xclient.message_type == x->protocols &&
               event->xclient.format == 32 && (Atom)event->xclient.data.l[0] == x->wm_delete) {
        quit(app);
    }
    return app->done || frame(app, feed, count);
}

int main(int argc, char **argv)
{
    static const char usage[] = "Usage: poindexter-gui --book LOCAL_WORKBOOK\n"
        "Set POINDEXTER_EXE to the compiled On1x worksheet worker if not located beside this executable.\n";
    if (argc == 2 && !strcmp(argv[1], "--help")) {
        fputs(usage, stdout);
        return 0;
    }
    if (argc != 3 || strcmp(argv[1], "--book") || !argv[2][0]) {
        fputs(usage, stderr);
        return 2;
    }
    char path[PATH_MAX];
    const char *worker = getenv("POINDEXTER_EXE");
    if (!worker || !*worker) {
        ssize_t n = readlink("/proc/self/exe", path, sizeof path - 1);
        if (n <= 0 || (size_t)n >= sizeof path - 1) return 2;
        path[n] = '\0';
        char *slash = strrchr(path, '/');
        if (!slash || (size_t)(slash + 1 - path) + sizeof "poindexter-grid" > sizeof path)
            return 2;
        strcpy(slash + 1, "poindexter-grid");
        worker = path;
    }
    App app = {0};
    XWindow x = {0};
    int status = 2;
    if (app_open(&app, worker, argv[2]) && window_open(&x, app.status)) {
        bool ok = frame(&app, NULL, 0);
        while (ok && !app.done) {
            XEvent event;
            XNextEvent(x.display, &event);
            ok = app_event(&app, &x, &event);
            if (ok && !app.done) present(&x, &app.surface);
        }
        if (ok) status = 0;
        else message(&app, "ImmGTK frame failed.");
    }
    if (status) fprintf(stderr, "Poindexter GUI: %s\n", app.status);
    window_close(&x);
    app_close(&app);
    return status;
}
