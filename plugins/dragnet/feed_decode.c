/* Offline syntax/shape bridge. Only stdout crosses into the On1x importer. */
#include "feed_limits.h"
#define MULIB_IMPL_SHA
#define MULIB_IMPL_CRYPTOHASH
#include "mulib-cryptohash.h"
#include <jansson.h>
#include <libxml/parser.h>
#include <stdio.h>
#include <string.h>

static int token(const char *s, const char *alphabet, size_t min, size_t max) {
    return s && strlen(s) >= min && strlen(s) <= max && strspn(s, alphabet) == strlen(s);
}

static int element(const xmlNode *n, const char *name, const char *ns) {
    return n && n->type == XML_ELEMENT_NODE && n->ns &&
        xmlStrEqual(n->name, BAD_CAST name) && xmlStrEqual(n->ns->href, BAD_CAST ns);
}

/* XML_PARSE_NOBLANKS normally removes formatting whitespace. Check remaining
 * direct children rather than silently dropping unknown elements or text. */
static xmlNode *significant(xmlNode *n) {
    while (n && (n->type == XML_COMMENT_NODE || xmlIsBlankNode(n))) n = n->next;
    return n;
}

static int xml_text_is(xmlNode *n, const char *expected) {
    xmlNode *text = n->children;
    return !n->properties && text && text->type == XML_TEXT_NODE && !text->next &&
        xmlStrEqual(text->content, BAD_CAST expected);
}

