# C11 descriptor SDK

Use `libfinpred_sdk` to discover the built-in Yieldcraft package, inspect its
versioned contract names and matching limits, and check whether a proposed
use is compatible. This library is independently linkable; it has no MuLIB
runtime dependency. Pricing and run admission remain in the On1x executable.

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
