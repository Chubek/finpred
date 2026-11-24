/* Trusted host adapter, not a KernelBind storage admission. MuLIB owns search
 * parsing/readability/hashes; libcurl supplies verified, bounded HTTPS IO. */
#define _POSIX_C_SOURCE 200809L
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
#define MULIB_IMPL_SCRAPE_READABLE
#define MULIB_IMPL_CRYPTOHASH
#define MULIB_IMPL_SHA
#define MULIB_IMPL_OPENAI
#include "mulib-elvi-scrape.h"
#include "mulib-scrape-readable.h"
#include "mulib-cryptohash.h"
#include "mulib-openai.h"
#include <curl/curl.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <strings.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/select.h>
#include <sys/wait.h>

#define CAP 262144
static mulib_json_t *config;
static mulib_elvi_scrape_result_t results[10];
static size_t result_count;
static char *search_body, *page_body, *readable, *quoted, *evidence;
static char *llm_text, *llm_response, *llm_request;
static char llm_endpoint[8192], llm_hash[72];
static char page_url[8192];
static char request_url[8192], search_hash[72], page_hash[72];
static volatile sig_atomic_t cancelled;
static volatile sig_atomic_t worker_pid;
static char received_at[21];
static char page_received[21];
static mulib_json_t *dotenv;
static const char *llm_model, *llm_key, *llm_org, *llm_project;