static int ecb(const char *body, size_t size) {
    static const char gesmes[] = "http://www.gesmes.org/xml/2002-08-01";
    static const char fx[] = "http://www.ecb.int/vocabulary/2002-08-01/eurofxref";
    if (strstr(body, "<!DOCTYPE")) return 0;  /* no DTD, entities, or external imports */
    xmlDoc *doc = xmlReadMemory(body, (int)size, NULL, "UTF-8",
        XML_PARSE_NONET | XML_PARSE_NOBLANKS | XML_PARSE_NOERROR | XML_PARSE_NOWARNING);
    if (!doc) return 0;
    int ok = 0;
    xmlChar *date = NULL;
    xmlNode *root = xmlDocGetRootElement(doc);
    if (doc->intSubset || doc->extSubset || !element(root, "Envelope", gesmes)) goto done;
    xmlNode *subject = significant(root->children);
    if (!element(subject, "subject", gesmes) || !xml_text_is(subject, "Reference rates")) goto done;
    xmlNode *sender = significant(subject->next);
    if (!element(sender, "Sender", gesmes) || sender->properties) goto done;
    xmlNode *name = significant(sender->children);
    if (!element(name, "name", gesmes) || significant(name->next) ||
        !xml_text_is(name, "European Central Bank")) goto done;
    xmlNode *container = significant(sender->next);
    if (!element(container, "Cube", fx) || container->properties || significant(container->next))
        goto done;
    xmlNode *day = significant(container->children);
    if (!element(day, "Cube", fx) || significant(day->next) || !day->properties ||
        day->properties->next || day->properties->ns) goto done;
    date = xmlGetNoNsProp(day, BAD_CAST "time");
    if (!token((const char *)date, "0123456789-", 10, 10)) goto done;
    puts((const char *)date);
    size_t rows = 0;
    for (xmlNode *row = significant(day->children); row; row = significant(row->next)) {
        if (++rows > 64 || !element(row, "Cube", fx) || significant(row->children) ||
            !row->properties || !row->properties->next || row->properties->next->next ||
            row->properties->ns || row->properties->next->ns) goto done;
        xmlChar *currency = xmlGetNoNsProp(row, BAD_CAST "currency");
        xmlChar *rate = xmlGetNoNsProp(row, BAD_CAST "rate");
        int valid = token((const char *)currency, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", 3, 3) &&
            token((const char *)rate, "0123456789.", 1, 24);
        if (valid) printf("%s,%s\n", (const char *)currency, (const char *)rate);
        xmlFree(currency);
        xmlFree(rate);
        if (!valid) goto done;
    }
    ok = rows != 0;
done:
    xmlFree(date);
    xmlFreeDoc(doc);
    return ok;
}

/* Bound the JSON tree depth before parsing; Jansson rejects duplicate keys,
 * invalid UTF-8 and out-of-range integers. Floats are never used for counts. */
static int json_depth(const char *s) {
    int depth = 0, quoted = 0, escaped = 0;
    for (; *s; s++) {
        if (quoted) {
            if (escaped) escaped = 0;
            else if (*s == '\\') escaped = 1;
            else if (*s == '"') quoted = 0;
        } else if (*s == '"') quoted = 1;
        else if ((*s == '{' || *s == '[') && ++depth > 32) return 0;
        else if ((*s == '}' || *s == ']') && --depth < 0) return 0;
    }
    return depth == 0 && !quoted;
}

static int equal(json_t *v, const char *expected) {
    return json_is_string(v) && json_string_length(v) == strlen(expected) &&
        !strcmp(json_string_value(v), expected);
}

static int ordinal(json_t *v, size_t value) {
    return json_is_integer(v) && json_integer_value(v) == (json_int_t)value;
}

static json_t *dimension_index(json_t *dimension, const char *id) {
    return json_object_get(json_object_get(json_object_get(dimension, id), "category"), "index");
}

static int bounded_keys(json_t *v, size_t count) {
    if (!json_is_object(v) || json_object_size(v) > count) return 0;
    const char *key;
    json_t *item;
    json_object_foreach(v, key, item) {
        if (strlen(key) != 1 || *key < '0' || (size_t)(*key - '0') >= count) return 0;
    }
    return 1;
}

static int eurostat(const char *body, size_t size) {
    static const char *const dimensions[] = {"freq", "c_resid", "unit", "nace_r2", "geo", "time"};
    static const char *const selected[] = {"M", "TOTAL", "NR", "I551-I553", "EU27_2020"};
    if (!json_depth(body)) return 0;
    json_t *root = json_loadb(body, size, JSON_REJECT_DUPLICATES, NULL);
    if (!root) return 0;
    int ok = 0;
    json_t *ext = json_object_get(root, "extension");
    if (!equal(json_object_get(root, "version"), "2.0") ||
        !equal(json_object_get(root, "class"), "dataset") ||
        !equal(json_object_get(root, "source"), "ESTAT") ||
        !equal(json_object_get(ext, "id"), "TOUR_OCC_NIM") ||
        !equal(json_object_get(ext, "agencyId"), "ESTAT")) goto done;
    const char *updated = json_string_value(json_object_get(root, "updated"));
    if (!token(updated, "0123456789-+:T", 24, 24)) goto done;
    json_t *ids = json_object_get(root, "id"), *sizes = json_object_get(root, "size");
    json_t *dims = json_object_get(root, "dimension");
    if (json_array_size(ids) != 6 || json_array_size(sizes) != 6 ||
        json_object_size(dims) != 6) goto done;
    /* Only time varies, so its index is also the flattened position, no
     * matter where Eurostat places it in the dimension order. */
    unsigned seen = 0;
    size_t count = json_object_size(dimension_index(dims, "time"));
    if (!count || count > 3) goto done;
    for (size_t i = 0; i < 6; ++i) {
        size_t k = 0;
        while (k < 6 && !equal(json_array_get(ids, i), dimensions[k])) ++k;
        if (k == 6 || (seen & (1U << k))) goto done;
        seen |= 1U << k;
        json_t *index = dimension_index(dims, dimensions[k]);
        if (k < 5 && (json_object_size(index) != 1 ||
            !ordinal(json_object_get(index, selected[k]), 0))) goto done;
        if (!ordinal(json_array_get(sizes, i), k == 5 ? count : 1)) goto done;
    }
    const char *periods[3] = {0};
    const char *period;
    json_t *pos;
    json_t *time_index = dimension_index(dims, "time");
    json_object_foreach(time_index, period, pos) {
        if (!token(period, "0123456789-", 7, 7)) goto done;
        size_t i = 0;
        while (i < count && !ordinal(pos, i)) ++i;
        if (i == count || periods[i]) goto done;
        periods[i] = period;
    }
    json_t *values = json_object_get(root, "value"), *statuses = json_object_get(root, "status");
    if (!bounded_keys(values, count) || (statuses && !bounded_keys(statuses, count))) goto done;
    puts(updated);
    for (size_t i = 0; i < count; ++i) {
        char key[] = {(char)('0' + i), '\0'};
        const char *flag = "-";
        json_t *status = json_object_get(statuses, key);
        if (status) {
            flag = json_string_value(status);
            if (!token(flag, "abcdefghijklmnopqrstuvwxyz ", 1, 16)) goto done;
        }
        json_t *value = json_object_get(values, key);
        if (!value) printf("%s,-,%s\n", periods[i], flag);
        else if (json_is_integer(value))
            printf("%s,%" JSON_INTEGER_FORMAT ",%s\n", periods[i], json_integer_value(value), flag);
        else goto done;
    }
    ok = 1;
done:
    json_decref(root);
    return ok;
}

int main(int argc, char **argv) {
    int fx = argc == 2 && !strcmp(argv[1], "ecb");
    if (!fx && !(argc == 2 && !strcmp(argv[1], "eurostat"))) {
        fputs("usage: dragnet-feed-decode ecb|eurostat < raw_body\n", stderr);
        return 2;
    }
    char body[dragnet_body_max + 1];
    size_t n = fread(body, 1, sizeof body, stdin);
    if (ferror(stdin) || !n || n > dragnet_body_max || memchr(body, 0, n)) return 1;
    body[n] = 0;
    unsigned char digest[32];
    if (!mulib_blake3(body, n, digest, sizeof digest)) return 1;
    printf("dragnet.feed-decode@1\n%s\n", argv[1]);
    for (size_t i = 0; i < sizeof digest; ++i) printf("%02x", (unsigned)digest[i]);
    putchar('\n');
    /* An unsuccessful, possibly partial handoff MUST NOT be consumed. */
    if (!(fx ? ecb(body, n) : eurostat(body, n)) || fflush(stdout) == EOF) {
        fputs("dragnet: invalid provider snapshot\n", stderr);
        return 1;
    }
    return 0;
}
