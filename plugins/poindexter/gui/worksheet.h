#ifndef PX_GUI_WORKSHEET_H
#define PX_GUI_WORKSHEET_H

#include <stdbool.h>

enum {
    PX_ROWS = 64, PX_COLS = 16, PX_PAGE_ROWS = 12, PX_PAGE_COLS = 4,
    PX_SOURCE = 192, PX_FIELD = 12, PX_ERROR = 160
};

typedef struct {
    const char *worker, *book;  /* Borrowed launch arguments, never cell data. */
    char *dir;
} PxSession;

typedef struct {
    char cells[PX_PAGE_ROWS][PX_PAGE_COLS][PX_FIELD + 1];
    char source[PX_SOURCE + 1], value[PX_SOURCE + 1];
} PxFrame;

bool px_open(PxSession *, const char *worker, const char *book, char error[PX_ERROR]);
void px_close(PxSession *);
bool px_frame(PxSession *, int row, int col, PxFrame *, char error[PX_ERROR]);
bool px_edit(PxSession *, int row, int col, const char *, PxFrame *, char error[PX_ERROR]);
bool px_save(PxSession *, char error[PX_ERROR]);

#endif
