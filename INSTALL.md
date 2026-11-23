# Install and verify FinPRED

Build from the **FinPRED repository root**. The verified platform is x86-64 GNU/Linux. MuLIB, its On1x compiler and the nested LibStone sources are separate dependencies; `bin/build.sh` does not download them. The [acceptance record](docs/IMPLEMENTATION.md#acceptance-record) gives the tested host, versions and commands. For what the program does, see the [overview](README.md).

The build wrapper assembles the host and its linked `plugins/` modules in a
temporary project because On1xfile discovers one source tree. Use `./bin/build.sh`
for the CLI; set `FINPRED_BUILD_DIR` to choose a different output directory.
After building `on1xc`, `make` is equivalent to `./bin/build.sh`.
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

On a fresh checkout:

```sh
export MULIB_ROOT="$PWD/third_party/mulib"
git clone https://github.com/Chubek/mulib.git "$MULIB_ROOT"
git -C "$MULIB_ROOT" checkout --detach 49de89acbc97efbee493d6b28d02c8f64ed4f725
git -C "$MULIB_ROOT" submodule update --init on1x/third_party/libstone
git -C "$MULIB_ROOT" rev-parse HEAD
git -C "$MULIB_ROOT/on1x/third_party/libstone" rev-parse HEAD
```

Check that the last two lines are, respectively:

```text
49de89acbc97efbee493d6b28d02c8f64ed4f725
b5c962721a32df18b2fb22de136c1f2ef8b6390d
```

For an existing pinned checkout, export its **absolute path** as `MULIB_ROOT` instead, skip the clone and confirm the two revisions. Keep local dependency edits separate when reproducing these results.

## 3. Build the compiler, then the application

```sh
cmake -S "$MULIB_ROOT/on1x" -B "$MULIB_ROOT/build/on1x" \
  -DBUILD_TESTING=ON -DON1X_REQUIRE_LIBSTONE=ON \
  -DON1X_BUILD_NATIVE_PPX=ON -DON1X_BUILD_GRAMMAREMBED=ON \
  -DON1X_LIBSTONE_ROOT="$MULIB_ROOT/on1x/third_party/libstone"
cmake --build "$MULIB_ROOT/build/on1x" --parallel 4 --target on1xc on1x_ppx_GrammarEmbed
./bin/build.sh
./bin/finpred selftest
```

Expect `On1x scanner: LibStone ASDL+Aurocks generated frontend` during configuration and `selftest_ok=true` from the last command. The [build wrapper](bin/build.sh) runs MuLIB’s `on1x/tools/on1x-project.py` against FinPRED’s [On1xfile](On1xfile). By default it uses `$MULIB_ROOT/build/on1x/on1xc` and produces `target/dev/finpred`. To reuse another build of the **same** compiler, export `ON1XC` as its absolute executable path. To select another built **FinPRED** executable for the launcher and suite, export `FINPRED_EXE` as its absolute path.

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
| `Missing MuLIB` / `Missing compiled On1x compiler` | The first requires `$MULIB_ROOT/on1x/tools/on1x-project.py`; the second requires an executable `on1xc`. `ON1XC` alone does not supply the source tree. |
| `Missing LibStone generators` | Check the nested submodule revision and `scripts/asdl.pl` and `scripts/aurocks.pl` under its root. Rerun step 2, then configure against that root. |
| Temporary volume full during configure/build/test | Choose a volume with space: `mkdir -p "$MULIB_ROOT/build/tmp"` then `export TMPDIR="$MULIB_ROOT/build/tmp"` before retrying. On CMake 3.24+, `cmake --fresh` with the same configure arguments clears a stale configuration. |
| `FinPRED On1x executable absent` / launcher accepts a command the executable rejects | Rebuild from the same source tree as `bin/finpred`. Check or unset `FINPRED_EXE` so you test the intended binary. |
| `validate_runtime_json requires Python package jsonschema>=4` | Activate the test environment from step 1 in the shell running the suite. |
| `on1xc --version` exits 2 | This revision has no `--version` option. Use the Git revisions above; `sha256sum "$MULIB_ROOT/build/on1x/on1xc"` identifies a particular built compiler. |
