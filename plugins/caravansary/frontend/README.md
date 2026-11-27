# CaravanScript frontend

Build consumers with the regular direct On1x C11 builder and put the
repository root and `plugins/caravansary` on the include path.
`frontend.parse_script` accepts a
borrowed `buffer` of UTF-8 source bytes. It returns `(config_json, "")` on
success, otherwise `("", diagnostic)`. It does not resolve credentials, load
referenced files, or evaluate transforms. Legacy IANA zone names are checked
against the platform's standard POSIX zoneinfo directories.

Legacy hosts that immediately compile the returned transform AST can use
`frontend.parse_script_syntax` instead. It checks legacy configuration,
syntax and parser limits but defers static transform type checks to that
compiler. It refuses market scripts rather than routing them to a legacy host.

The legacy JSON config keeps its original schema. The optional `transform` member has
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

## Market scripts

Use `frontend.parse_market_script` to require the market dialect and import
the resulting config with `plugins.caravansary.planning.json.parse` if a
canonical immutable tree is needed. `parse_script` can recognize both
dialects; mixing their sections in one script is an error.

```caravan
name = "Fictional sample";
target { id="subject"; type="hotel"; latitude="51.5"; longitude="-0.1"; currency="GBP"; }
target_sources {
  probe {
    kind="fixture"; fixture="sample_capture"; extractor="rates";
    profile_url="https://www.booking.com/hotel/gb/fictional-subject.html";
  }
}
extractors { rates { kind="caravansary.fixture@1"; } }
discovery { sources=["probe"]; radius_m=2500; max_candidates=8; }
pricing { currency="GBP"; floor_minor=8500; ceiling_minor=30000; }
schedule { workflow="offline_market"; every_seconds=3600; start_at="2026-12-01T00:00:00Z"; }
```

Script `name`, `target.name`, `target.address` and `schedule` are optional.
Named blocks become objects keyed by
declaration name. `discovery.sources` contains unique names of declared sources;
every source refers to a declared extractor. Coordinates are decimal strings
in WGS84, radius is in metres, and pricing bounds are positive signed 64-bit
minor-unit amounts in the target's currency. There is no implicit conversion.
`schedule.start_at` is UTC RFC3339 with `Z` and whole seconds. Fixtures and
workflows are registry identifiers, not paths, commands or authorizations.
Hosts must explicitly authorize their resolution and all effects.

`profile_url` is optional inert metadata on a fixture source. The frontend
accepts only the exact `https://www.booking.com/hotel/<country>/<slug>.html`
or `https://www.agoda.com/<slug>/hotel/<destination>.html` forms (Agoda may
start its path with `/en-gb` or `/en-us`). Slugs use unescaped ASCII letters,
digits, hyphens and underscores. The parser neither resolves these URLs nor
checks that properties exist. URLs cannot replace fixture authorization,
and sources of kind `native_profile` are rejected as unsupported.

### Pure functions and modules

```caravan
modules { arithmetic { fn twice(x:int)->int { return x * 2; } } }
functions { fn eligible(minor:int)->bool { return arithmetic.twice(minor) > 9000; } }
```

Only inline pure functions exist: `int`, `bool` and `text` arguments and
results, one return expression, no recursion, and no report counters.
Unqualified calls resolve inside the current module (or at root when used
at root); cross-module calls are qualified. A function cannot import a file,
load a provider, or execute discovery, pricing, or a scheduled job. Neither
declaring nor parsing a function runs it.

`frontend.call_market_function(source, name, arguments_json)` checks the
script and explicitly calls one function, returning `(value_json, "")` or
`("", diagnostic)`. Use an array of JSON scalars and a root name or
`module.name`. The callable uses the same checked arithmetic, short-circuit
logic and evaluation engine as legacy transforms. Limits include 64
functions and 4,096 expression nodes across all blocks, expression depth
64, 16 arguments, 4,096 decoded UTF-8 bytes per text value and 10,000
evaluation steps. It does not implicitly run functions during discovery,
pricing or scheduling. JSON config retains the original expression AST in
the `functions` envelope and each `modules.<name>` envelope; both have empty
`metrics` arrays.

## Build and test

`CaravanScript.llsynth` is synthesized with the pinned LibStone generator and
`std.llsynth` table packer. Native `std.llsynth.recognize` gates the entire
source. Because recognition does not expose a parse tree, `tokens.on1x`
replays the same synthesized DFA for byte spans and the On1x frontend lowers
those tokens into configuration and a statically checked transform AST.

The checked-in `tables.on1x` needs no generator when building or running a
consumer. Regeneration uses `bin/format-on1x.py` with the project's `.on1xfmt`.
Build the pinned toolchain with `make mulib` or set `ON1XC` to its compiler
before regenerating or checking the tables:

```sh
sh plugins/caravansary/frontend/generate-tables.sh
sh plugins/caravansary/frontend/generate-tables.sh --check
```

Run the standalone native frontend test from the repository root with a
pinned On1x already built:

```sh
CC=clang CXX=clang++ sh plugins/caravansary/build.sh --check-frontend
```
