# Install and verify FinPRED

Build from the **FinPRED repository root**. The verified platform is x86-64 GNU/Linux. MuLIB, its On1x compiler and the nested LibStone sources are separate dependencies; `bin/build.sh` does not download them. The [acceptance record](docs/IMPLEMENTATION.md#acceptance-record) gives the tested host, versions and commands. For what the program does, see the [overview](README.md).

The build wrapper assembles the host and its linked `plugins/` modules in a
temporary project because On1xfile discovers one source tree. Use `./bin/build.sh`
for the CLI; set `FINPRED_BUILD_DIR` to choose a different output directory.
After `make mulib` builds `on1xc` and GrammarEmbed, `make` is equivalent to
`./bin/build.sh`.
Use `make test` to build and verify the CLI, `make native-test` for the
standalone C store tests, and `make poindexter` to build the workbench.
`make poindexter-gui` additionally builds the optional ImmGTK frontend.
It requires the X11 development library and `pkg-config`, not GTK. The
ordinary CLI and terminal workbench do not require X11.

## 1. Prepare the host

Use Git, CMake (On1x requires 3.20 or newer), a CMake build tool such as Make, C11 and C++20 toolchains, Perl for LibStone’s generators, and Python 3 for the build driver and tests. The C11 driver expects `cc` on `PATH`. The recorded build used GCC 16.2.1, CMake 4.4.3 and Python 3.14.7. The compiled pricing CLI itself does not use Python.

The integration suite uses `jsonschema` 4 with Draft 2020-12 support. If it is not already installed, create a test environment (the pin below matches the acceptance record):

```sh
python3 -m venv build/test-venv
. build/test-venv/bin/activate
python3 -m pip install 'jsonschema==4.26.0'
```

## 2. Pin MuLIB and LibStone

On a fresh Git checkout, use the submodule revisions recorded by the checkout:

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
git submodule status third_party/mulib
git -C third_party/mulib submodule status on1x/third_party/libstone
```

A leading `+` in either status line means the checkout differs from the pinned
revision. For an existing compiler source checkout, export its **absolute path**
as `MULIB_ROOT` instead. Verify the revisions against the checkout or the
historical acceptance record you intend to reproduce.

## 3. Build the compiler, then the application

```sh
make mulib                 # optionally set MULIB_JOBS
make
./bin/finpred selftest
```

Expect `On1x scanner: LibStone ASDL+Aurocks generated frontend` during configuration and `selftest_ok=true` from the last command. The [build wrapper](bin/build.sh) runs MuLIB’s `on1x/tools/on1x-project.py` against FinPRED’s [On1xfile](On1xfile).

Build output defaults are relative to the **FinPRED root**, even if `MULIB_ROOT`
points elsewhere:

| Output | Location |
| --- | --- |
| On1x compiler, GrammarEmbed, and MuLIB/LibStone intermediates | `build/mulib/on1x/` |
| FinPRED CLI | `build/dev/finpred` |
| Poindexter grid and optional GUI | `build/poindexter/` |
| Dragnet CSV, Crossref and public-feed tools | `build/dragnet/`, `build/dragnet-crossref/`, `build/dragnet-feeds/` |
| Standalone C review builds | `build/native/`, `build/poindexter-tui-review/` |
| Build and integration-suite scratch space | `build/tmp/` unless `TMPDIR` is set |

Rebuild with `make mulib` rather than moving an old CMake cache out of the MuLIB
checkout; the cache contains absolute paths. `make` does not build or fetch
the compiler implicitly. To reuse a compatible external compiler, set `ON1XC`
to its absolute executable path. To select another built FinPRED executable
for the launcher and suite, set `FINPRED_EXE`.

Ottomat uses the native GrammarEmbed PPX at build time. The wrapper selects
it explicitly for C emission; it does not enable PPX directives from strategy
files. By default the processor is located in `stdppx/` next to `on1xc`. If
using a separate installation, set `FINPRED_STDPPX_DIR` to the directory
containing the matching `on1x-ppx-GrammarEmbed` executable and
`category.schema.json`. MuLIB's source checkout is still required for
the build tools.

## 4. Check the build

The [CI workflow](.github/workflows/verify.yml) runs these checks on Ubuntu
24.04 x86-64. It also builds the independent package consumers, the Poindexter
workbench and the standalone native store tests. The [coverage index](tests/COVERAGE.md)
links the positive and negative cases.

```sh
python3 tests/check_fixtures.py
python3 tests/validate_static.py
./tests/run.sh
```

The oracle should report `price_minor=17100` and `expected_minor=16000`; the static check verifies module declarations and four schemas. Neither runs the pricing engine. The [integration suite](tests/run.sh) exercises the compiled CLI in disposable homes, including both prices and reasons, replay with live paths unavailable, derived room evidence, unchanged store contents, JSON and parent checks, corrupt artifacts, invalid inputs and execution denial. A successful suite ends with `on1x_integration_ok=true`. Continue with the **[operator guide](GUIDE.md)**.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Missing MuLIB` / `Missing compiled On1x compiler` | Initialize the source checkout, then run `make mulib` to build `on1xc` and GrammarEmbed. `ON1XC` alone does not supply the source tree. |
| `Missing LibStone generators` | Check the nested submodule revision and `scripts/asdl.pl` and `scripts/aurocks.pl` under its root. Rerun step 2, then configure against that root. |
| Temporary volume full during configure/build/test | Set `TMPDIR` to a writable executable filesystem with enough space. For an incompatible CMake cache, set the old `build/mulib/on1x` tree aside and rerun `make mulib`. |
| `FinPRED On1x executable absent` / launcher accepts a command the executable rejects | Rebuild from the same source tree as `bin/finpred`. Check or unset `FINPRED_EXE` so you test the intended binary. |
| `validate_runtime_json requires Python package jsonschema>=4` | Activate the test environment from step 1 in the shell running the suite. |
| `on1xc --version` exits 2 | Some revisions have no `--version` option. Use the Git revisions above; `sha256sum build/mulib/on1x/on1xc` identifies a particular built compiler. |
