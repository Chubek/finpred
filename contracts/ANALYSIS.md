# Analysis-only contracts

`analysis.guest-nights-monthly@1` is a projection of one frozen Eurostat
`tour_occ_nim` snapshot (`EU27_2020`, `I551-I553`, `TOTAL`). It is measured in
guest nights, has no currency, and is never a pricing input. This is a new
contract, not a migration or rewrite of Dragnet or pricing archives.

`core.guest_nights.project(snapshot, expected_parent, cutoff)` takes the
canonical Dragnet snapshot bytes and a BLAKE3 ID from trusted host lineage.
It checks the exact parent bytes, fixed profile, size, dimensions, dates and
presence semantics. The snapshot's original digest is recorded in `parent`;
its raw evidence, capture metadata, and policy references remain in that
parent. A digest does not authenticate Eurostat, and this transform does not
perform acquisition or verification of the original raw/capture artifacts.

Months are ordered and unique. `unknown` with `nights: null` is not zero.
Unlisted months remain absent; no row is filled or inferred. A snapshot is
`available` only for three contiguous, numeric observations; otherwise it is
`partial`. Economic months must be finished by the provider update. Provider
update, observation, receipt, ingestion, the source's original `as_of` and
the consumer's cutoff remain distinct. The legacy Dragnet source records
receipt as its observation timestamp; the projection retains that meaning
and rejects sources normalized with a later `as_of` than the requested cutoff.

For replay, `core.guest_nights.verifies` reruns the transform on the frozen
parent and checks exact output bytes. The schema describes shape, not
temporal/lineage validity. Version 1 accepts only the canonical version 1
Eurostat snapshot profile; a future profile requires an explicitly versioned
validator or transform. ECB references are not convertible by this contract.
