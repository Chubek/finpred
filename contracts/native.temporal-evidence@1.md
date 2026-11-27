# Native temporal evidence v1

This host-only wire contract defines a frozen revision catalog and a local
point-in-time commit. It is separate from FinPRED run manifests and the
guest-night forecast vintage format. Neither record is an On1x admission or
a provider authentication statement.

## Canonical bytes

All literals below are ASCII. Each line ends with exactly one LF, including
the last line. There are no blank lines, spaces, CRs, or optional fields.
Integers are unsigned decimal, with no leading zeros unless the integer is
zero. `H` is exactly 64 lowercase hex digits of the BLAKE3-256 digest of
the referenced bytes, including any trailing LF. Both record types live in
`artifacts/blake3-<H>.txt`. Do not mix writers using the legacy reservation
protocol and writers using this native publication protocol in one namespace.

Catalog:

```text
finpred-temporal-catalog@1
<key>,<effective>,<known>,<revision>,<state>,<H>
```

There are 0–64 catalog rows, strictly increasing by the tuple shown (numeric
fields numerically; state and digest lexically). `key` is a nonzero `uint64`,
`effective` and `known` are nonnegative Unix seconds up to `INT64_MAX`, and
`revision` is a `uint32`. `state` is `present` or `withdrawn`. Each row names
one NUL-free source object of up to 2 MiB. Source bytes are opaque: for
example, an application may encode numeric zero as present, but this
contract does not prescribe a numeric encoding. A withdrawal also names its
evidence. Identical rows are forbidden, while multiple rows at the same rank
with different state or evidence can be represented.

Commit:

```text
finpred-temporal-commit@1
catalog=<H>
effective=<effective cutoff>
knowledge=<knowledge cutoff>
selection=<key>,missing
selection=<key>,<state>,<effective>,<known>,<revision>,<H>
```

There are 1–32 `selection` lines in strictly increasing numeric key order.
Each key has exactly one line. The two cutoff values are independent,
inclusive, and use the same Unix-seconds bounds as catalog times. A row
participates only if its effective time and knowledge time both pass. Rank
eligible rows of each key by greatest `(effective, known, revision)`, in that
order. Two different rows at the winning rank are an error, even if they
have the same state and only the evidence digest differs. Nonwinning ties
do not block selection. A winning withdrawal suppresses earlier rows and
retains its own evidence. With no eligible row, the line is `missing` and
has no evidence fields. This ranking is **not** the guest-night resolver.

## Publish, replay, recover

1. A trusted host stages the catalog and all its direct source objects in the
   protected native store. Publication parses the catalog and computes the
   commit bytes. It verifies the digest and obtains durable installation of
   every distinct named source object, including unselected and future
   objects; then it verifies and syncs the catalog. Underlying installs
   compare exact bytes and sync the existing inode and destination directory.
2. Only then may publication install the commit. Its content ID binds the
   exact catalog, cutoffs, requested keys, and selected evidence; even an
   unselected catalog change therefore changes the commit ID. No final
   name is deleted on failure. A failed call can leave a visible commit (for
   instance, when its directory sync failed after the link). An ID, or a
   visible commit, is not a success receipt.
3. Replay starts with a **separately trusted** commit ID, validates its hash,
   recomputes the canonical bytes, and checks the entire direct closure. It
   performs no installation or sync, never promotes the commit, and cannot
   certify an earlier sync. A self-consistent replacement catalog and commit
   are not evidence against a different trusted ID.
4. To recover a visible commit, explicitly resume from the independently
   pinned ID: verify identical bytes, then re-sync the entire direct closure
   in the original order, ending at the commit. If the commit is missing,
   resubmit the original publish request rather than promoting a stage or
   discovering commits by directory scan.

The temporal API uses one native object read at a time and bounded record
and query state. Each operation checks at most 64 distinct sources; source
content is not recursively traversed as another commit. The supported scope
is the existing native store's protected Linux namespace and cooperating
writers. The API does not establish actual availability, the truth or
completeness of a catalog, creator or provider authenticity, retention
rights, or persistence after a remount or power loss. The process tests
observe live-mount behavior.
