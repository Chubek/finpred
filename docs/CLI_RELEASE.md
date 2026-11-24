# FinPRED CLI release bundle v1

`finpred-cli-release@1` is a relocatable analysis-only binary bundle for
x86-64 GNU/Linux. It includes the FinPRED launcher and the compiled pricing,
competitor cube and guest-nights forecast hosts, plus the bundled demo fixtures,
strategy files and schemas. It does not include Dragnet adapter executables,
Poindexter frontends, the descriptor SDK, or an On1x compiler. It grants no
financial execution authority. Fixture outcomes are synthetic checks, not
performance evidence.

## Build and verify

Run from a Git checkout with pinned MuLIB and LibStone sources and a paired
`on1xc`/GrammarEmbed build; see [INSTALL](../INSTALL.md) in the repository.
Python 3, Git, GNU/Linux userland, and the C driver and system linker are used
to build and package; runtime does not require Python or the compiler.

```sh
make mulib
python3 bin/release.py build 0.1.0
archive=build/releases/finpred-cli-0.1.0-linux-x86_64.tar.gz
python3 bin/release.py verify "$archive"
```

The version is an explicit `MAJOR.MINOR.PATCH` label. The build uses the
**committed `HEAD`** tree, not edits or generated binaries in the worktree.
It refuses to overwrite either output file. `--output DIR` selects an
alternative destination. `MULIB_ROOT`, `ON1XC`, `FINPRED_STDPPX_DIR` and `CC`
can select an existing local build; the dependency source checkouts must
match the two gitlinks and contain no tracked edits or nonignored untracked
files. No dependency is fetched by this command.

Verification checks the archive structure and exact inventory of file sizes,
modes and SHA-256 digests without extracting anything. For a downloaded archive
also pass `--sha256 DIGEST` using a digest obtained independently from a
trusted channel. The generated `.sha256` is convenient for transfer checks but
does not authenticate the archive; an unauthenticated sender can replace both.
The manifest is a build record, not a signature or a claim that an overridden
compiler was itself built from those sources.

After verification, extract into a directory you control:

```sh
mkdir -p build/install
tar -xzf "$archive" -C build/install
cli="$PWD/build/install/finpred-cli-0.1.0-linux-x86_64/bin/finpred"
"$cli" selftest
export FINPRED_HOME="$PWD/build/my-private-finpred"
"$cli" run
```

The launcher can run from a different current directory. Keep `FINPRED_HOME`
absolute and outside the extracted tree for user state. Unset `FINPRED_EXE`
and `FINPRED_BUILD_DIR` to select the enclosed binaries rather than a local
development build. The executables require a compatible GNU C library and
system loader; earlier glibc versions than the builder's are not certified.

## Reproducibility and manifest

The payload is regular files under a single versioned root, sorted by path.
USTAR data uses uid/gid zero, no user/group names and the Git commit timestamp;
gzip uses zero mtime and no original name. Modes are 0755 for the launcher and
executables, 0644 otherwise. `release.json` records the independent FinPRED,
MuLIB and LibStone commits, SHA-256 of the specific compiler, PPX, PPX schema
and C driver, C driver version, and Python/zlib versions. Every other payload
file is listed with its mode, byte count and SHA-256. The outer SHA-256 covers
the manifest as well.

CI builds twice using different source-stage paths, scratch paths, output
paths and umasks, checks identity of the compressed bytes, rejects corrupt
archives, and exercises the relocated launcher against synthetic inputs. The
claim is reproducibility with the **same inputs and installed toolchain**,
including system headers, assembler, linker, libraries and compression stack;
it is not a cross-host or independently rebuilt compiler claim. Release
archive hashes are separate from application artifact IDs. No historical
pricing archives, model identifiers or replay contracts are migrated.

The On1x v1 PPX transport preserves canonical paths in source locations and
has a fixed 4 MiB request and response budget. The CLI build puts its temporary
On1x source stage directly in `build/` rather than nesting it in `TMPDIR`, and
relativizes staged locations in the response. Tool scratch still uses `TMPDIR`.
For an unusually deep checkout, set `FINPRED_STAGE_PARENT` to a shorter
writable directory; the release command defaults to the original checkout's
`build/` rather than its nested snapshot. A very large
merged On1x unit can still exceed the compiler's request budget.
