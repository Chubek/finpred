# Static package compatibility SDK

The **v2 package-use check** covers the three statically trusted packages,
in [On1x](packages.on1x) and in the independently linkable
[C11 library](sdk_v2.h). Pricing and run admission remain in the On1x hosts.
The legacy Yieldcraft-only descriptor API is described below.

### Engine registry

[`sdk.registry`](registry.on1x) holds the default-deny policy for the
statically linked call sites. The CLI's Yieldcraft policy binding,
Poindexter view host, frozen CSV source host, and scalar midpoint dispatch
consult it. The legacy runner itself checks its plan but has no plugin
registry dependency.
An entry still has to pass its mode and dependency checks; the midpoint also
has to be available in the graph version. A `plugin.json` describes a package
but cannot register it, and an SDK compatibility result alone cannot invoke it.

The registry is not a sandbox for arbitrary On1x programs. An independent
host linking a library directly controls its own calls. The stand-alone
Crossref tools and worksheet frontends are not engine-dispatched plugins.

### Internal typed calls

[`sdk.callable`](callable.on1x) defines the additive On1x-only typed call
protocol. It owns no registration table: the trusted, statically linked host
supplies `lookup` and `call`. `resolve` is the planning gate; `invoke` resolves
again and checks the exact `Pin` (package and handler versions, protocol ABI,
and BLAKE3 code and policy identities). A pin identifies code relative to
trusted build inputs; it does not authenticate an external author. Neither
the C ABI nor the legacy `sdk.registry` entry points change.

Ports are named, with exact contract kind/major, unit, and currency (`none`
when unset). `connects` requires the producer's state mask and byte maximum
to fit the consumer's. Pass ordered immutable payloads, a UTC cutoff, and an
explicit work allowance; no paths or effect handles are passed. The host
verifies contract semantics, bytes/digests and lineage. The protocol admits
pure analysis and recommendation only. A work allowance is not hard resource
metering, cancellation, or process isolation. `python3 tests/check_sdk_data1.py`
compiles independent consumers and exercises both positive calls and denials.
An explicitly `unknown` output can be zero bytes for formats with a canonical
empty encoding, such as NDJSON. This does not relax input bounds or allow
empty `available` output.

### Legacy package profiles

| Manifest (SDK 1, package 1.0.0) | Invocation mode | Ordered input schema/format IDs → output | Required host dependency IDs |
|---|---|---|---|
| [`dragnet.frozen_csv`](../../plugins/dragnet/plugin.json) (`Source`) | `analysis` | `hospitality.scenario@1`, `finpred.offers.csv@1` → `hospitality.offer@1` | `finpred.core@1`, `yieldcraft.asof-whole-stay-property-min@1` |
| [`yieldcraft.percentile`](../../plugins/yieldcraft/plugin.json) (`Strategy`) | `recommendation` | `hospitality.scenario@1`, `hospitality.offer@1`, `pricing.valuation@1` → `pricing.recommendation@1` | none declared |
| [`poindexter.pricing-sheet`](../../plugins/poindexter/plugin.json) (`View`) | `analysis` | `pricing.recommendation@1`, `pricing.valuation@1` → `poindexter.pricing-sheet@1` | `yieldcraft.percentile@1` |

### Host integration

Import `sdk.packages as P` and call `P.check_v2(name, use, host)` before
dispatch to a statically linked entry point. Native hosts include
`<finpred/sdk_v2.h>`, look up a handle with `finpred_sdk_lookup_v2(2, name, &p)`,
and call `finpred_sdk_check_v2(p, &use, &host)`. A host can inspect requirements
through `finpred_sdk_describe_v2(p)`. Both interfaces take three independent inputs:

- **Identity and use.** The checker selects the compiled profile by name;
  the caller specifies its expected manifest SDK, package version, kind,
  ordered inputs, output, effect, invocation mode and requested capabilities.
  All schema/format/version identifiers must match literally. Dragnet consumes
  raw offers CSV and emits normalized offer envelopes. The pricing sheet is a
  versioned CSV view, not a new persisted pricing contract.
