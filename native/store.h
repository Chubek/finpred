#ifndef FINPRED_NATIVE_STORE_H
#define FINPRED_NATIVE_STORE_H

#include <stddef.h>

/* Host-only review candidate, not an On1x FFI. No ambient store path. */
typedef struct fp_store fp_store;
typedef enum { FP_READER, FP_WRITER } fp_access;
typedef enum { FP_ARTIFACT, FP_RUN } fp_kind;
#define FP_ARTIFACT_MAX ((size_t)2097152)
#define FP_RUN_SIZE ((size_t)404)

typedef enum {
    FP_OK, FP_INVALID, FP_DENIED, FP_SCOPE, FP_MISSING, FP_CONFLICT,
    FP_LIMIT, FP_UNSUPPORTED, FP_IO
} fp_status;
typedef enum {
    FP_VALIDATE, FP_OPEN, FP_READ, FP_WRITE, FP_FILE_SYNC,
    FP_INSTALL, FP_DIR_SYNC, FP_CLOSE
} fp_phase;
/* UNCHANGED means this call did not install a final name. A successful
 * install is either EXISTING (identical) or CREATED, both synced. */
typedef enum { FP_UNCHANGED, FP_EXISTING, FP_CREATED, FP_UNCERTAIN } fp_name_state;
typedef struct {
    fp_status status;
    fp_phase phase;
    fp_name_state name;
} fp_result;

/* root_fd is borrowed and already provisioned by the host. *out is owned
 * on success, NULL on error. Readers never mkdir or fsync. */
fp_result fp_store_open(int root_fd, fp_access access, fp_store **out);
void fp_store_close(fp_store *store);

/* id is a NUL-terminated string of 64 lowercase hex digits, not a path.
 * On success *out owns size bytes plus a convenience NUL; free with free().
 * On error *out == NULL and *size == 0 when both arguments are supplied. */
fp_result fp_store_read(const fp_store *store, fp_kind kind, const char *id,
                        char **out, size_t *size);
/* data is borrowed only during the call. The caller validates the actual
 * digest, manifest references and run-level commit order. */
fp_result fp_store_install(const fp_store *store, fp_kind kind, const char *id,
                           const char *data, size_t size);
#endif
