# Dragnet trusted Source dispatcher (experimental @1)

This is a **statically linked, local and offline** source-dispatch boundary.
It does not provide an SDK v3, a dynamic loader, an OS sandbox, a durable
store, an action gateway, or authorization to retrieve any network resource.

The implementation lives at:

- `source/dragnet/source_registry.on1x`: trusted `sdk.callable` lookup and invoke bindings.
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

The existing `SourceDescriptor`, `SourceOutcome`, and fd selectors are
compatibility wrappers. The process prints only the existing adapter's bytes;
it creates no new serialized contract or run ID. It checks the registration
and mode before opening source content and reads the ordered input ports
and byte ceilings from the resolved SDK descriptor rather than re-declaring
them in the fd host. The public-feed mux reads the shared bounded capture
header first, then resolves the concrete provider before reading its body
or decoder slots.

The SDK resolves the following exact, ordered source profiles, then checks
the same pin again at invocation. It exposes only `pure`/`analysis`:

| SDK handler | Ordered inputs | Cutoff | Output |
| --- | --- | --- | --- |
| `dragnet.frozen_csv@1` | `scenario`, `offers` | Equal to scenario `decision_at` | `hospitality.offer@1`; empty NDJSON is `unknown` |
| `dragnet.crossref@1` | `request`, `search_raw`, `work_raw`, `search_decode`, `work_decode` | Equal to request `as_of` | `dragnet.crossref-evidence@1` |
| `dragnet.public-feed.ecb@1` | `capture`, ECB XML `raw`, ECB `decode` | SDK cutoff | `dragnet.ecb-fx-reference@1` |
| `dragnet.public-feed.eurostat@1` | `capture`, Eurostat JSON-stat `raw`, Eurostat `decode` | SDK cutoff | `dragnet.eurostat-accommodation-nights@1`; missing results may be `partial` |

The frozen CSV binding retains the original `sdk.registry` dependency gate.
The legacy public-feed selector maps the capture's provider to one of the
two concrete SDK handlers. It is not itself a callable SDK handler or a grant.
The concrete provider keys are not accepted as fd selectors.
The application source-closure pin is checked by an independent consumer;
it is not binary attestation or external provider authentication. Existing
parsers still fail closed with their terminal diagnostics on malformed data.

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

`check_dragnet_dispatch.py` compares exact output bytes across the existing
hosts, the fd dispatcher, the five-argument wrapper and a separate compiled
SDK caller for frozen CSV, Crossref, ECB and Eurostat, and independently validates
their schemas. It checks selector syntax, missing/empty/oversized descriptors,
duplicate CSV observations, mismatched handoffs and late captures. It also
checks forged pins, wrong provider, provider rejection before opening payload
slots, per-slot feed caps, wrong arity/state/budget, a valid empty CSV result,
and that direct registry invocation denies non-analysis modes. It checks
for pricing-store changes and, when `strace` is available, network syscalls.
CI installs native decoder dependencies and runs this test after the
separate public-feed conformance test.

Financial Automat does not link these Source bindings by default. Dynamic
packages, recoverable domain errors for the legacy parsers, hard cancellation
and process/OS isolation remain separate work. No such authority is implied
by the dispatcher.