- **Host inventory and budget.** The host supplies its own available dependency
  IDs and ceilings, independently of the manifest. Extra inventory is allowed;
  every declared dependency must be present at its exact `@version`. These are
  static interface IDs, not dynamic discovery, version-range solving, or proof
  of a dependency's provenance. Each declared resource maximum must fit within
  the host's ceiling for that named dimension. Equality passes; zero budgets
  cannot cover positive maxima. Zero in a compiled profile means the manifest
  does not declare that dimension. The check does not meter actual consumption,
  infer missing limits, or replace entry-point validation.
- **Authority.** Requested capabilities must cover required capabilities and
  be contained in the intersection of the host grants and package declaration.
  All three declare `pure` and an empty capability set: even a host grant of
  `network` cannot make a request for `network` admissible. Unknown modes,
  `execution`, publication, and all non-pure effects fail. A compatible result
  is metadata only: no filesystem handle, callback, loader, or action token.

The checker returns `0` for compatibility; `1` for malformed lists or invalid
C arguments; `2` for an incompatible package/contract/dependency/budget;
`3` for unknown name at lookup; and `4` for denied mode/effect/capability.
Lists have at most 16 unique nonempty names of at most 127 bytes each. On1x
uses proper `sexpr` lists of string atoms. C strings/arrays must be valid and
borrowed for the call; returned C metadata has library lifetime. See the
[independent On1x](../../tests/sdk_packages_consumer/main.on1x) and
[C](../../tests/sdk_packages_consumer/main.c) consumers for full call sites.
Their environment-driven inputs are test vectors, not a production grant source.

**Verify:** `python3 tests/check_sdk_packages.py` builds both consumers in a
temporary directory and checks the same 106 cases per host against the three
checked-in manifests, including every resource boundary and dependency.
Verified with MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
`third_party/mulib/build/on1x/on1xc` (C11), Linux x86_64 and GCC 16.2.1.
The v1 consumer (`python3 tests/check_sdk.py`), independent Yieldcraft package
test, Python fixture oracle, static checks, On1xfile build and `tests/run.sh`
also passed (17100 and 16000 cents/night, both unpublished). For a full temp
filesystem, set `TMPDIR` to a writable directory on a disk with space.

### Build and use the legacy v1 API

From the repository root:

```sh
cmake -S source/sdk -B build/sdk -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/sdk-install" -DCMAKE_INSTALL_LIBDIR=lib
cmake --build build/sdk
cmake --install build/sdk
```

For a static archive, configure with `-DBUILD_SHARED_LIBS=OFF`. A native
consumer includes `<finpred/sdk.h>` and links `-lfinpred_sdk`. Example:

```c
#include <finpred/sdk.h>
#include <stdio.h>

int main(void)
{
    const finpred_sdk_plugin_v1 *plugin;
    if (finpred_sdk_lookup_v1(FINPRED_SDK_ABI_V1, "yieldcraft.percentile", &plugin)
        != FINPRED_SDK_OK) return 1;
    if (finpred_sdk_check_v1(plugin, "Strategy", "pricing.recommendation@1",
                            "pure", "recommendation", 0) != FINPRED_SDK_OK) return 1;
    puts(finpred_sdk_describe_v1(plugin)->package_version);
    return 0;
}
```

To compile the example on Linux:

```sh
cc -std=c11 -Ibuild/sdk-install/include example.c -Lbuild/sdk-install/lib \
  -Wl,-rpath,"$PWD/build/sdk-install/lib" -lfinpred_sdk -o example
./example
```

**ABI and lifetimes.** The `_v1` symbols, status values and descriptor layout
are fixed for ABI 1 (shared library major version 1). Library and caller must
use the same native C ABI. Handles and descriptor data are borrowed, immutable,
and valid until that library instance is unloaded. No allocation or release
call is required. An unknown name yields `NOT_FOUND`; an unsupported ABI,
kind or output contract yields `INCOMPATIBLE`; unsupported modes, non-pure
effects and all nonzero capability requests yield `DENIED`. Null required
arguments yield `INVALID`.

`analysis`, `recommendation` and `simulation` are descriptor-compatible modes;
this check does not start any of them or authorize an action. For the actual
pricing workflow use the [CLI](../../GUIDE.md). The C interface does not load
external code or expose filesystem, network or process handles.

`python3 tests/check_sdk.py` builds and installs the shared library in a
temporary directory, compiles a separate C11 consumer, checks failure
statuses, and compares the exported metadata with the
[package descriptor](../../plugins/yieldcraft/plugin.json).
