# CaravanScript frontend

Build consumers with the regular direct On1x C11 builder and put
`plugins/caravansary` on the include path. `frontend.parse_script` accepts a
borrowed `buffer` of UTF-8 source bytes. It returns `(config_json, "")` on
success, otherwise `("", diagnostic)`. It does not resolve credentials, load
referenced files, or evaluate transforms. IANA zone names are checked against
the platform's standard POSIX zoneinfo directories.

Hosts that immediately compile the returned transform AST can use
`frontend.parse_script_syntax` instead. It checks the configuration, syntax
and parser limits but defers static transform type checks to that compiler.

The JSON config keeps the script schema. The optional `transform` member has
ordered `functions` and `metrics`: functions contain `name`, `parameters`
(`[[name, type], ...]`), `return_type` and `expression`; metrics contain
`name` and `expression`. Expressions use the original tagged array encoding:

```text
["literal", value]
["name", name]
["call", callee, [expression, ...]]
["unary", operator, expression]
["binary", operator, left_expression, right_expression]
```

`CaravanScript.llsynth` is synthesized with the pinned LibStone generator and
`std.llsynth` table packer. Native `std.llsynth.recognize` gates the entire
source. Because recognition does not expose a parse tree, `tokens.on1x`
replays the same synthesized DFA for byte spans and the On1x frontend lowers
those tokens into configuration and a statically checked transform AST.

The checked-in `tables.on1x` needs no generator when building or running a
consumer. To regenerate it (or verify it without editing the checkout):

```sh
sh plugins/caravansary/frontend/generate-tables.sh
sh plugins/caravansary/frontend/generate-tables.sh --check
```

Run the standalone native frontend test from the repository root:

```sh
python3 third_party/mulib/on1x/tools/on1x-build.py \
  plugins/caravansary/frontend/tests/main.on1x \
  --on1xc build/mulib/on1x/on1xc -I plugins/caravansary \
  -o build/caravansary-frontend-test
build/caravansary-frontend-test
```
