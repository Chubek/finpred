/* One MuLIB kernel implementation TU for HTML and Elvi. Do not combine this
 * with the stdlib's standalone HTML, Elvi or lifecycle kernels.c files. The
 * fixture runner never selects an Elvi live/native transport. */
#define MULIB_IMPL_BOUNDED_TEXT
#define MULIB_IMPL_BROWSER_ORIGIN
#define MULIB_IMPL_BUFFER
#define MULIB_IMPL_ELVI_SCRAPE
#define MULIB_IMPL_FETCH
#define MULIB_IMPL_FETCH_POLICY
#define MULIB_IMPL_HTML
#define MULIB_IMPL_HTML_TEXTSTREAM
#define MULIB_IMPL_HTML_TOKENIZER
#define MULIB_IMPL_HTML_TREEBUILDER
#define MULIB_IMPL_HTTP
#define MULIB_IMPL_HTTPS
#define MULIB_IMPL_INET4
#define MULIB_IMPL_INET6
#define MULIB_IMPL_JSON
#define MULIB_IMPL_PARSEC
#define MULIB_IMPL_STRBUF
#define MULIB_IMPL_TSL
#define MULIB_IMPL_URI
#define MULIB_IMPL_URL
#define MULIB_IMPL_UTF8
#define MULIB_IMPL_WEBCLIENT
#define MULIB_IMPL_XML
#define MULIB_IMPL_XPATH

#include "mulib-elvi-scrape.h"
#include "mulib-html.h"
#include "mulib-html-textstream.h"
#include "mulib-html-treebuilder.h"
#include "mulib-xpath.h"
