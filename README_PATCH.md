# FinPRED Dragnet patch bundle

Baseline: `Chubek/finpred` `master` at
`6d3994a2c9caeda157592b5a556b002113ff5edf` (2026-11-23).

**This is an overlay of changed/new files, not a complete copy of FinPRED.**
The original repository, other plugins and historical run formats stay as-is.
Do not try to execute the bundle independently of the original checkout.

## Contents

- `.github/workflows/verify.yml`: installs native test dependencies and
  makes public-feed and trusted-source-dispatch compiled checks mandatory.
- `Makefile`: `make dragnet-test`; `make test` now includes the expanded suite.
- `plugins/dragnet/source/dragnet/source_registry.on1x`: closed, pure Source
  dispatch and metadata for frozen CSV, Crossref and public-feed adapters.
- `plugins/dragnet/source/dispatch_host.on1x`: independent offline host,
  descriptor-only inputs and no access to the FinPRED store.
- `plugins/dragnet/build-dispatch.sh`: On1xfile C11 build staging with no
  changes to the existing frozen-CSV project manifest.
- `tests/check_dragnet_dispatch.py`: compiled end-to-end parity, negative
  and side-effect tests for all three source families.
- `plugins/dragnet/SOURCE_DISPATCH.md`: exact interfaces and limitations.

## Apply

On a clean working tree with the baseline commit checked out, unpack the ZIP
**over the repository root**, preserving relative paths. For example:

```sh
cd /path/to/finpred
test "$(git rev-parse HEAD)" = 6d3994a2c9caeda157592b5a556b002113ff5edf
unzip -o /path/to/finpred-dragnet-patch.zip
# Remove bundle-only notes from the worktree if not wanted:
# rm -f README_PATCH.md VALIDATION.md
```

Check `git diff` before staging anything. Nothing in this patch requires
writing to the GitHub repository or installing system services.

## Validation on a provisioned host

CI expects Ubuntu 24.04 x86-64 with the existing pinned On1x/LibStone toolchain,
plus `pkg-config libcurl4-openssl-dev libxml2-dev libjansson-dev`.

```sh
python3 tests/check_dragnet_public_feeds.py
python3 tests/check_dragnet_dispatch.py
make test
```

The public-feed suite performs loopback HTTP only. The dispatcher performs no
network activity. Do not enable external polling during CI and do not infer
that an offline fixture test establishes live-provider compatibility.

## Limits

The runtime and transport security audits, generalized SDK Source registration,
financial-domain contract registry, signed KernelBind storage admission, and
power-loss durability remain separate milestones. This patch does not claim to
complete them. Read `VALIDATION.md` for tests actually run by the packager.
