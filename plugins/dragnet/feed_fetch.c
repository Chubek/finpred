/* Standalone allowlisted GET transport. No decoder, FinPRED ABI, or FFI. */
#define _POSIX_C_SOURCE 200809L
#include "feed_limits.h"
#include <curl/curl.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#ifdef DRAGNET_LOOPBACK_TEST
#include <stdlib.h>
#endif

struct response {
    size_t size, headers;
    int unexpected_encoding;
    char body[dragnet_body_max];
};

static size_t body_cb(char *p, size_t unit, size_t count, void *ctx) {
    struct response *r = ctx;
    if (unit != 1 || count > sizeof r->body - r->size) return 0;
    memcpy(r->body + r->size, p, count);
    r->size += count;
    return count;
}

static size_t header_cb(char *p, size_t unit, size_t count, void *ctx) {
    struct response *r = ctx;
    static const char key[] = "Content-Encoding:";
    if (unit != 1 || count > 16384 - r->headers) return 0;
    r->headers += count;
    if (count >= sizeof key - 1 && !strncasecmp(p, key, sizeof key - 1)) {
        size_t i = sizeof key - 1, stop = count;
        while (i < stop && (p[i] == ' ' || p[i] == '\t')) ++i;
        while (stop > i && strchr(" \t\r\n", p[stop - 1]) && p[stop - 1]) --stop;
        if (stop - i != 8 || strncasecmp(p + i, "identity", 8)) {
            r->unexpected_encoding = 1;
            return 0;
        }
    }
    return count;
}

static int media_is(const char *value, const char *media) {
    if (!value) return 0;
    size_t n = strlen(media);
    return !strncasecmp(value, media, n) && (value[n] == 0 || value[n] == ';');
}

int main(int argc, char **argv) {
    int fx;
    const char *url;
    const char *protocol = "https";
    if (argc !=
#ifdef DRAGNET_LOOPBACK_TEST
        3
#else
        2
#endif
        || (strcmp(argv[1], "ecb") && strcmp(argv[1], "eurostat"))) return 2;
    fx = !strcmp(argv[1], "ecb");
    url = fx ? DRAGNET_ECB_URL : DRAGNET_EUROSTAT_URL;
#ifdef DRAGNET_LOOPBACK_TEST
    char local[512];
    if (!argv[2][0] || strlen(argv[2]) > 5 ||
        strspn(argv[2], "0123456789") != strlen(argv[2])) return 2;
    unsigned long port = strtoul(argv[2], NULL, 10);
    if (!port || port > 65535) return 2;
    int n = snprintf(local, sizeof local, "http://127.0.0.1:%lu%s", port,
        fx ? "/stats/eurofxref/eurofxref-daily.xml" : DRAGNET_EUROSTAT_PATH);
    if (n < 0 || (size_t)n >= sizeof local) return 2;
    url = local;
    protocol = "http";
#endif
    struct response r = {0};
    const char *failure = "transport_setup";
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) goto report;
    CURL *c = curl_easy_init();
    if (!c) goto global_cleanup;
#define SET(option, value) do { if (curl_easy_setopt(c, option, value) != CURLE_OK) goto cleanup; } while (0)
    SET(CURLOPT_URL, url);
    SET(CURLOPT_PROTOCOLS_STR, protocol);
    SET(CURLOPT_FOLLOWLOCATION, 0L);
    SET(CURLOPT_HTTPGET, 1L);
    SET(CURLOPT_PROXY, "");
    SET(CURLOPT_NETRC, (long)CURL_NETRC_IGNORED);
    SET(CURLOPT_SSL_VERIFYPEER, 1L);
    SET(CURLOPT_SSL_VERIFYHOST, 2L);
    SET(CURLOPT_HTTP_CONTENT_DECODING, 0L);
    SET(CURLOPT_ACCEPT_ENCODING, "identity");
    SET(CURLOPT_USERAGENT, "FinPRED-Dragnet/1");
    SET(CURLOPT_CONNECTTIMEOUT_MS, 3000L);
    SET(CURLOPT_TIMEOUT_MS, 10000L);
    SET(CURLOPT_MAXFILESIZE_LARGE, (curl_off_t)dragnet_body_max);
    SET(CURLOPT_WRITEFUNCTION, body_cb);
    SET(CURLOPT_WRITEDATA, &r);
    SET(CURLOPT_HEADERFUNCTION, header_cb);
    SET(CURLOPT_HEADERDATA, &r);
#undef SET
    CURLcode result = curl_easy_perform(c);
    long status = 0;
    char *media = NULL;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_getinfo(c, CURLINFO_CONTENT_TYPE, &media);
    if (r.unexpected_encoding) failure = "content_encoding";
    else if (status == 429 || status == 503) failure = "provider_backoff";
    else if (status && status != 200) failure = "http_status";
    else if (result == CURLE_OPERATION_TIMEDOUT) failure = "timeout";
    else if (result == CURLE_FILESIZE_EXCEEDED || result == CURLE_WRITE_ERROR) failure = "transfer_limit";
    else if (result != CURLE_OK || status != 200 || !r.size) failure = "incomplete_transfer";
    else if (!(fx ? (media_is(media, "text/xml") || media_is(media, "application/xml")) :
                        media_is(media, "application/json"))) failure = "content_type";
    else {
        struct timespec now;
        struct tm utc;
        char receipt[21];
        failure = "local_clock";
        if (clock_gettime(CLOCK_REALTIME, &now) || now.tv_sec < 0) goto cleanup;
        /* The first whole UTC second not before successful transfer. */
        time_t rounded = now.tv_sec + (now.tv_nsec != 0);
        if (!gmtime_r(&rounded, &utc) ||
            strftime(receipt, sizeof receipt, "%Y-%m-%dT%H:%M:%SZ", &utc) != 20) goto cleanup;
        failure = "output_error";
        if (fwrite(r.body, 1, r.size, stdout) != r.size || fflush(stdout) == EOF ||
            fprintf(stderr, "%s\n", receipt) < 0 || fflush(stderr) == EOF) goto cleanup;
        failure = NULL;
    }
cleanup:
    curl_easy_cleanup(c);
global_cleanup:
    curl_global_cleanup();
report:
    if (failure) fprintf(stderr, "%s\n", failure);
    return failure != NULL;
}
