# Install and verify FinPRED

To build, verify, or install a versioned, relocatable binary bundle for the
three analysis CLI hosts, see [CLI release bundles](docs/CLI_RELEASE.md).

Build from the **FinPRED repository root**. The verification target is
x86-64 GNU/Linux. `bin/build.sh` does not fetch MuLIB or nested LibStone or
build the On1x compiler. The [acceptance record](docs/IMPLEMENTATION.md#acceptance-record)
lists historical hosts, versions and commands; it does not verify your
checkout. See the [overview](README.md) for application scope.

The build wrapper assembles the host and its linked modules in a temporary
source tree. Use `./bin/build.sh`
for the CLI; set `FINPRED_BUILD_DIR` to choose a different output directory.
After `make mulib` builds `on1xc` and GrammarEmbed, `make` is equivalent to
`./bin/build.sh`.
Use `make test` to build and verify the CLI, `make native-test` for the
standalone C store candidate, and `make poindexter` to build the workbench.
`make poindexter-gui` additionally builds the optional ImmGTK frontend.
It requires the X11 development library and `pkg-config`, not GTK. The
ordinary CLI and terminal workbench do not require X11.

`make dragnet` builds the On1x Elvi search host and a separate offline consumer;
`make dragnet-search-test` verifies the pipeline and consumer-neutral handoff
after `make`. `make dragnet-test` verifies the restored legacy offline adapters
and loopback public-feed acquisition. See [Dragnet](plugins/dragnet/README.md)
for credentials, permissions and daemon operation.

## 1. Prepare the host

Use Git, GNU Make, CMake (On1x requires 3.20 or newer), C11 and C++20
toolchains, Perl for LibStone’s generators, and Python 3 for the build driver
and tests. The C11 driver expects `cc` on `PATH`. The compiled pricing CLI
itself does not use Python.

The integration suite, including `make forecast-score-test` for scoring and
evaluation replay, uses `jsonschema` 4 with Draft 2020-12 support. The
forecast graph test uses `pkg-config`, libxml2, and Jansson development headers
for offline fixture decoding. `make test` also runs the offline Dragnet suite,
which additionally needs libcurl ≥ 7.85. On Ubuntu 24.04 those headers are
provided by `libcurl4-openssl-dev`, `libxml2-dev`, and `libjansson-dev`.
The CI workflow also installs `strace` for network-syscall checks during
offline Dragnet verification.
If `jsonschema` is not already installed, create a test environment:

```sh
python3 -m venv build/test-venv
. build/test-venv/bin/activate
python3 -m pip install --require-hashes --only-binary=:all: -r tests/requirements-schema.txt
```

This is the same hash-locked wheel set used by CI. The native wheel hashes
cover standard CPython 3.10–3.14 on glibc Linux (x86-64 and AArch64); that
does not qualify the application for all those hosts.

## 2. Pin MuLIB and LibStone

The MuLIB gitlink recorded by each FinPRED commit and the LibStone gitlink
recorded by that MuLIB commit are authoritative for CI and the default local
build. Older independent CI pins in the implementation notes are historical
records, not a second default toolchain. On a fresh Git checkout:

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
git submodule status third_party/mulib
git -C third_party/mulib submodule status on1x/third_party/libstone
```

A leading `+` in either status line means the checkout differs from the pinned
revision. `make mulib` refuses a mismatched default MuLIB checkout or a
LibStone checkout that does not match the selected MuLIB gitlink. If you are
working in an existing checkout, inspect and preserve any local submodule
work before updating it. To use an external Git checkout, export its **absolute path** as
`MULIB_ROOT`; the nested LibStone pin still applies.

## 3. Build the compiler, then the application

The pinned compiler needs a build-host Cephyr shared library for foreign ABI
table generation. Install Clang, Clang++, llvm-ar, pkg-config and LibYAML
development headers (`clang llvm pkg-config libyaml-dev` on Ubuntu), then provision the pinned
external header checkout with FinPRED's dependency helper:

```sh
sh bin/cephyr-headers.sh fetch third_party/mulib/on1x/third_party/libstone
CC=clang CXX=clang++ make mulib   # optionally set MULIB_JOBS
make
./bin/finpred selftest
```

Use `CEPHYR_LIBRARY=/absolute/path/libcephyr.so` to use a compatible
prebuilt library instead. If an existing CMake build root was initialized
with a different compiler, set `FINPRED_MULIB_BUILD_DIR` to a fresh build
directory for both the compiler build and its consumers.
Valijson is supplied by the LibStone commit and must not be overlaid with
another checkout. The helper verifies or provisions the exact external
nlohmann-json checkout without changing an existing one.

FinPRED's C11 toolchain build uses the checked-in On1x registrar map: the
synchronized Yellowstone source guard still requires a removed Perl Aurocks
path. To qualify Yellowstone generation separately, pass
`ON1X_YELLOWSTONE_HOST_GENERATOR=/absolute/path/on1x-backend-manifest` from
an independently built matching host generator. Neither configuration
proves that FinPRED runs on On1x's other backends.

MuLIB now keeps headers under `kernels/`. FinPRED's Make targets and
verification helpers provide unchanged legacy plugin builders with a
disposable `include/` view of the same checkout. To run such a legacy
builder directly, prefix its command with `sh bin/with-legacy-mulib.sh`.
The helper does not change MuLIB or its gitlinks.

Expect `On1x scanner: LibStone ASDL+native Aurocks generated frontend` during
configuration and `selftest_ok=true` from the last command. The [build wrapper](bin/build.sh)
uses MuLIB’s `on1x-build.py` to link the main FinPRED host and its trusted
price-prediction companion. It explicitly selects the host C driver (`CC`,
or `cc`) rather than depending on MuLIB's native-tool defaults.

Build output defaults are relative to the **FinPRED root**, even if `MULIB_ROOT`
points elsewhere:

| Output | Location |
| --- | --- |
| On1x compiler, GrammarEmbed, and MuLIB/LibStone intermediates | `build/mulib/on1x/` |
| FinPRED CLI (normally invoked as `./bin/finpred`) | `build/dev/finpred` |
| Competitor cube host (invoked as `./bin/finpred cube`) | `build/dev/finpred-cube` |
| Forecast host (invoked as `./bin/finpred forecast`) | `build/dev-forecast/finpred-forecast` |
| Poindexter grid and optional GUI | `build/poindexter/` |
| Dragnet CSV, Crossref, public-feed and dispatcher tools | `build/dragnet/`, `build/dragnet-crossref/`, `build/dragnet-feeds/`, `build/dragnet-dispatch/` (explicit dispatcher output) |
| Standalone C review builds | `build/native/`, `build/poindexter-tui-review/` |
| Build and integration-suite scratch space | `build/tmp/` unless `TMPDIR` is set |
| Temporary On1x source stage | `build/` unless `FINPRED_STAGE_PARENT` is set; keep this path short for the PPX wire budget |

Rebuild with `make mulib` rather than moving an old CMake cache out of the MuLIB
checkout; the cache contains absolute paths. `make` does not build or fetch
the compiler implicitly. To reuse a compatible external compiler, set `ON1XC`
to its absolute executable path. The CLI build, launcher and suite share
`FINPRED_BUILD_DIR`; relative values resolve from the FinPRED root. `FINPRED_EXE`
overrides the launcher and a direct `./tests/run.sh` invocation only.
`make test` ignores that override so it verifies the executable it just built.
The forecast host builds in a sibling directory with the suffix `-forecast`,
using the same `FINPRED_BUILD_DIR` base. Its launcher ignores `FINPRED_EXE`.
The competitor cube host builds as `finpred-cube` next to `finpred` and
also ignores `FINPRED_EXE`.

Ottomat uses the native GrammarEmbed PPX at build time. The wrapper selects
it explicitly for C emission; it does not enable PPX directives from strategy
files. By default the processor is located in `stdppx/` next to `on1xc`. If
using a separate installation, set `FINPRED_STDPPX_DIR` to the directory
containing the matching `on1x-ppx-GrammarEmbed` executable and
`category.schema.json`. Use the compiler, PPX and MuLIB source tools from the
same revision; override paths opt out of the default paired build.

## 4. Check the build

Run the full application suite and the separate native store candidate tests:

```sh
make test
make native-test
```

`make test` builds the CLI and runs the six verification suites, including
Dragnet search and legacy adapters, forecast scoring, independent SDK
consumers, workbench checks, and standalone native CTests. After building, run
one suite independently with `make test-compiler`, `make test-pricing`,
`make test-forecasting`, `make test-plugins`, `make test-storage` or
`make test-security`. The [CI workflow](.github/workflows/verify.yml) explicitly
provisions X11 development files and private Xvfb on Ubuntu 24.04 x86-64;
install `libx11-dev`, `xvfb`, `xauth` and `xfonts-base` for equivalent GUI
coverage locally. The native-store suite does not test KernelBind admission
or power loss; it needs a supported filesystem for its build directory.
The [coverage index](tests/COVERAGE.md) links the positive and negative cases.
The security suite requires the [offline worker](docs/OFFLINE_WORKER.md)
prerequisites, including Bubblewrap and enabled unprivileged user namespaces.

### Format On1x source

With the pinned compiler built, format a file or check all tracked On1x sources:

```sh
python3 bin/format-on1x.py source/ottomat/financial.on1x
git ls-files -z -- '*.on1x' '*.on1xi' |
  xargs -0 python3 bin/format-on1x.py --check
```

The project formatter uses `.on1xfmt` for the 80-column target and basic layout.
It adds leading commas and aligned fields to records, and keeps nested argument
lists inline when they fit. Comments, multiline literals, and indivisible
expressions can exceed 80 columns. Use this script rather than bare `on1xc fmt`
to apply and check the project style.

### Install the descriptor SDK

The C SDK can be installed without the On1x compiler. To install the shared
library, C headers, CMake target and optional Python 3.10+ binding:

```sh
cmake -S source/sdk -B build/sdk -DBUILD_SHARED_LIBS=ON \
  -DFINPRED_INSTALL_PYTHON_SDK=ON -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/sdk-install"
cmake --build build/sdk
cmake --install build/sdk
```

Native CMake consumers use `find_package(FinPREDSDK 1.1 CONFIG REQUIRED)`
and link `FinPRED::sdk`, with the install prefix on `CMAKE_PREFIX_PATH`.
For Python:

```sh
PYTHONPATH="$PWD/build/sdk-install/lib/finpred/python" python3 -c \
  'import sys; from finpred_sdk import SDK; print(SDK(sys.argv[1]).describe("yieldcraft.percentile"))' \
  "$PWD/build/sdk-install/lib/libfinpred_sdk.so"
```

`SDK.check(name, use, host)` takes an independent host inventory and
resource ceilings, and returns the C ABI status. The binding copies
descriptions into immutable Python values. Load only an explicitly selected
trusted SDK shared library by absolute path. These are descriptor APIs, not
plugin invocation or a grant of authority. Test relocation and both consumers
with `python3 tests/check_python_sdk.py`.

For faster checks, use the fixture oracle and static validator; run the
integration script directly only if you already built the intended executable:

```sh
python3 tests/check_fixtures.py
python3 tests/validate_static.py
./tests/run.sh
```

The oracle should report `price_minor=17100` and `expected_minor=16000`.
The static check verifies module declarations and the schemas under
[`contracts/`](contracts/), including the four historical pricing and
hospitality schemas. Neither runs the pricing engine. The
[integration suite](tests/run.sh) exercises the compiled CLI in disposable
homes, checking both prices and reasons, read-only replay without live
inputs, room evidence, parent and digest validation, and denial of execution
mode. It ends with `on1x_integration_ok=true` on success; that marker does
not cover the separate Dragnet, forecast scoring or native tests.
Continue with the **[operator guide](GUIDE.md)**.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Missing MuLIB` / `Missing compiled On1x compiler` | Initialize the source checkout, then run `make mulib` to build `on1xc` and GrammarEmbed. `ON1XC` alone does not supply the source tree. |
| `Submodule pin mismatch` | Compare the expected and actual revisions with the commands in [step 2](#2-pin-mulib-and-libstone). An existing executable is not evidence of a successful build with the pinned compiler. |
| `check_environ_argv.py` reports zero arguments for a nonempty vector | Rebuild `on1xc` with `make mulib` and check for a stale `ON1XC` override. The compiler must generate startup code that forwards the process argv. |
| `Missing LibStone generators` | Check the nested submodule revision and `scripts/asdl.pl` and `scripts/aurocks.pl` under its root. Rerun step 2, then configure against that root. |
| Temporary volume full during configure/build/test | Set `TMPDIR` to a writable executable filesystem with enough space. For an incompatible CMake cache, set the old `build/mulib/on1x` tree aside and rerun `make mulib`. |
| `FinPRED On1x executable absent` / launcher accepts a command the executable rejects | Rebuild from the same source tree as `bin/finpred`. Check or unset `FINPRED_EXE` so you test the intended binary. |
| `validate_runtime_json requires Python package jsonschema>=4` | Activate the test environment from step 1 in the shell running the suite. |
| `on1xc --version` exits 2 | Some revisions have no `--version` option. Use the Git revisions above; `sha256sum build/mulib/on1x/on1xc` identifies a particular built compiler. |
