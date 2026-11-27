#include "temporal.h"

#define MULIB_IMPL_ASOF
#include "mulib-asof.h"
#define MULIB_IMPL_SHA
#define MULIB_IMPL_CRYPTOHASH
#include "mulib-cryptohash.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char catalog_header[] = "finpred-temporal-catalog@1\n";
static const char commit_header[] = "finpred-temporal-commit@1\n";
enum { RECORD_LIMIT = 16384 };

typedef struct {
    mulib_asof_row_t rank;
    int withdrawn;
    char parent[65];
} revision;

typedef struct {
    char catalog[65];
    int64_t effective, knowledge;
    uint64_t keys[FP_TEMPORAL_MAX_KEYS];
    size_t count;
} query;

typedef struct { const char *p, *end; } cursor;
typedef struct { char bytes[RECORD_LIMIT]; size_t size; } wire;

static fp_result failure(fp_status status, fp_phase phase)
{
    return (fp_result){status, phase, FP_UNCHANGED};
}

static int take(cursor *in, const char *literal)
{
    size_t n = strlen(literal);
    if ((size_t)(in->end - in->p) < n || memcmp(in->p, literal, n)) return 0;
    in->p += n;
    return 1;
}

static int number(cursor *in, char delimiter, uint64_t max, uint64_t *out)
{
    if (in->p == in->end || *in->p < '0' || *in->p > '9') return 0;
    if (*in->p == '0' && in->end - in->p > 1 && in->p[1] != delimiter) return 0;
    uint64_t n = 0;
    while (in->p < in->end && *in->p >= '0' && *in->p <= '9') {
        unsigned d = (unsigned)(*in->p++ - '0');
        if (n > max / 10 || (n == max / 10 && d > max % 10)) return 0;
        n = n * 10 + d;
    }
    if (in->p == in->end || *in->p++ != delimiter) return 0;
    *out = n;
    return 1;
}

static int hex_id(cursor *in, char out[65])
{
    if (in->end - in->p < 64) return 0;
    for (size_t i = 0; i < 64; ++i) {
        char c = in->p[i];
        if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) return 0;
    }
    memcpy(out, in->p, 64);
    out[64] = '\0';
    in->p += 64;
    return 1;
}

static int copy_id(const char *id, char out[65])
{
    if (!id) return 0;
    for (size_t i = 0; i < 64; ++i)
        if (!id[i]) return 0;
    if (id[64]) return 0;
    cursor in = {id, id + 64};
    return hex_id(&in, out);
}

static int digest(const char *bytes, size_t size, char out[65])
{
    static const char hex[] = "0123456789abcdef";
    unsigned char hash[32];
    if (!mulib_blake3(bytes, size, hash, sizeof hash)) return 0;
    for (size_t i = 0; i < sizeof hash; ++i) {
        out[2*i] = hex[hash[i] >> 4];
        out[2*i+1] = hex[hash[i] & 15];
    }
    out[64] = '\0';
    return 1;
}

static fp_result verified_read(const fp_store *s, const char *id, char **bytes, size_t *size)
{
    fp_result r = fp_store_read(s, FP_ARTIFACT, id, bytes, size);
    char actual[65];
    if (r.status != FP_OK) return r;
    if (!digest(*bytes, *size, actual)) r.status = FP_IO;
    else if (strcmp(actual, id)) r.status = FP_CONFLICT;
    if (r.status != FP_OK) {
        free(*bytes);
        *bytes = NULL;
        *size = 0;
    }
    return r;
}

static int ordered(const revision *a, const revision *b)
{
    if (a->rank.key != b->rank.key) return a->rank.key < b->rank.key;
    if (a->rank.effective_at != b->rank.effective_at)
        return a->rank.effective_at < b->rank.effective_at;
    if (a->rank.known_at != b->rank.known_at) return a->rank.known_at < b->rank.known_at;
    if (a->rank.revision != b->rank.revision) return a->rank.revision < b->rank.revision;
    if (a->withdrawn != b->withdrawn) return a->withdrawn < b->withdrawn;
    return strcmp(a->parent, b->parent) < 0;
}

