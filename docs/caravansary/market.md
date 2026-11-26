# Caravansary market intelligence

Caravansary separates four problems: extracting provider facts, deciding
which properties are comparable, normalizing exact-context evidence, and
recommending a price. None of these operations publishes a price, makes a
booking, or shares data with competitors.

## Authority and evidence

The market host's first execution profile uses fictional, frozen Booking and
Agoda HTML. A source declaration names a capability; it does not grant one.
The operator independently selects trusted input roots and a capture registry
that binds an operation, source, URL, fixture identity, file, and SHA-256
digest. Probe receives an exact request, a separate host authorization check
and an injected transport. The provider adapters do not make a live request
or follow a link. The existing `pilot-booking` is a distinct, explicitly
authorized Booking Demand API sandbox integration.

Probe builds an immutable `std.html` document from an Elvi document-capture
profile. A successful typed extraction is not a guarantee of completeness.
Missing, ambiguous, stale, or rejected fields are not negative inventory
evidence. A public listing price without matching stay, occupancy, taxes,
fees and terms is not a comparable offer. The canonical HTML is not a
sanitizer and is not served as active content.

Production transport would need a separately authorized provider profile,
verified TLS and egress policy, provider permissions and quotas, and a
measured extraction and retention agreement. Synthetic peer metadata
and successful local fixtures are not evidence of live TLS, current
selectors, availability, or collection rights.

## Artifact chain

* A provider observation describes a capture, the operation, the extractor
  version and the extracted facts. Capture paths are host data; they are
  not persistent provider identities. Failed extraction is an error, not an
  empty set of successful observations.
* `caravansary.discovery@1` binds a subject, discovery policy, observations
  and candidate decision evidence. Close locations or similar names are
  not proof that two listings refer to the same building. Exact provider
  IDs group corroborating facts; conflicting records remain visible.
  A physical identity link must be supplied independently by the host.
* Planning still uses the existing matrix and coverage formats. Discovery
  can supply candidate mappings, but the planner never treats an
  unverified mapping as a quote or permission to request one.
* `caravansary.position@1` is market positioning, not demand estimation. A
  recommendation needs enough distinct, fresh, exact-scope properties
  and must meet the configured floor, ceiling and movement guard. An
  abstention is a result and has no usable recommended nightly amount.
  Evidence made available after the decision time cannot enter the sample.
* First-party demand and expected-contribution inputs are separate.
  Competitor prices or observed availability alone do not identify demand
  elasticity, willingness to pay, or an expected-contribution optimum.

Digests identify canonical inputs and outputs; they do not authenticate an
operator, provider, or persistent record. Never log credentials, session
cookies, authorization headers, or credential-bearing URLs.

Local On1x consumers can import `plugins.caravansary.recommendation`.
`review(comparables, policy)` emits a `caravansary.position-review@1`
envelope binding the recommendation and both parents. `verify` recalculates
the recommendation from independently selected parents and rejects any
different envelope, even if its displayed report digest was recalculated
after tampering. Verification is exact replay, not permission to use the
data or proof that it was observed. This is a read-only review interface;
it does not add a pricing or booking gateway to Yieldcraft or Poindexter.

## Scheduled work

The host admits a named, versioned registry profile and schedules it
through Kron. It does not serialize callback addresses, credentials,
execution permissions, or application process handles. At dispatch,
current policy is checked again before Daemon supervises the fixed runner.
The consume/rearm commit happens before the child starts. A crash in
between can skip an occurrence; uncertain durability must not be blindly
retried. The result of a child process is not by itself proof of a persisted
application result.

## Qualification boundary

See [the application README](../../plugins/caravansary/README.md) for
the supported commands and worked examples. Local fixture qualification
does not verify current provider pages, economic performance, forecast
coverage on real data, or live operating permission.

The qualified scheduling profile runs a fixed, digest-bound fixture scrape.
It does not schedule arbitrary CaravanScript procedures, operate provider
quotas across installations, or automatically publish results. The pure
function API lets an On1x caller invoke a script function explicitly; it
does not execute `on_result` effects or implicitly turn a custom function
into a pricing strategy. Production transport, broad provider extraction,
automatic live identity reconciliation, shared retries and quota management,
and GUI/optimizer ingestion require additional implementation and verification.
