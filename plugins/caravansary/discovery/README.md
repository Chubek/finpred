# Native discovery and comparison inputs

These libraries consume immutable `planning.json` values. They do not read
captures, open URLs, authorize acquisition, publish prices, or infer
availability. The host selects trusted inputs and owns policy, grants, and
identity links separately.

## Listing discovery

- `Discovery.run(subject, policy, facts)` accepts normalized listing facts.
  `subject` requires string `id` and `name`; `type`, `address`, `latitude` and
  `longitude` are optional. A listing requires `provider` (`booking` or `agoda`),
  opaque `provider_property_id`, and `name`; it may additionally supply `type`,
  `address`, paired coordinates, an informational `url`, and `evidence_ref`.
  It must not contain offers. Coordinates accept decimal strings or JSON
  numbers and are emitted as strings with six decimal places. Bounds are
  checked before quantization, against the exact decimal string or the
  planning decoder's canonical numeric value. Longitude at a pole is
  canonicalized to zero and +180° is equivalent to −180°. Distance is
  spherical, using mean Earth radius and rounding to the nearest metre—not
  route distance.
- `Discovery.from_observations(subject, policy, observations)` accepts an
  array of successful W2 `provider-observation/v1` **fictional frozen HTML**
  envelopes. It carries capture provenance (`fixture_evidence`) and excludes
  unnamed listings (`unusable_listings`). A missing half-coordinate cannot
  support distance. Error envelopes are rejected, not reinterpreted as empty
  successful searches. The adapter's sparse prices and amenities are not
  evidence of comparability or demand.
- Policy requires integer `radius_m`; optional `min_score` defaults to 1,
  `max_candidates` defaults to 256, and `excluded_types` and
  `excluded_provider_ids` default to empty arrays. An excluded provider identity
  is `{provider, provider_property_id}`. A batch admits at most 256 listing
  facts, and the candidate limit itself accepts 1–1024 to match script syntax.

An eligible candidate scores `floor(70 × (radius_m − distance_m) / radius_m)`
plus 30 for an exact normalized property-type match. Out-of-radius, unknown
distance, explicit exclusions, conflicting listing facts, and possible subject
matches remain visible but cannot be used as competitors. `max_candidates`
selects by descending score, then ascending candidate ID. Beyond-limit
candidates are retained with their ranks and the reason `candidate_limit`.

The candidate ID hashes a versioned tuple of the exact provider and opaque
provider-local ID. Identical canonical facts collapse, and independent
evidence references are retained. Inconsistent facts for one ID or two IDs
claiming the same exact URL on one provider are excluded rather than merged.
Matching names plus matching addresses or locations within 100 m yield only
advisory corroboration, never automated cross-provider linking. Label matching
folds ASCII case and collapses whitespace; it does not guess transliterations
or remove punctuation. Candidate order is by ID, and `discovery_id` hashes
canonical artifact bytes excluding `discovery_id` itself.

## Planner and pricing handoff

`Projection.competitors(discovery, guests, verified_links)` produces a legacy
`caravansary.competitors@1` document. A trusted host can provide explicit
`{candidate_id, property_id}` links to eligible candidates. Only those links
verify provider mappings and place candidates into a shared physical property
ID; multiple provider IDs on one physical property for the same provider are
rejected. Unlinked properties are under the reserved `candidate:` namespace
with unverified mappings, which the original planner marks unsupported. No
URLs are projected into the plan. A verified identity is **not** a grant to
scan, read, connect to, or publish anything.

`Projection.observation(discovery, verified_links, planner_row, supplied)`
validates and canonically timestamps an already supplied `priced` coverage
observation. The host supplies an actual pending planner row, and the
observation must match its cell, verified provider identity, and exact request
context. The discovery artifact cannot create observation rows or establish
unavailability.

`Comparables.select(discovery, verified_links, planner_row, observation,
qualification)` returns a result with a canonical **array** accepted by
`Price.position`. It preserves the host physical property ID, exact source
and observation IDs, canonical UTC clocks, positive integer minor units, and
the full `scope` (including the canonical guest allocation object). Only
complete, explicit available quotes with disclosed meal and cancellation,
included taxes/fees and a reported `stay_total` or `nightly_average` qualify.
There is no unit, basis or currency conversion. `qualification` must be
host-selected `fixture` or `observed`; a fixture discovery cannot be relabeled
as observed market evidence. Multiple result arrays can be combined for the
pricing guardrails to handle exact scope, freshness and physical-property
deduplication. An empty result array means no qualifying quotes, not sold out.

## Checks

Run `sh plugins/caravansary/discovery/check.sh` with the pinned `on1xc`; set
`ON1XC` explicitly if it is installed elsewhere. The check uses Clang and an
isolated W3 output, links `planning/host.c` and `stdlib/geo/geodesy.c` with
`-lcrypto -lm`, and exercises only fictional offline inputs.
