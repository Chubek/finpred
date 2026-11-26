#define _GNU_SOURCE
#include "on1x_runtime.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <limits.h>
#include <locale.h>
#include <math.h>
#include <openssl/sha.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Capability adapters only: directory/file primitives, the system clock and
 * tzdata, binary64 conversion, and SHA-256. Policy stays in On1x. */

const char *caravansary_realpath(const char *path)
{
    char *resolved = realpath(path, NULL);
    if (!resolved) return "";
    const char *result = on1x_text_slice(resolved, 0, (int64_t)strlen(resolved));
    free(resolved);
    return result;
}

/* Open every component of an already-resolved absolute path without
 * following a symlink. A component replaced after realpath fails closed. */
static int open_canonical(const char *path)
{
    if (path[0] != '/') return -1;
    int fd = open("/", O_PATH | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return -1;
    ++path;
    for (;;) {
        const char *slash = strchr(path, '/');
        size_t length = slash ? (size_t)(slash - path) : strlen(path);
        char name[NAME_MAX + 1];
        if (!length || length > NAME_MAX || (length == 1 && path[0] == '.') ||
            (length == 2 && path[0] == '.' && path[1] == '.')) {
            close(fd);
            return -1;
        }
        memcpy(name, path, length);
        name[length] = '\0';
        int flags = O_NOFOLLOW | O_CLOEXEC | (slash ? O_PATH | O_DIRECTORY : O_RDONLY | O_NONBLOCK);
        int next = openat(fd, name, flags);
        close(fd);
        if (!slash || next < 0) return next;
        fd = next;
        path = slash + 1;
    }
}

const char *caravansary_read_regular(const char *path, bool canonical, int64_t limit, const char *description)
{
    int fd = canonical ? open_canonical(path) : open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    struct stat st;
    char error[128];
    if (fd < 0 || fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
        if (fd >= 0) close(fd);
        snprintf(error, sizeof error, "%s must be a readable regular file", description);
        on1x_tool_fail(error);
        return "";
    }
    if (st.st_size < 0 || st.st_size > limit) {
        close(fd);
        snprintf(error, sizeof error, "%s exceeds text byte limit", description);
        on1x_tool_fail(error);
        return "";
    }
    FILE *file = fdopen(fd, "rb");
    if (!file) {
        close(fd);
        on1x_tool_fail("cannot open input stream");
        return "";
    }
    /* Allocate at the stable file size. Treat a concurrent size change as
     * invalid instead of reading bytes from a different input snapshot. */
    size_t size = (size_t)st.st_size;
    char *bytes = malloc(size + 1);
    if (!bytes) {
        fclose(file);
        on1x_tool_fail("cannot allocate input text");
        return "";
    }
    size_t count = fread(bytes, 1, size, file);
    int extra = fgetc(file);
    bool valid = count == size && extra == EOF && !ferror(file) && !memchr(bytes, 0, size);
    if (fclose(file) != 0) valid = false;
    if (!valid) {
        free(bytes);
        on1x_tool_fail("input cannot be read as NUL-free text");
        return "";
    }
    bytes[size] = '\0';
    const char *result = on1x_text_slice(bytes, 0, (int64_t)size);
    free(bytes);
    return result;
}

static bool zone_path(const char *name, char *path, size_t size)
{
    static const char *const directories[] = {
        "/usr/share/zoneinfo", "/usr/lib/zoneinfo", "/usr/share/lib/zoneinfo", "/etc/zoneinfo",
    };
    if (!*name || strcmp(name, "localtime") == 0 || strcmp(name, "posixrules") == 0 ||
        strcmp(name, "posix") == 0 || strncmp(name, "posix/", 6) == 0 ||
        strcmp(name, "right") == 0 || strncmp(name, "right/", 6) == 0 ||
        name[0] == '/' || name[strlen(name) - 1] == '/' || strstr(name, "//") ||
        strspn(name, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_+-/") != strlen(name)) return false;
    for (size_t i = 0; i < sizeof directories / sizeof directories[0]; ++i) {
        int length = snprintf(path, size, "%s/%s", directories[i], name);
        if (length <= 0 || (size_t)length >= size) continue;
        FILE *file = fopen(path, "rb");
        if (!file) continue;
        char magic[4];
        bool valid = fread(magic, 1, sizeof magic, file) == sizeof magic && !memcmp(magic, "TZif", 4);
        fclose(file);
        if (valid) return true;
    }
    return false;
}

bool caravansary_has_zone(const char *name)
{
    char path[PATH_MAX];
    return zone_path(name, path, sizeof path);
}

int64_t caravansary_clock(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_REALTIME, &now) != 0) on1x_tool_fail("cannot read the system clock");
    return (int64_t)now.tv_sec * INT64_C(1000000) + now.tv_nsec / 1000;
}

const char *caravansary_local_date(const char *zone, int64_t seconds)
{
    char setting[PATH_MAX + 1] = ":";
    if (!zone_path(zone, setting + 1, sizeof setting - 1))
        on1x_tool_fail("property.timezone is not available in the host IANA timezone database");
    /* This planner is used by a serial CLI. Restore the process setting before
     * returning, including on localtime conversion failure. */
    const char *old = getenv("TZ");
    char *saved = old ? strdup(old) : NULL;
    if ((old && !saved) || setenv("TZ", setting, 1) != 0)
        on1x_tool_fail("cannot set property timezone");
    tzset();
    const time_t time_value = (time_t)seconds;
    struct tm civil;
    bool valid = (int64_t)time_value == seconds && localtime_r(&time_value, &civil) != NULL;
    int status = saved ? setenv("TZ", saved, 1) : unsetenv("TZ");
    free(saved);
    if (status != 0) on1x_tool_fail("cannot restore process timezone");
    tzset();
    if (!valid || civil.tm_year < -1899 || civil.tm_year > 8099)
        on1x_tool_fail("now is outside the property's supported local calendar");
    char out[40];
    if (snprintf(out, sizeof out, "%04d-%02d-%02d",
                 civil.tm_year + 1900, civil.tm_mon + 1, civil.tm_mday) != 10)
        on1x_tool_fail("cannot render property civil date");
    return on1x_text_slice(out, 0, 10);
}

bool caravansary_ipv6(const char *address)
{
    struct in6_addr value;
    return inet_pton(AF_INET6, address, &value) == 1;
}

double caravansary_parse_float(const char *text)
{
    locale_t locale = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    if (!locale) on1x_tool_fail("cannot select C numeric locale");
    char *end;
    double value = strtod_l(text, &end, locale);
    freelocale(locale);
    return end == text || *end ? NAN : value;
}

static int encode_scientific(char out[static 32], bool negative, uint64_t significand,
                             uint64_t first_place, int exponent)
{
    size_t pos = 0;
    if (negative) out[pos++] = '-';
    out[pos++] = (char)('0' + significand / first_place);
    if (first_place != 1) out[pos++] = '.';
    for (uint64_t place = first_place / 10; place; place /= 10)
        out[pos++] = (char)('0' + significand / place % 10);
    return (int)pos + snprintf(out + pos, 32 - pos, "e%+03d", exponent);
}

/* Return the shortest decimal significand with the same binary64 value,
 * favoring the closest decimal (round-to-even on ties). On1x chooses the
 * JSON fixed/scientific notation and exponent spelling. */
const char *caravansary_float_digits(double value)
{
    if (!isfinite(value)) on1x_tool_fail("JSON number must be finite");
    locale_t locale = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
    if (!locale) on1x_tool_fail("cannot select C numeric locale");
    locale_t previous = uselocale(locale);
    if (!previous) on1x_tool_fail("cannot select thread numeric locale");
    char out[32];
    int count = 0;
    uint64_t power = 1;
    for (int precision = 0; precision < 17; ++precision) {
        count = snprintf(out, sizeof out, "%.*e", precision, value);
        if (count <= 0 || count >= (int)sizeof out) break;
        if (strtod_l(out, NULL, locale) == value) break;

        /* At power-of-two boundaries the binary rounding interval is
         * asymmetric. The closest decimal may be just outside the short
         * side; try the adjacent shorter-significand candidates as well. */
        const bool negative = signbit(value);
        const char *p = out + negative;
        uint64_t nearest = 0;
        while (*p != 'e') {
            if (*p != '.') nearest = nearest * 10 + (unsigned)(*p - '0');
            ++p;
        }
        int exponent = (int)strtol(p + 1, NULL, 10);
        uint64_t next_power = power * 10;
        count = nearest == power
            ? encode_scientific(out, negative, next_power - 1, power, exponent - 1)
            : encode_scientific(out, negative, nearest - 1, power, exponent);
        if (strtod_l(out, NULL, locale) == value) break;
        count = nearest + 1 == next_power
            ? encode_scientific(out, negative, power, power, exponent + 1)
            : encode_scientific(out, negative, nearest + 1, power, exponent);
        if (strtod_l(out, NULL, locale) == value) break;
        power = next_power;
    }
    uselocale(previous);
    freelocale(locale);
    if (count <= 0 || count >= (int)sizeof out) on1x_tool_fail("cannot render JSON number");
    return on1x_text_slice(out, 0, count);
}

const char *caravansary_sha256(const char *text)
{
    unsigned char digest[SHA256_DIGEST_LENGTH];
    if (!SHA256((const unsigned char *)text, strlen(text), digest))
        on1x_tool_fail("cannot compute SHA-256 identity");
    static const char hex[] = "0123456789abcdef";
    char out[2 * sizeof digest + 1];
    for (size_t i = 0; i < sizeof digest; ++i) {
        out[2 * i] = hex[digest[i] >> 4];
        out[2 * i + 1] = hex[digest[i] & 15];
    }
    out[2 * sizeof digest] = '\0';
    return on1x_text_slice(out, 0, 2 * sizeof digest);
}
