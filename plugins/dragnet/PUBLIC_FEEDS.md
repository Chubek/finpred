# Public feeds: version 1

Dragnet can acquire two fixed public snapshots and reproduce their versioned
observations offline. They are not bookable offers, prices, an FX conversion
capability, or inputs to any FinPRED engine. No SDK registration, pricing
store access, outbound write method, action, or automatic start is added.

| Source | Fixed read-only request | Output contract and interpretation |
|---|---|---|
| European Central Bank | [`eurofxref-daily.xml`](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml) | `dragnet.ecb-fx-reference@1`: one dated daily snapshot, exact positive decimal quote units per EUR; indicative reference rates, not executable quotes. `complete` means the single document passed validation, not that every currency or trading session is covered. |
| Eurostat | [`tour_occ_nim`](https://ec.europa.eu/eurostat/databrowser/view/tour_occ_nim/default/table?lang=en), public [Statistics API](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction), one `lastTimePeriod=3` JSON-stat slice | `dragnet.eurostat-accommodation-nights@1`: monthly count of guest nights across EU27_2020, all residences, NACE `I551-I553` (hotels, other short-stay accommodation, campsites). This is an aggregate, not room inventory, availability, or an estimate of nightly price. `partial` means fewer than three present counts; a selected missing month has `nights:null`, not zero. Provider flags are retained. |

The exact requests are in [`feed_limits.h`](feed_limits.h). Neither response
has a continuation cursor. Dragnet does not paginate, backfill, pool snapshots,
or infer observations between returned dates. A later revision is a new
capture, not an update to an older capture.

## Terms and retention

- The ECB's [copyright and disclaimer](https://www.ecb.europa.eu/services/disclaimer/html/index.en.html#c)
  require accurate reproduction, ECB attribution, disclosure of changes and
  notice of free source availability when incorporated in sold documents.
  The ECB [discourages use in transactions](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).
- Eurostat's [reuse notice](https://ec.europa.eu/eurostat/en/help/copyright-notice)
  authorizes statistical reuse with attribution, subject to stated exceptions.
  Include dataset `tour_occ_nim` and access date when redistributing, and
  disclose modifications with the required disclaimer. Dragnet selects a
  slice and projects it, without estimating or replacing counts.
- `poll` requires `--accept-public-terms`, an operator's terms policy
  reference, and a retention policy reference. These identifiers (1–64 ASCII
  letters/digits/`._-`) are not proof of permission. The operator must review
  current terms, retain originals only under their local retention policy, and
  enforce the expiration/quota externally. Dragnet never deletes committed
  evidence or logs credentials. No credential or arbitrary URL argument exists.

## Build and explicitly start

On Linux with the existing release On1x toolchain, GNU coreutils, util-linux
`flock`, and development packages for libxml2, Jansson, and libcurl ≥ 7.85:

```sh
plugins/dragnet/build-feeds.sh

# Use a separate trusted directory, never FINPRED_HOME or its subdirectories.
mkdir -m 700 "$HOME/dragnet-evidence"
# Start only after reviewing both providers' terms and your retention policy.
plugins/dragnet/feeds poll --accept-public-terms \
  "$HOME/dragnet-evidence" provider-terms-r1 local-retention-r1 1
```

The **foreground** host launches one GET worker at a time and polls that
child's completion, up to 1–24 rounds; it never backgrounds itself or listens
on a socket. It rejects spool paths overlapping the default pricing store or
the one named by `FINPRED_HOME`. It returns nonzero if any feed was partial,
deferred or failed, but attempts the other feed independently. Its
`dragnet.feed-poll@1` JSONL
events distinguish `complete`, `partial`, `deferred` and `failed`. For
`complete` and `partial`, `detail` gives a committed capture directory
basename; otherwise it is a fixed diagnostic. SIGTERM stops and reaps the
active fetch worker and removes its staging files. An uncatchable kill may
leave a hidden `.incoming.*` directory; it is not committed evidence. Do not
promote it, and inspect or remove it only when no host owns the spool lock.

Each fetch allows HTTPS to its compiled origin and path only, verifies TLS,
does not follow redirects, ignores proxies and netrc, and runs with an empty
credential environment. It rejects unexpected encodings and media, non-200
response, truncated transfers detected by libcurl, and observed limits of
16 KiB of headers and 64 KiB of raw body. Connect/transfer timeouts are 3/10
seconds and the outer watchdog allows 15 seconds (plus 2 seconds for forced
termination). Decoding and normalization each have their own watchdog. There
is no pagination or simultaneous per-spool HTTP activity.

A file lock and a UTC-clock checkpoint per provider prevent a cooperating
operator from restarting a spool to bypass the one-hour spacing. Write the
checkpoint before requesting; wait at least an hour before another round.
Transient failures can retry in a later round, not within the same round.
On HTTP 429 or 503,
`provider_hold` in `.dragnet-public_https-PROVIDER-next` blocks further
attempts for that provider. Review the provider's retry policy before
clearing the hold with the poller stopped. This is not a machine-global quota:
use one spool and a synchronized clock. It is not a durability claim or
protection against hostile filesystem writers. The test-only HTTP transport
is omitted by default; when explicitly built, it only accepts a numeric
loopback port and never selects a live provider.

## Evidence and as-of semantics

The [plugin-local schema](contracts/dragnet.public-feed@1.schema.json) covers
both observation contracts. A capture is a private directory published
without replacing a prior capture after full validation. It contains:

- `body`: exact HTTP entity bytes (HTTP framing removed, no decompression or
  text normalization), paired with the observation's `raw_evidence`
  BLAKE3-256 and `raw_bytes`;
- `capture.csv`: exact capture handoff and policy references, hashed as
  `capture_evidence`;
- `as-of.txt`: UTC, second precision, with a single LF;
- `observation.json`: deterministic normalized bytes.

`observed_at` is Dragnet's first observation of that snapshot, equal to
`received_at`, not the provider's economic period. Acquisition stamps
receipt conservatively at the first UTC second not before full transfer.
`ingested_at` is the validation acceptance time in staging, sampled after
source decoding and successful On1x preflight, conservatively rounded up;
the archive install can occur later. A historical read cannot see a
capture earlier than ingestion, even if the date or month is much older.
The ECB supplies a reference day but no exact publication timestamp here
(`provider_updated_at:null`); Eurostat supplies its dataset update timestamp
with an offset, not the timestamp of each row's first publication. On1x
checks the update in UTC without rewriting it. It rejects future provider
dates/updates, open months, FX dates more than 7 calendar days before
receipt, Eurostat updates more than 120 elapsed days before receipt, and
any `received_at > ingested_at` or `ingested_at > as_of`. Freshness is
checked against original receipt, not the replay clock.

Offline imports take explicitly asserted capture times; never substitute a
period date or provider update for the saved receipt or ingestion date.
For a detached snapshot use `offline_snapshot` mode:

```text
dragnet.feed-capture@1
ecb,offline_snapshot,2026-11-16T10:10:00Z,2026-11-16T10:10:01Z,terms-r1,retention-r1
```

```sh
plugins/dragnet/feeds import capture.csv body 2026-11-16T10:10:01Z
plugins/dragnet/feeds verify "$HOME/dragnet-evidence/CAPTURE_BASENAME"
```

Verification stages bounded private copies, re-decodes the original body
and compares output byte-for-byte; it does not trust saved decoder output,
write to the original archive, or touch the network. Save all four
files and the pinned build. Permissions discourage accidental mutation;
hashes detect inconsistent content, not authorship, and cannot detect a
trusted operator replacing an entire bundle with a consistent fabrication.
Invalid responses and interrupted bodies are never admitted or normalized
as partial observations. Only an otherwise valid provider snapshot with
missing Eurostat counts is committed as `partial`.

## On1x and the daemon admission blocker

`dragnet.public_feeds.normalize(capture, raw, decode, as_of)` is the pure
On1x entrypoint. The trusted host regenerates the bounded
`dragnet.feed-decode@1` handoff using the standalone parser before invoking
the compiled On1x reader. `feed_decode.c` only parses syntax and pins the
fixed subset, while On1x owns the time, validity, unit, duplicate and output
semantics. The C executables are separate single-threaded processes: only
bounded bytes, diagnostics and exit statuses cross; there are no borrowed
pointers, packed structs, kernel imports, or new ABI grants.

The release MuLIB pin `49de89acbc97efbee493d6b28d02c8f64ed4f725` has no
`std.daemon`. Local upstream `5040412bf7fcce0e1e925fe63c613ddcc9681ea0`
offers `basis_daemon_ipc_dispatch` only: one synchronous byte roundtrip to
a handler in the caller using an explicitly **unsafe** local socketpair
KernelBind profile. There is no admitted `mulib.daemon` or `mulib.process`
profile and no launch, poll, stop or reap API. This is why the foreground
launcher is separate; it is not an On1x daemon implementation. The next
acceptance step is an independently admitted owned process/daemon API,
then a compiled foreground On1x host test for launch, deadline, stop/reap,
partial status and offline replay, before enabling it. No FFI bypass,
toolchain upgrade, sandbox claim, service unit, or auto-restart is provided.

## Verification

```sh
TMPDIR=/tmp MULIB_ROOT=/path/to/pinned/mulib python3 tests/check_dragnet_public_feeds.py
```

The suite builds the real On1x normalizer with the production parser and
separately enabled loopback transport. Synthetic fixtures and loopback cover
both providers, point-in-time cutoffs, missing data, offsets, stale and
duplicate data, corruption, exact-body retention, rate holds, bounded and
interrupted transfer, denied redirects, cancellation, and read-only replay.
If `strace` is available it also checks that offline verification opens no
network sockets. Provider documentation and payload shape were checked
separately; the production poller has not been run against either live
endpoint, and no end-to-end live acquisition claim is made.

Verified on Linux x86-64 with GCC 16.2.1, MuLIB
`49de89acbc97efbee493d6b28d02c8f64ed4f725`, LibStone
`b5c962721a32df18b2fb22de136c1f2ef8b6390d`, and `on1xc` SHA-256
`88428528934039ca7d0eb4064ec10e156235984aeafc3138b43ee19ee18cff20`.
The standalone C11 build used libxml2 2.15.4, Jansson 2.15.1 and libcurl
8.22.0. The public feeds, frozen CSV, Crossref and shared integration
suites exited 0; existing v1 archives and v2 hashes were unchanged.