static void stop(int sig) {
  cancelled = 1;
  if (worker_pid > 0) kill((pid_t)worker_pid,sig);
}
static void fail(const char *message) {
  fprintf(stderr,"dragnet: %s\n",message);
  exit(1);
}
static const char *text(mulib_json_t *v) {
  size_t n = 0;
  const char *s = mulib_json_text(v,&n);
  if (!s || strlen(s) != n) fail("expected text without NUL");
  return s;
}
static int json_is(mulib_json_t *v, const char *expected) {
  size_t n = 0;
  const char *s = mulib_json_text(v,&n);
  return s && n == strlen(expected) && !memcmp(s,expected,n);
}
static char *read_file_checked(const char *path, struct stat *metadata, int private_file) {
  int flags = O_RDONLY | O_NONBLOCK | O_CLOEXEC;
  if (private_file) flags |= O_NOFOLLOW;
  int fd = open(path,flags);
  struct stat st;
  if (fd < 0 || fstat(fd,&st) || !S_ISREG(st.st_mode)
      || st.st_size < 0 || st.st_size > CAP) fail("snapshot/config size or file type");
  if (private_file && (st.st_uid != geteuid() || (st.st_mode & 077))) fail("private file required (0600)");
  if (metadata) *metadata = st;
  FILE *f = fdopen(fd,"rb");
  if (!f) fail("snapshot stream");
  char *s = malloc(CAP + 1);
  if (!s) fail("allocation");
  size_t n = fread(s,1,CAP + 1,f);
  if (n > CAP || ferror(f) || fclose(f)) fail("snapshot read");
  s[n] = 0;
  if (strlen(s) != n) fail("embedded NUL");
  return s;
}
static char *read_file(const char *path) { return read_file_checked(path,NULL,0); }
static void known_keys(mulib_json_t *o, const char *const *keys, size_t count) {
  if (mulib_json_typeof(o) != MULIB_JSON_OBJECT) fail("expected object");
  for (size_t i = 0; i < mulib_json_size(o); i++) {
    size_t n;
    const char *key = mulib_json_key(o,i,&n);
    int known = 0;
    for (size_t j = 0; j < count; j++)
      if (strlen(keys[j]) == n && !memcmp(key,keys[j],n)) known = 1;
    if (!known) fail("unknown configuration field");
  }
}
int64_t dragnet_open(const char *path) {
  const char *const keys[] = {"version","provider","keywords","extraction","as_of",
    "max_results","interval_seconds","transport","fixtures","environment","env_file","llm_fixtures","llm_task"};
  struct stat config_metadata;
  char *raw = read_file_checked(path,&config_metadata,0);
  size_t raw_len = strlen(raw);
  config = mulib_json_parse(raw,raw_len,NULL);
  memset(raw,0,raw_len);
  free(raw);
  if (!config) return 0;
  known_keys(config,keys,sizeof keys/sizeof keys[0]);
  mulib_json_t *v = mulib_json_get(config,"version");
  if (mulib_json_typeof(v) != MULIB_JSON_NUMBER || mulib_json_numeric(v) != 1) return 0;
  if (mulib_json_typeof(mulib_json_get(config,"keywords")) != MULIB_JSON_ARRAY) return 0;
  const char *transport = text(mulib_json_get(config,"transport"));
  if (strcmp(transport,"offline") && strcmp(transport,"https")) return 0;
  mulib_json_t *fixtures = mulib_json_get(config,"fixtures");
  if (!strcmp(transport,"offline") && mulib_json_typeof(fixtures) != MULIB_JSON_OBJECT) return 0;
  if (!strcmp(transport,"https") && fixtures) return 0;
  mulib_json_t *environment = mulib_json_get(config,"environment");
  mulib_json_t *llm_fixtures = mulib_json_get(config,"llm_fixtures");
  mulib_json_t *env_file = mulib_json_get(config,"env_file");
  mulib_json_t *llm_task = mulib_json_get(config,"llm_task");
  int gpt = json_is(mulib_json_get(config,"extraction"),"gpt");
  if (!gpt && (environment || llm_fixtures || env_file || llm_task)) {
    fail("LLM configuration requires gpt extraction");
  }
  if (llm_task) {
    size_t n = strlen(text(llm_task));
    if (n < 1 || n > 2048) fail("llm_task must be 1–2048 bytes");
  }
  if (!strcmp(transport,"https") && llm_fixtures) return 0;
  if (environment) {
    const char *const allowed[] = {"OPENAI_API_KEY","OPENAI_ACCESS_TOKEN","OPENAI_BASE_URL",
      "OPENAI_MODEL","OPENAI_ORG_ID","OPENAI_PROJECT_ID"};
    known_keys(environment,allowed,sizeof allowed/sizeof allowed[0]);
    for (size_t i = 0; i < mulib_json_size(environment); i++) text(mulib_json_at(environment,i));
    if (config_metadata.st_uid != geteuid() || (config_metadata.st_mode & 077))
      fail("inline environment requires owned private config permissions (0600)");
  }
  struct sigaction sa;
  memset(&sa,0,sizeof sa);
  sa.sa_handler = stop;
  sigemptyset(&sa.sa_mask);
  sigaction(SIGINT,&sa,NULL);
  sigaction(SIGTERM,&sa,NULL);
  return curl_global_init(CURL_GLOBAL_DEFAULT) == CURLE_OK;
}
const char *dragnet_setting(const char *key) {
  mulib_json_t *field = mulib_json_get(config,key);
  if (!field && !strcmp(key,"llm_task")) return "Summarize facts relevant to the search.";
  return text(field);
}
int64_t dragnet_number(const char *key) {
  mulib_json_t *v = mulib_json_get(config,key);
  if (!strcmp(key,"keywords")) return (int64_t)mulib_json_size(v);
  double n = mulib_json_numeric(v);
  if (mulib_json_typeof(v) != MULIB_JSON_NUMBER || n < 0 || n > 86400 || n != (int64_t)n)
    fail("expected bounded integer");
  return (int64_t)n;
}
const char *dragnet_keyword(int64_t i) {
  if (i < 0 || i >= dragnet_number("keywords")) fail("keyword index");
  return text(mulib_json_at(mulib_json_get(config,"keywords"),(size_t)i));
}
struct body { char *s; size_t n; };
static size_t receive(char *s, size_t size, size_t nmemb, void *ctx) {
  struct body *b = ctx;
  if (size && nmemb > SIZE_MAX/size) return 0;
  size_t n = size * nmemb;
  if (cancelled || n > CAP - b->n) return 0;
  memcpy(b->s+b->n,s,n); b->n += n; b->s[b->n] = 0;
  return n;
}
static int progress(void *ctx, curl_off_t a, curl_off_t b, curl_off_t c, curl_off_t d) {
  (void)ctx; (void)a; (void)b; (void)c; (void)d;
  return cancelled != 0;
}
/* Check the actual address selected by curl, not only lexical hostnames.
 * IPv6 is denied until its complete public-address policy is implemented. */
