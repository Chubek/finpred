#define _POSIX_C_SOURCE 200809L
#include <on1x_runtime.h>

#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

enum { body_limit = 512 * 1024 };

struct response {
    char *body;
    size_t size;
    int status;
    bool too_large, json, media_seen, encoded, encoding_seen;
};

static bool header_is(const char *line, size_t n, const char *key)
{
    size_t length = strlen(key);
    return n > length && line[length] == ':' && !strncasecmp(line, key, length);
}

static bool header_value(const char *line, size_t n, const char *wanted, bool allow_params)
{
    const char *colon = memchr(line, ':', n);
    if (!colon) return false;
    size_t pos = (size_t)(colon - line) + 1;
    while (pos < n && (line[pos] == ' ' || line[pos] == '\t')) ++pos;
    size_t end = pos;
    while (end < n && line[end] != '\r' && line[end] != '\n' &&
           (!allow_params || line[end] != ';')) ++end;
    while (end > pos && (line[end - 1] == ' ' || line[end - 1] == '\t')) --end;
    return end - pos == strlen(wanted) && !strncasecmp(line + pos, wanted, end - pos);
}

static size_t read_header(char *line, size_t size, size_t count, void *context)
{
    size_t n = size * count;
    struct response *r = context;
    if (n >= 12 && !memcmp(line, "HTTP/", 5)) {
        const char *separator = memchr(line, ' ', n);
        r->status = 0;
        if (separator && n - (size_t)(separator - line) >= 4 &&
            separator[1] >= '0' && separator[1] <= '9' &&
            separator[2] >= '0' && separator[2] <= '9' &&
            separator[3] >= '0' && separator[3] <= '9')
            r->status = (separator[1] - '0') * 100 + (separator[2] - '0') * 10 + separator[3] - '0';
        r->json = r->media_seen = r->encoded = r->encoding_seen = false;
    } else if (header_is(line, n, "Content-Type")) {
        r->json = !r->media_seen && header_value(line, n, "application/json", true);
        r->media_seen = true;
    } else if (header_is(line, n, "Content-Encoding")) {
        r->encoded = r->encoding_seen || !header_value(line, n, "identity", false);
        r->encoding_seen = true;
    }
    /* Abort before consuming an error/redirect or an unexpected media body.
     * Provisional 1xx blocks can precede the final response. */
    if ((n == 2 && line[0] == '\r' && line[1] == '\n') || (n == 1 && line[0] == '\n')) {
        if (r->status >= 200 && (r->status != 200 || !r->json || r->encoded)) return 0;
    }
    return n;
}

static size_t read_body(char *data, size_t size, size_t count, void *context)
{
    struct response *r = context;
    if (size && count > (body_limit - r->size) / size) {
        r->too_large = true;
        return 0;
    }
    size_t n = size * count;
    memcpy(r->body + r->size, data, n);
    r->size += n;
    return n;
}

static bool add_header(struct curl_slist **headers, const char *text)
{
    struct curl_slist *next = curl_slist_append(*headers, text);
    if (!next) return false;
    *headers = next;
    return true;
}

/* One authorized request, from the standalone serial CLI. No caller-supplied
 * target, proxy, certificate exceptions, retries, redirects, or raw logging. */
