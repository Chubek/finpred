/* Test-only stand-in for the fixed market sibling. No provider operations. */
#include <stdio.h>
#include <string.h>

static int contains(const char *path, const char *needle)
{
    char buf[2048];
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    int valid = !ferror(f);
    fclose(f);
    buf[n] = 0;
    return valid && strstr(buf, needle);
}

int main(int argc, char **argv)
{
    const char *expected[] = {"scrape", "input/script.caf", "--source", "test_source",
                              "--input-root", "input", "--host-grants", "input/grants.json",
                              "--as-of", "2026-11-26T10:00:00Z"};
    if (argc != (int)(1 + sizeof expected / sizeof *expected)) return 10;
    for (int i = 1; i < argc; ++i)
        if (strcmp(argv[i], expected[i - 1])) return 11;
    if (!contains("input/script.caf", "test-only script") ||
        !contains("input/capture.html", "test-only capture") ||
        !contains("input/grants.json", "\"path\":\"capture.html\"") ||
        !contains("input/grants.json", "\"operations\":[\"scrape\"]") ||
        !contains("input/grants.json", "\"source\":\"test_source\"")) return 12;
    puts("{\"kind\":\"caravansary.market.scrape@1\",\"test_only\":true}");
    return contains("input/script.caf", "fail after write") ? 13 : 0;
}