static curl_socket_t open_socket(void *ctx, curlsocktype purpose, struct curl_sockaddr *addr) {
  (void)ctx; (void)purpose;
  if (cancelled || addr->family != AF_INET) return CURL_SOCKET_BAD;
  struct sockaddr_in *a = (struct sockaddr_in *)&addr->addr;
  uint32_t ip = ntohl(a->sin_addr.s_addr);
  unsigned first = ip >> 24, second = (ip >> 16) & 255;
  if (first == 0 || first == 10 || first == 127 || first >= 224
      || (first == 169 && second == 254) || (first == 172 && second >= 16 && second <= 31)
      || (first == 192 && second == 168) || (first == 100 && second >= 64 && second <= 127)
      || (first == 198 && (second == 18 || second == 19))
      || (ip >> 8) == 0xc00000 || (ip >> 8) == 0xc00002
      || (ip >> 8) == 0xc63364 || (ip >> 8) == 0xcb0071) return CURL_SOCKET_BAD;
  return socket(addr->family,addr->socktype,addr->protocol);
}
static int granted_in(const char *env, const char *host) {
  const char *grants = getenv(env);
  if (!grants) return 0;
  size_t n = strlen(host);
  while (*grants) {
    const char *end = strchr(grants,',');
    size_t length = end ? (size_t)(end-grants) : strlen(grants);
    if (length == n && !memcmp(host,grants,n)) return 1;
    if (!end) break;
    grants = end+1;
  }
  return 0;
}
static int granted(const char *host) { return granted_in("DRAGNET_ALLOWED_HOSTS",host); }
int64_t dragnet_offer_granted(const char *url) {
  if (!strcmp(dragnet_setting("transport"),"offline")) return 1;
  mulib_browser_origin_t origin;
  return mulib_browser_origin_parse(url,&origin)
    && granted_in("DRAGNET_OFFER_HOSTS",origin.host);
}
static char *https_request(const char *url, const char *post, struct curl_slist *headers, int json) {
  mulib_fetch_policy_t policy = {8191,CAP,0,1,0};
  mulib_browser_origin_t origin;
  if (!mulib_fetch_policy_check(&policy,url) || !mulib_browser_origin_parse(url,&origin))
    fail("URL denied");
  if (!granted(origin.host)) fail("host capability denied; use --allow-host");
  CURL *c = curl_easy_init();
  struct body b = {malloc(CAP+1),0};
  if (!c || !b.s) fail("allocation");
  b.s[0] = 0;
#define OPT(k,v) do { if (curl_easy_setopt(c,k,v) != CURLE_OK) fail("curl option"); } while (0)
  OPT(CURLOPT_URL,url);
  if (post) {
    OPT(CURLOPT_POSTFIELDS,post);
    OPT(CURLOPT_POSTFIELDSIZE,(long)strlen(post));
    OPT(CURLOPT_HTTPHEADER,headers);
  }
  OPT(CURLOPT_PROTOCOLS_STR,"https");
  OPT(CURLOPT_FOLLOWLOCATION,0L);
  OPT(CURLOPT_PROXY,"");
  OPT(CURLOPT_SSL_VERIFYPEER,1L);
  OPT(CURLOPT_SSL_VERIFYHOST,2L);
  OPT(CURLOPT_SSLVERSION,CURL_SSLVERSION_TLSv1_2);
  OPT(CURLOPT_CONNECTTIMEOUT,5L);
  OPT(CURLOPT_TIMEOUT,15L);
  OPT(CURLOPT_NOSIGNAL,1L);
  OPT(CURLOPT_USERAGENT,"FinPRED-Dragnet/1");
  OPT(CURLOPT_WRITEFUNCTION,receive);
  OPT(CURLOPT_WRITEDATA,&b);
  OPT(CURLOPT_OPENSOCKETFUNCTION,open_socket);
  OPT(CURLOPT_XFERINFOFUNCTION,progress);
  OPT(CURLOPT_NOPROGRESS,0L);
  CURLcode code = curl_easy_perform(c);
  long status = 0;
  char *type = NULL;
  curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&status);
  curl_easy_getinfo(c,CURLINFO_CONTENT_TYPE,&type);
  struct curl_header *header_info;
  int headers_ok = curl_easy_header(c,"Content-Type",0,CURLH_HEADER,-1,&header_info) == CURLHE_OK
    && header_info->amount == 1;
  CURLHcode encoding = curl_easy_header(c,"Content-Encoding",0,CURLH_HEADER,-1,&header_info);
  headers_ok = headers_ok && (encoding == CURLHE_MISSING ||
    (encoding == CURLHE_OK && header_info->amount == 1 && !strcasecmp(header_info->value,"identity")));
  int valid_type = json ? mulib_openai_media_type(type,"application/json") :
    (type && !strncasecmp(type,"text/html",9) &&
     (!type[9] || type[9] == ';' || type[9] == ' '));
  curl_easy_cleanup(c);
  if (code != CURLE_OK || status != 200 || !valid_type || !headers_ok || strlen(b.s) != b.n) {
    free(b.s);
    if (cancelled) return NULL;
    fail("HTTPS transfer failed (only complete HTTP 200 with expected MIME accepted; no retries/redirects)");
  }
  time_t now = time(NULL);
  struct tm utc;
  if (!gmtime_r(&now,&utc) || strftime(received_at,sizeof received_at,"%Y-%m-%dT%H:%M:%SZ",&utc) != 20)
    fail("capture clock");
  return b.s;
}
static char *fetch(const char *url) {
  mulib_fetch_policy_t policy = {8191,CAP,0,1,0};
  if (!mulib_fetch_policy_check(&policy,url)) fail("URL denied");
  if (!strcmp(dragnet_setting("transport"),"offline")) {
    received_at[0] = 0;
    mulib_json_t *v = mulib_json_get(mulib_json_get(config,"fixtures"),url);
    if (!v) fail("missing offline snapshot; network is disabled");
    return read_file(text(v));
  }
  return https_request(url,NULL,NULL,0);
}
static void hash(const char *s, char out[72]) {
  unsigned char digest[32];
  if (!mulib_blake3(s,strlen(s),digest,sizeof digest)) fail("hash");
  memcpy(out,"blake3:",7);
  for (size_t i = 0; i < 32; i++) sprintf(out+7+i*2,"%02x",digest[i]);
}
const char *dragnet_batch_digest(const char *s) {
  static char digest[72];
  hash(s,digest);
  return digest;
}
int64_t dragnet_search(const char *source, const char *query, int64_t limit) {
  mulib_elvi_scrape_program_t p;
  if (limit < 1 || limit > 10 || !mulib_elvi_scrape_compile(source,strlen(source),&p,NULL)
      || !mulib_elvi_scrape_url(&p,query,(unsigned)limit,request_url,sizeof request_url)) return -1;
  free(search_body); search_body = fetch(request_url);
  if (!search_body) return -1;
  hash(search_body,search_hash);
  if (!mulib_elvi_scrape_parse(&p,search_body,strlen(search_body),results,(size_t)limit,&result_count))
    return -1;
  return (int64_t)result_count;
}
const char *dragnet_url(int64_t i) {
  if (i < 0 || (size_t)i >= result_count) fail("result index");
  return results[i].url;
}
const char *dragnet_page(int64_t i) {
  snprintf(page_url,sizeof page_url,"%s",dragnet_url(i));
  free(llm_request); llm_request = NULL;
  free(llm_response); llm_response = NULL;
  llm_hash[0] = 0;
  free(page_body); page_body = fetch(dragnet_url(i));
  if (!page_body) return "";
  memcpy(page_received,received_at,sizeof page_received);
  hash(page_body,page_hash);
  free(readable); readable = malloc(strlen(page_body)+1);
  if (!readable) fail("allocation");
  mulib_scrape_readable(page_body,readable,strlen(page_body)+1);
  return readable;
}
const char *dragnet_quote(const char *s) {
  mulib_json_t *v = mulib_json_string(s);
  free(quoted); quoted = mulib_json_stringify(v,0);
  mulib_json_destroy(v);
  if (!quoted) fail("JSON encoding");
  return quoted;
}
static void set(mulib_json_t *o, const char *key, const char *value) {
  mulib_json_t *v = mulib_json_string(value);
  if (!v || !mulib_json_set(o,key,v)) fail("JSON allocation");
}
static int credential_name(const char *key) {
  return !strcmp(key,"OPENAI_API_KEY") || !strcmp(key,"OPENAI_ACCESS_TOKEN")
    || !strcmp(key,"OPENAI_BASE_URL") || !strcmp(key,"OPENAI_MODEL")
    || !strcmp(key,"OPENAI_ORG_ID") || !strcmp(key,"OPENAI_PROJECT_ID");
}
static void load_dotenv(void) {
  mulib_json_t *field = mulib_json_get(config,"env_file");
  const char *path = field ? text(field) : ".env";
  struct stat st;
  if (lstat(path,&st)) {
    if (!field && errno == ENOENT) return;
    fail("cannot read env_file");
  }
  if (!S_ISREG(st.st_mode) || st.st_uid != geteuid() || (st.st_mode & 077))
    fail("env_file must be an owned, private regular file (0600)");
  char *raw = read_file_checked(path,NULL,1), *line = raw;
  size_t raw_len = strlen(raw);
  dotenv = mulib_json_new(MULIB_JSON_OBJECT);
  while (*line) {
    char *end = strchr(line,'\n');
    if (end) *end = 0;
    while (*line == ' ' || *line == '\t') line++;
    char *tail = line + strlen(line);
    while (tail > line && (tail[-1] == '\r' || tail[-1] == ' ' || tail[-1] == '\t')) *--tail = 0;
    if (*line && *line != '#') {
      char *equal = strchr(line,'=');
      if (!equal) fail("env_file expects literal KEY=VALUE lines");
      *equal = 0;
      char *value = equal+1;
      tail = equal;
      while (tail > line && (tail[-1] == ' ' || tail[-1] == '\t')) *--tail = 0;
      while (*value == ' ' || *value == '\t') value++;
      size_t length = strlen(value);
      if (length && (*value == '\'' || *value == '"')) {
        if (length < 2 || value[length-1] != *value) fail("env_file quotes");
        value[length-1] = 0; value++;
      }
      if (credential_name(line)) {
        if (mulib_json_get(dotenv,line)) fail("duplicate env_file variable");
        set(dotenv,line,value);
      }
    }
    if (!end) break;
    line = end+1;
  }
  memset(raw,0,raw_len);
  free(raw);
}
static const char *credential(const char *key, const char *fallback) {
  const char *s = getenv(key);
  if (!s) {
    mulib_json_t *v = mulib_json_get(dotenv,key);
    if (!v) v = mulib_json_get(mulib_json_get(config,"environment"),key);
    s = v ? text(v) : fallback;
  }
  if (strlen(s) > 4096) fail("credential/config value too long");
  for (const unsigned char *p = (const unsigned char *)s; *p; p++)
    if (*p < 32 || *p == 127) fail("credential/config value contains controls");
  return s;
}
int64_t dragnet_prepare_llm(void) {
  load_dotenv();
  llm_model = credential("OPENAI_MODEL","");
  if (!*llm_model || strlen(llm_model) > 128) fail("OPENAI_MODEL is required and bounded");
  const char *base = credential("OPENAI_BASE_URL","https://api.openai.com/v1");
  size_t n = strlen(base);
  while (n && base[n-1] == '/') n--;
  if (!n || n > 2048) fail("invalid OPENAI_BASE_URL");
  const mulib_openai_operation_t *op = mulib_openai_operation("createResponse");
  if (!op || strcmp(op->method,"POST") || strcmp(op->path,"/responses")) fail("OpenAI catalog mismatch");
  snprintf(llm_endpoint,sizeof llm_endpoint,"%.*s%s",(int)n,base,op->path);
  mulib_uri_t uri;
  mulib_fetch_policy_t policy = {8191,CAP,0,1,0};
  if (!mulib_fetch_policy_check(&policy,llm_endpoint)
      || !mulib_uri_parse(base,strlen(base),&uri) || uri.has_userinfo
      || uri.has_query || uri.has_fragment) fail("LLM endpoint denied");
  llm_key = credential("OPENAI_API_KEY","");
  const char *token = credential("OPENAI_ACCESS_TOKEN","");
  if (!*llm_key) llm_key = token; /* Pre-obtained OAuth bearer, never a refresh flow. */
  llm_org = credential("OPENAI_ORG_ID","");
  llm_project = credential("OPENAI_PROJECT_ID","");
  if (!strcmp(dragnet_setting("transport"),"offline")) {
    if (mulib_json_typeof(mulib_json_get(config,"llm_fixtures")) != MULIB_JSON_OBJECT)
      fail("offline gpt requires llm_fixtures; network is disabled");
  } else {
    const char *allow = getenv("DRAGNET_ALLOW_LLM");
    if (!allow || strcmp(allow,"1")) fail("LLM data-egress capability denied; use --allow-llm");
    mulib_browser_origin_t origin;
    if (!mulib_browser_origin_parse(llm_endpoint,&origin) || !granted(origin.host))
      fail("LLM host capability denied; use --allow-host");
    if (!*llm_key) fail("OPENAI_API_KEY or OPENAI_ACCESS_TOKEN is required");
  }
  return 1;
}
static struct curl_slist *header(struct curl_slist *list, const char *key, const char *value) {
  char bytes[8192];
  if (snprintf(bytes,sizeof bytes,"%s: %s",key,value) >= (int)sizeof bytes) fail("header size");
  struct curl_slist *next = curl_slist_append(list,bytes);
  if (!next) fail("header allocation");
  return next;
}
const char *dragnet_llm(const char *instructions, const char *input) {
  if (!llm_model) fail("LLM not prepared by host");
  mulib_json_t *request = mulib_json_new(MULIB_JSON_OBJECT);
  set(request,"model",llm_model);
  set(request,"input",input);
  set(request,"instructions",instructions);
  if (!mulib_json_set(request,"store",mulib_json_bool(0))
      || !mulib_json_set(request,"max_output_tokens",mulib_json_number(1024))) fail("JSON allocation");
  free(llm_request); llm_request = mulib_json_stringify(request,0);
  mulib_json_destroy(request);
  if (!llm_request) fail("JSON request");
  free(llm_response); llm_response = NULL;
  if (!strcmp(dragnet_setting("transport"),"offline")) {
    mulib_json_t *v = mulib_json_get(mulib_json_get(config,"llm_fixtures"),page_url);
    if (!v) fail("missing offline LLM snapshot");
    llm_response = read_file(text(v));
  } else {
    struct curl_slist *headers = header(NULL,"Content-Type","application/json");
    char auth[8192];
    snprintf(auth,sizeof auth,"Bearer %s",llm_key);
    headers = header(headers,"Authorization",auth);
    memset(auth,0,sizeof auth);
    if (*llm_org) headers = header(headers,"OpenAI-Organization",llm_org);
    if (*llm_project) headers = header(headers,"OpenAI-Project",llm_project);
    llm_response = https_request(llm_endpoint,llm_request,headers,1);
    curl_slist_free_all(headers);
    if (!llm_response && cancelled) return "";
  }
  hash(llm_response,llm_hash);
  mulib_json_t *response = mulib_json_parse(llm_response,strlen(llm_response),NULL);
  mulib_json_t *items = mulib_json_get(response,"output");
  if (!json_is(mulib_json_get(response,"status"),"completed")
      || mulib_json_typeof(items) != MULIB_JSON_ARRAY || mulib_json_get(response,"choices")
      || mulib_json_typeof(mulib_json_get(response,"error")) != MULIB_JSON_NULL
      || mulib_json_typeof(mulib_json_get(response,"incomplete_details")) != MULIB_JSON_NULL)
    fail("LLM response incomplete, failed or malformed");
  size_t blocks = 0;
  for (size_t i = 0; i < mulib_json_size(items); i++) {
    mulib_json_t *item = mulib_json_at(items,i);
    mulib_json_t *type = mulib_json_get(item,"type");
    mulib_json_t *content = mulib_json_get(item,"content");
    if (json_is(type,"reasoning") && !content) continue;
    if (!json_is(type,"message")) fail("LLM tools/actions are denied");
    if (mulib_json_typeof(content) != MULIB_JSON_ARRAY) fail("LLM response content must be text");
    for (size_t j = 0; j < mulib_json_size(content); j++) {
      mulib_json_t *block = mulib_json_at(content,j);
      if (!json_is(mulib_json_get(block,"type"),"output_text")) fail("LLM response content must be text");
      text(mulib_json_get(block,"text"));
      blocks++;
    }
  }
  if (!blocks) fail("LLM output missing or oversized");
  mulib_json_t *out = mulib_openai_output_text(response);
  const char *s = text(out);
  if (!*s || strlen(s) > 16384) fail("LLM output missing or oversized");
  free(llm_text); llm_text = strdup(s);
  mulib_json_destroy(out);
  mulib_json_destroy(response);
  if (!llm_text) fail("allocation");
  return llm_text;
}
const char *dragnet_evidence(void) {
  mulib_json_t *o = mulib_json_new(MULIB_JSON_OBJECT);
  set(o,"request_url",request_url);
  set(o,"search_html",search_body);
  set(o,"search_digest",search_hash);
  set(o,"page_html",page_body);
  set(o,"page_digest",page_hash);
  set(o,"transport",dragnet_setting("transport"));
  set(o,"received_at",page_received);
  if (llm_response) {
    set(o,"llm_endpoint",llm_endpoint);
    set(o,"llm_model",llm_model);
    set(o,"llm_request",llm_request);
    set(o,"llm_response",llm_response);
    set(o,"llm_digest",llm_hash);
    set(o,"llm_received_at",received_at);
  }
  free(evidence); evidence = mulib_json_stringify(o,0);
  mulib_json_destroy(o);
  if (!evidence) fail("JSON allocation");
  return evidence;
}
int64_t dragnet_cancelled(void) { return cancelled != 0; }
const char *dragnet_received(void) { return received_at; }
int64_t dragnet_worker(void) {
  pid_t child = fork();
  if (child < 0) return -1;
  if (!child) { worker_pid = 0; return 1; }
  worker_pid = (sig_atomic_t)child;
  if (cancelled) kill(child,SIGTERM);
  int status;
  pid_t done;
  do { done = waitpid(child,&status,0); } while (done < 0 && errno == EINTR);
  worker_pid = 0;
  if (cancelled) return 0;
  return done == child && WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}
int64_t dragnet_wait(int64_t seconds) {
  struct timespec delay = {(time_t)seconds,0};
  sigset_t block, old;
  sigemptyset(&block);
  sigaddset(&block,SIGTERM);
  sigaddset(&block,SIGINT);
  if (sigprocmask(SIG_BLOCK,&block,&old)) fail("daemon wait mask");
  int rc = cancelled ? 0 : pselect(0,NULL,NULL,NULL,&delay,&old);
  int wait_error = errno;
  if (sigprocmask(SIG_SETMASK,&old,NULL)) fail("daemon wait restore");
  if (rc < 0 && wait_error != EINTR) fail("daemon wait");
  return !cancelled;
}
int64_t dragnet_emit(const char *bytes) {
  return fputs(bytes,stdout) >= 0 && fflush(stdout) == 0;
}