const char *caravansary_booking_exchange(const char *body, const char *token,
                                         const char *affiliate)
{
    static const char failure[] = "000transport_error\n";
    const char *setting = getenv("SSLKEYLOGFILE");
    char *saved = setting ? strdup(setting) : NULL;
    if (setting && !saved) return failure;
    if (unsetenv("SSLKEYLOGFILE") != 0) {
        free(saved);
        return failure;
    }
    bool initialized = curl_global_init(CURL_GLOBAL_DEFAULT) == CURLE_OK;
    CURL *curl = initialized ? curl_easy_init() : NULL;
    char authorization[sizeof "Authorization: Bearer " + 4096];
    char affiliation[sizeof "X-Affiliate-Id: " + 19];
    struct curl_slist *headers = NULL;
    struct response response = {0};
    long status = 0;
    const char *reason = "transport_error";
    if (!curl || strlen(token) > 4096 || strlen(affiliate) > 19) goto done;
    response.body = malloc(body_limit);
    if (!response.body) goto done;
    snprintf(authorization, sizeof authorization, "Authorization: Bearer %s", token);
    snprintf(affiliation, sizeof affiliation, "X-Affiliate-Id: %s", affiliate);
    if (!add_header(&headers, authorization) || !add_header(&headers, affiliation) ||
        !add_header(&headers, "Accept: application/json") ||
        !add_header(&headers, "Accept-Encoding: identity") ||
        !add_header(&headers, "Content-Type: application/json") ||
        !add_header(&headers, "Expect:")) goto done;

#define SET(option, value) do { if (curl_easy_setopt(curl, option, value) != CURLE_OK) goto done; } while (0)
    SET(CURLOPT_URL, "https://demandapi-sandbox.booking.com/3.3/accommodations/search");
    SET(CURLOPT_PROTOCOLS_STR, "https");
    SET(CURLOPT_PROXY, "");
    SET(CURLOPT_FOLLOWLOCATION, 0L);
    SET(CURLOPT_SSL_VERIFYPEER, 1L);
    SET(CURLOPT_SSL_VERIFYHOST, 2L);
    SET(CURLOPT_HTTP_VERSION, (long)CURL_HTTP_VERSION_1_1);
    SET(CURLOPT_HTTP_CONTENT_DECODING, 0L);
    SET(CURLOPT_FRESH_CONNECT, 1L);
    SET(CURLOPT_FORBID_REUSE, 1L);
    SET(CURLOPT_NOSIGNAL, 1L);
    SET(CURLOPT_CONNECTTIMEOUT_MS, 10000L);
    SET(CURLOPT_TIMEOUT_MS, 10000L);
    SET(CURLOPT_MAXFILESIZE_LARGE, (curl_off_t)body_limit);
    SET(CURLOPT_HTTPHEADER, headers);
    SET(CURLOPT_POST, 1L);
    SET(CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    SET(CURLOPT_POSTFIELDS, body);
    SET(CURLOPT_HEADERFUNCTION, read_header);
    SET(CURLOPT_HEADERDATA, &response);
    SET(CURLOPT_WRITEFUNCTION, read_body);
    SET(CURLOPT_WRITEDATA, &response);
#undef SET

    CURLcode rc = curl_easy_perform(curl);
    if (curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status) != CURLE_OK ||
        status < 100 || status > 999) status = 0;
    if (status == 200) {
        if (!response.json || response.encoded) reason = "unexpected_content";
        else if (response.too_large || rc == CURLE_FILESIZE_EXCEEDED) reason = "response_too_large";
        else if (rc == CURLE_PARTIAL_FILE) reason = "invalid_response";
        else if (rc == CURLE_OK) reason = memchr(response.body, 0, response.size) ? "invalid_response" : "";
    }

done:
    if (curl) curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    if (initialized) curl_global_cleanup();
    if (saved) {
        if (setenv("SSLKEYLOGFILE", saved, 1) != 0) reason = "transport_error";
        free(saved);
    }
    size_t data_size = status == 200 && !*reason ? response.size : 0;
    char prefix[64];
    int n = snprintf(prefix, sizeof prefix, "%03ld%s\n", status, reason);
    char *wire = malloc((size_t)n + data_size + 1);
    if (!wire) {
        free(response.body);
        return failure;
    }
    memcpy(wire, prefix, (size_t)n);
    if (data_size) memcpy(wire + n, response.body, data_size);
    wire[(size_t)n + data_size] = '\0';
    free(response.body);
    const char *result = on1x_text_slice(wire, 0, n + (int64_t)data_size);
    free(wire);
    return result;
}
