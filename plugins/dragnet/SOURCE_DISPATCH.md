# Dragnet trusted Source dispatcher (experimental @1)

This is a **statically linked, local and offline** source-dispatch boundary.
It does not provide an SDK v3, a dynamic loader, an OS sandbox, a durable
store, an action gateway, or authorization to retrieve any network resource.

The implementation lives at:

- `source/dragnet/source_registry.on1x`: closed allowlist and pure invocation.
- `source/dispatch_host.on1x`: host-controlled descriptor reader and stdout.
- `build-dispatch.sh`: builds the host with the matching On1x/MuLIB toolchain.

## Build

```sh
plugins/dragnet/build-dispatch.sh "$PWD/build/dragnet-dispatch"
python3 tests/check_dragnet_dispatch.py
```

The host reads the source selector (one ASCII identifier plus `LF`) from file
descriptor 3. Only the file descriptors required by the chosen source are read.
The caller must select trustworthy, unchanged, regular snapshots in its own
private directory and supply the **already decoded** source handoff for
Crossref/public feeds. This process never fetches URLs or runs the decoder.

| Source selector | fd 4 | fd 5 | fd 6 | fd 7 | fd 8 | Output |
| --- | --- | --- | --- | --- | --- | --- |
| `dragnet.frozen_csv@1` | Scenario CSV | Offers CSV | — | — | — | `hospitality.offer@1` JSON Lines |
| `dragnet.crossref@1` | Request CSV | Search raw bytes | Work raw bytes | Search decode | Work decode | `dragnet.crossref-evidence@1` JSON |
| `dragnet.public-feed@1` | Capture CSV | Raw HTTP body | Provider decode | As-of UTC with LF | — | `dragnet.public-feed@1` JSON |

The descriptor API returns a version, output kind/encoding, effect, bounds and
a pure `SourceOutcome`. The process prints only the existing adapter's output
bytes; no new serialized contract identity or run ID is generated here. The
host checks the registration and mode **before opening source content**. Both
source module and process gate reject unknown source IDs and versions.

The existing `dragnet.frozen_csv` SDK admission check remains mandatory. The
Crossref/public-feed policies are deliberately **local to this trusted
process**; they are not yet entries in the general SDK package registry or
callable through the financial Automat. A future registered Source SDK must
perform independent capability and package-version checks and must not
confer network permissions from strategy text alone.

## Semantics and safety

- The `frozen_csv` source preserves existing validated offer envelopes and
  requires its scenario as a separate input.
- `crossref` requires previously generated bounded decoder handoffs. The
  implementation independently checks the raw digest, time cutoffs and DOI.
- `public-feed` requires an offline decoder handoff. The normalization keeps
  its existing provider, chronology, unit and quality checks.
- All three call the same On1x implementations as their pre-existing hosts,
  with no change to the serialized output formats.
- This does **not** upgrade a reference FX quote to a tradeable price, an
  aggregate Eurostat observation to room inventory, or any source data to an
  actionable recommendation. No existing v1/v2 pricing run is rewritten.
- The process uses the existing runtime's file operations. `fd` confinement
  and private snapshot selection are caller responsibilities; do not place
  untrusted filenames, symlinks or hostile shared directories on that boundary.

## Tests and remaining gates

`check_dragnet_dispatch.py` compares exact output bytes with the existing
hosts for frozen CSV, Crossref, ECB and Eurostat, and independently validates
their schemas. It checks selector syntax, missing/empty/oversized descriptors,
duplicate CSV observations, mismatched handoffs and late captures. It also
checks that direct registry invocation denies non-analysis modes, and checks
for pricing-store changes and, when `strace` is available, network syscalls.
CI installs native decoder dependencies and runs this test after the
separate public-feed conformance test.

The complete FinPRED plugin-runtime milestone remains open. Before allowing
new Source packages without rebuilding this host, implement and review a
versioned SDK source package registry, capability grants, build identities,
error mapping, and an appropriate isolation boundary for untrusted plugins.
No such authority is implied by the dispatcher introduced here.