static int parse_catalog(const char *bytes, size_t size, revision *rows, size_t *count)
{
    cursor in = {bytes, bytes + size};
    if (!take(&in, catalog_header)) return 0;
    size_t n = 0;
    while (in.p != in.end) {
        uint64_t key, effective, known, rev;
        if (n == FP_TEMPORAL_MAX_ROWS ||
            !number(&in, ',', UINT64_MAX, &key) || !key ||
            !number(&in, ',', INT64_MAX, &effective) ||
            !number(&in, ',', INT64_MAX, &known) ||
            !number(&in, ',', UINT32_MAX, &rev)) return 0;
        revision *r = &rows[n];
        if (take(&in, "present,")) r->withdrawn = 0;
        else if (take(&in, "withdrawn,")) r->withdrawn = 1;
        else return 0;
        if (!hex_id(&in, r->parent) || !take(&in, "\n")) return 0;
        /* Exact integer tokens let MuLIB detect competing provenance as well
         * as competing states; no source value passes through a double. */
        r->rank = (mulib_asof_row_t){key, (int64_t)effective, (int64_t)known,
                                     (uint32_t)rev, (double)(n + 1)};
        if (n && !ordered(&rows[n-1], r)) return 0;
        ++n;
    }
    *count = n;
    return 1;
}

static int parse_commit(const char *bytes, size_t size, query *q)
{
    cursor in = {bytes, bytes + size};
    uint64_t effective, knowledge;
    if (!take(&in, commit_header) || !take(&in, "catalog=") || !hex_id(&in, q->catalog) ||
        !take(&in, "\neffective=") || !number(&in, '\n', INT64_MAX, &effective) ||
        !take(&in, "knowledge=") || !number(&in, '\n', INT64_MAX, &knowledge)) return 0;
    q->effective = (int64_t)effective;
    q->knowledge = (int64_t)knowledge;
    q->count = 0;
    while (in.p != in.end) {
        size_t n = q->count;
        if (n == FP_TEMPORAL_MAX_KEYS || !take(&in, "selection=") ||
            !number(&in, ',', UINT64_MAX, &q->keys[n]) || !q->keys[n] ||
            (n && q->keys[n-1] >= q->keys[n])) return 0;
        /* The full rows are validated by exact comparison with recomputation. */
        const char *lf = memchr(in.p, '\n', (size_t)(in.end - in.p));
        if (!lf) return 0;
        in.p = lf + 1;
        ++q->count;
    }
    return q->count != 0;
}

static int append(wire *w, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    size_t left = sizeof w->bytes - w->size;
    int n = vsnprintf(w->bytes + w->size, left, format, args);
    va_end(args);
    if (n < 0 || (size_t)n >= left) return 0;
    w->size += (size_t)n;
    return 1;
}

static fp_result encode(const query *q, const revision *rows, size_t n, wire *w)
{
    mulib_asof_row_t ranked[FP_TEMPORAL_MAX_ROWS];
    mulib_asof_snapshot_entry_t chosen[FP_TEMPORAL_MAX_KEYS];
    for (size_t i = 0; i < n; ++i) ranked[i] = rows[i].rank;
    /* n and q have already been validated. Upstream reports winning-rank
     * ambiguity and allocation failure identically (both fail closed). */
    if (!mulib_asof_snapshot(ranked, n, NULL, q->keys, q->count, q->effective,
                             q->knowledge, chosen, FP_TEMPORAL_MAX_KEYS))
        return failure(FP_CONFLICT, FP_VALIDATE);
    w->size = 0;
    if (!append(w, "%scatalog=%s\neffective=%" PRId64 "\nknowledge=%" PRId64 "\n",
                commit_header, q->catalog, q->effective, q->knowledge))
        return failure(FP_LIMIT, FP_VALIDATE);
    for (size_t i = 0; i < q->count; ++i) {
        if (chosen[i].status == MULIB_ASOF_MISSING) {
            if (!append(w, "selection=%" PRIu64 ",missing\n", q->keys[i]))
                return failure(FP_LIMIT, FP_VALIDATE);
        } else {
            size_t index = (size_t)chosen[i].row.value;
            if (!index || index > n) return failure(FP_IO, FP_VALIDATE);
            const revision *r = &rows[index-1];
            if (!append(w, "selection=%" PRIu64 ",%s,%" PRId64 ",%" PRId64 ",%" PRIu32 ",%s\n",
                        q->keys[i], r->withdrawn ? "withdrawn" : "present",
                        r->rank.effective_at, r->rank.known_at, r->rank.revision, r->parent))
                return failure(FP_LIMIT, FP_VALIDATE);
        }
    }
    return failure(FP_OK, FP_VALIDATE);
}

