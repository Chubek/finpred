/* Standalone, offline-only C11 decoder. No FinPRED ABI or foreign import. */
#define MULIB_IMPL_PARSEC
#define MULIB_IMPL_STRBUF
#define MULIB_IMPL_BUFFER
#define MULIB_IMPL_INET4
#define MULIB_IMPL_INET6
#define MULIB_IMPL_URI
#define MULIB_IMPL_UTF8
#define MULIB_IMPL_JSON
#define MULIB_IMPL_BOUNDED_TEXT
#define MULIB_IMPL_BROWSER_ORIGIN
#define MULIB_IMPL_FETCH_POLICY
#define MULIB_IMPL_FETCH
#define MULIB_IMPL_URL
#define MULIB_IMPL_HTTP
#define MULIB_IMPL_WEBCLIENT
#define MULIB_IMPL_TSL
#define MULIB_IMPL_HTTPS
#define MULIB_IMPL_ELVI_SCRAPE
#include "mulib-elvi-scrape.h"
#define MULIB_IMPL_SHA
#define MULIB_IMPL_CRYPTOHASH
#include "mulib-cryptohash.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { snapshot_max = 262144, hit_max = 16, field_max = 1024 };

/* Pinned MuLIB library/elvis/Crossref.elvs, without its comment. Not operator- or
 * response-configurable. We invoke only compile/url/parse, never load/search. */
static const char profile[] =
    "elvi crossref\nhost api.crossref.org\nhome https://api.crossref.org/\n"
    "search \"https://api.crossref.org/works?query={query}&rows={limit}&select=title,URL\"\n"
    "format json\nresults /message/items\ntitle /title/0\nurl /URL\nmax_results 30\n";

static int equal_text(const mulib_json_t *v, const char *expected) {
    size_t n = 0;
    const char *s = mulib_json_text(v, &n);
    return s && n == strlen(expected) && !memcmp(s, expected, n);
}

static int valid_keyword(const char *s) {
    size_t n = strlen(s);
    int nonspace = 0;
    if (!n || n > 128) return 0;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c < 32 || c > 126 || c == '\\') return 0;
        if (c != ' ') nonspace = 1;
    }
    return nonspace;
}

static int search(const char *query, const char *raw, size_t n,
                  const mulib_json_t *message, const char *digest) {
    static const char doi_prefix[] = "https://doi.org/";
    const size_t prefix_n = sizeof doi_prefix - 1;
    const mulib_json_t *items = mulib_json_get(message, "items");
    mulib_elvi_scrape_program_t provider;
    mulib_elvi_scrape_result_t hits[hit_max];
    size_t count = 0;
    char url[512];
    if (mulib_json_typeof(items) != MULIB_JSON_ARRAY || mulib_json_size(items) > hit_max) {
        fputs("crossref: expected a bounded work-list page\n", stderr);
        return 1;
    }
    if (!mulib_elvi_scrape_compile(profile, sizeof profile - 1, &provider, NULL) ||
        !mulib_elvi_scrape_url(&provider, query, hit_max, url, sizeof url) ||
        !mulib_elvi_scrape_parse(&provider, raw, n, hits, hit_max, &count)) {
        fputs("crossref: Elvi work-list decode failed\n", stderr);
        return 1;
    }
    if (count != mulib_json_size(items)) {
        fputs("crossref: ineligible or duplicate search row\n", stderr);
        return 1;
    }
    for (size_t i = 0; i < count; i++) {
        const char *u = hits[i].url;
        if (strncmp(u, doi_prefix, prefix_n) || !u[prefix_n]) {
            fputs("crossref: search result is not a DOI URL\n", stderr);
            return 1;
        }
        for (size_t j = prefix_n; u[j]; j++) {
            if ((unsigned char)u[j] < 33 || (unsigned char)u[j] > 126) {
                fputs("crossref: invalid DOI URL bytes\n", stderr);
                return 1;
            }
        }
    }
    printf("dragnet.crossref-search-decode@1\n%s\n%s\n", digest, url);
    for (size_t i = 0; i < count; i++) puts(hits[i].url + prefix_n);
    return 0;
}

static int work(const mulib_json_t *message, const char *digest) {
    const mulib_json_t *title = mulib_json_get(message, "title");
    if (title && mulib_json_typeof(title) != MULIB_JSON_NULL &&
        mulib_json_typeof(title) != MULIB_JSON_ARRAY) {
        fputs("crossref: work title field must be an array\n", stderr);
        return 1;
    }
    const mulib_json_t *fields[] = {mulib_json_get(message, "DOI"), mulib_json_at(title, 0),
                                    mulib_json_get(message, "publisher"), mulib_json_get(message, "type")};
    char *values[4] = {0};
    int result = 1;
    for (size_t i = 0; i < 4; i++) {
        size_t n = 0;
        if (i && mulib_json_typeof(fields[i]) == MULIB_JSON_NULL) continue;
        const char *s = mulib_json_text(fields[i], &n);
        if (!s || !n || n > field_max) goto done;
        for (size_t j = 0; j < n; j++)
            if ((unsigned char)s[j] < 32 || (unsigned char)s[j] == 127) goto done;
        values[i] = mulib_json_stringify(fields[i], 0);
        if (!values[i]) goto done;
    }
    printf("dragnet.crossref-work-decode@1\n%s\n", digest);
    for (size_t i = 0; i < 4; i++) puts(values[i] ? values[i] : "null");
    result = 0;
done:
    for (size_t i = 0; i < 4; i++) free(values[i]);
    if (result) fputs("crossref: invalid or oversized work field\n", stderr);
    return result;
}

int main(int argc, char **argv) {
    int is_search = argc == 3 && !strcmp(argv[1], "search");
    if (!is_search && !(argc == 2 && !strcmp(argv[1], "work"))) {
        fputs("usage: dragnet-crossref-capture search KEYWORDS | work (snapshot response on stdin)\n", stderr);
        return 2;
    }
    if (is_search && !valid_keyword(argv[2])) {
        fputs("crossref: expected nonblank printable ASCII keywords (max 128 bytes, no backslash)\n", stderr);
        return 1;
    }
    char *raw = malloc(snapshot_max + 1);
    if (!raw) return 1;
    size_t len = fread(raw, 1, snapshot_max + 1, stdin);
    if (ferror(stdin) || !len || len > snapshot_max || memchr(raw, 0, len)) {
        fputs("crossref: invalid snapshot size or bytes (max 262144)\n", stderr);
        free(raw);
        return 1;
    }
    unsigned char hash[32];
    char digest[65];
    if (!mulib_blake3(raw, len, hash, sizeof hash)) {
        fputs("crossref: cannot hash snapshot\n", stderr);
        free(raw);
        return 1;
    }
    for (size_t i = 0; i < sizeof hash; i++) snprintf(digest + 2 * i, 3, "%02x", (unsigned)hash[i]);
    mulib_json_t *root = mulib_json_parse(raw, len, NULL);
    const mulib_json_t *message = mulib_json_get(root, "message");
    int result = 1;
    if (!equal_text(mulib_json_get(root, "status"), "ok") ||
        !equal_text(mulib_json_get(root, "message-type"), is_search ? "work-list" : "work") ||
        mulib_json_typeof(message) != MULIB_JSON_OBJECT) {
        fputs(is_search ? "crossref: invalid work-list response\n" :
                         "crossref: invalid work response\n", stderr);
    } else {
        result = is_search ? search(argv[2], raw, len, message, digest) : work(message, digest);
    }
    mulib_json_destroy(root);
    free(raw);
    if (fflush(stdout) == EOF) return 1;
    return result;
}