static fp_temporal_result execute(const fp_store *s, const query *q,
                                  const char *archived_id, int sync)
{
    fp_temporal_result r = { .stage = FP_TEMPORAL_CATALOG };
    char *bytes;
    size_t size, n;
    revision rows[FP_TEMPORAL_MAX_ROWS];
    wire w;

    r.detail = verified_read(s, q->catalog, &bytes, &size);
    if (r.detail.status != FP_OK) return r;
    if (size > RECORD_LIMIT) r.detail = failure(FP_LIMIT, FP_VALIDATE);
    else if (!parse_catalog(bytes, size, rows, &n)) r.detail = failure(FP_INVALID, FP_VALIDATE);
    free(bytes);
    if (r.detail.status != FP_OK) return r;

    r.detail = encode(q, rows, n, &w);
    if (r.detail.status != FP_OK) return r;
    r.stage = FP_TEMPORAL_COMMIT;
    if (!digest(w.bytes, w.size, r.commit_id)) {
        r.detail = failure(FP_IO, FP_VALIDATE);
        return r;
    }
    if (archived_id) {
        if (strcmp(archived_id, r.commit_id)) {
            r.detail = failure(FP_CONFLICT, FP_VALIDATE);
            return r;
        }
        r.detail = verified_read(s, archived_id, &bytes, &size);
        if (r.detail.status != FP_OK) return r;
        int same = size == w.size && !memcmp(bytes, w.bytes, size);
        free(bytes);
        if (!same) {
            r.detail = failure(FP_CONFLICT, FP_VALIDATE);
            return r;
        }
    }

    /* Include all distinct evidence parents, not only visible winners. The
     * catalog itself is the final prerequisite before the commit. */
    for (size_t i = 0; i <= n; ++i) {
        const char *id = i < n ? rows[i].parent : q->catalog;
        if (i == n && !sync) break; /* catalog was already read and verified */
        if (i < n) {
            if (!strcmp(id, q->catalog) || !strcmp(id, r.commit_id)) {
                r.stage = FP_TEMPORAL_PARENT;
                r.detail = failure(FP_INVALID, FP_VALIDATE);
                return r;
            }
            size_t j = 0;
            while (j < i && strcmp(id, rows[j].parent)) ++j;
            if (j < i) continue;
        }
        r.stage = i < n ? FP_TEMPORAL_PARENT : FP_TEMPORAL_CATALOG;
        r.detail = verified_read(s, id, &bytes, &size);
        if (r.detail.status != FP_OK) return r;
        if (sync) r.detail = fp_store_install(s, FP_ARTIFACT, id, bytes, size);
        free(bytes);
        if (r.detail.status != FP_OK) return r;
    }
    r.stage = FP_TEMPORAL_COMMIT;
    r.detail = sync ? fp_store_install(s, FP_ARTIFACT, r.commit_id, w.bytes, w.size)
                    : (fp_result){FP_OK, FP_READ, FP_EXISTING};
    return r;
}

fp_temporal_result fp_temporal_publish(const fp_store *s, const char *catalog_id,
                                      int64_t effective, int64_t knowledge,
                                      const uint64_t *keys, size_t count)
{
    fp_temporal_result invalid = {FP_TEMPORAL_QUERY, {FP_INVALID, FP_VALIDATE, FP_UNCHANGED}, ""};
    query q;
    if (!s || !keys || !count || count > FP_TEMPORAL_MAX_KEYS ||
        effective < 0 || knowledge < 0 || !copy_id(catalog_id, q.catalog)) return invalid;
    for (size_t i = 0; i < count; ++i) {
        if (!keys[i] || (i && keys[i-1] >= keys[i])) return invalid;
        q.keys[i] = keys[i];
    }
    q.effective = effective;
    q.knowledge = knowledge;
    q.count = count;
    return execute(s, &q, NULL, 1);
}

static fp_temporal_result from_archive(const fp_store *s, const char *id, int sync)
{
    fp_temporal_result r = { .stage = FP_TEMPORAL_COMMIT };
    char checked[65], *bytes;
    size_t size;
    query q;
    if (!s || !copy_id(id, checked)) {
        r.detail = failure(FP_INVALID, FP_VALIDATE);
        return r;
    }
    r.detail = verified_read(s, checked, &bytes, &size);
    if (r.detail.status != FP_OK) return r;
    if (size > RECORD_LIMIT) r.detail = failure(FP_LIMIT, FP_VALIDATE);
    else if (!parse_commit(bytes, size, &q)) r.detail = failure(FP_INVALID, FP_VALIDATE);
    free(bytes);
    if (r.detail.status != FP_OK) return r;
    return execute(s, &q, checked, sync);
}

fp_temporal_result fp_temporal_replay(const fp_store *s, const char *commit_id)
{
    return from_archive(s, commit_id, 0);
}

fp_temporal_result fp_temporal_resume(const fp_store *s, const char *commit_id)
{
    return from_archive(s, commit_id, 1);
}
