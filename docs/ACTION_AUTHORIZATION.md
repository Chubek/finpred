# Offline action authorization design

**Status: design only. Disabled by default and not implemented.** No CLI flag,
plugin manifest, worksheet, or strategy can enable execution. The current
CLI and SDK continue to deny execution; recommendation, analysis, simulation
and replay do not dispatch external effects. Local artifact publication is
not external action approval. This design admits no connector, credential
source, execution worker, or production validation.

## Records and trust

Keep the action control plane separate from the graph, SDK and run formats.
Only a trusted host may prepare an intent from a semantically verified
recommendation. Preparing and reviewing intent files is offline.

- **Intent:** A versioned, canonical, bounded record binds the verified run
  and recommendation IDs, exact action kind, environment and target identity,
  typed parameters and units, business operation identity, policy ID and
  revision, and a validity window. The reviewer sees those exact fields,
  including any account, numeric limits and expiry. Unknown fields, ambiguous
  encodings and implicit defaults fail closed. Use a domain-separated digest
  of the canonical bytes to bind subsequent decisions; that digest establishes
  integrity, not authority.
- **Human decision:** An authenticated approval or rejection binds the exact
  intent digest, approver identity, decision and validity window. Approver
  keys or identities, scopes and separation-of-duties rules come from
  independently provisioned host policy, not the intent or a package. An
  approval is not transferable to another target, account, environment,
  parameter, policy revision or run. Deny if the current policy/clock or
  revocation status cannot be verified. Rejection or revocation does not undo
  an action already dispatched.
- **Audit:** Record intent, decisions, revocation, claim, dispatch outcome,
  and reconciliation as distinct immutable records. Bind each to its
  predecessors and record actor, time, policy revision and correlation IDs.
  Do not store credentials in records. Production would require authenticated
  writers, protected durable state, and auditable access; local content
  hashes and the current private store are not a substitute.

## Idempotency and ambiguous outcomes

The host assigns a stable operation key scoped to the tenant, target,
environment and business operation. Transport retries and renewed approvals
reuse that key. Bind it to the canonical effect payload (kind, target and
typed parameters, excluding approval and policy metadata). A different
effect payload under the same key is a conflict, not a new attempt; a new
semantic operation needs a new key and approval. Never let strategy code
choose or rotate operation keys.

Before any future dispatch, a durable host gateway would atomically check
the current approval, policy, expiry and revocation and claim the operation
key. A revocation committed before the claim denies it; a revocation after
claim must surface as potentially in flight, not as guaranteed cancellation.
Repeated claims must return the existing outcome or indicate in-flight/
unknown without issuing a second effect. A dispatch claim is not evidence
that the effect happened, nor is a process timeout evidence that it did not.

An ambiguous outcome stays unresolved until independently reconciled.
Never blindly retry, mint a replacement key, or infer success from replay.
A future connector may retry only if it can safely reuse the same downstream
idempotency key under a verified scope/retention guarantee, or if authoritative
reconciliation proves the prior attempt had no effect and no stale worker
can still dispatch it. Otherwise stop and require manual reconciliation.
This design does not promise exactly-once effects across systems.

## Offline conformance before considering enablement

Use a recording sink and test-only approver identities only in an isolated
test harness. Assert no dispatch for recommendation, analysis, simulation or
replay; missing, invalid, revoked or expired decisions; untrusted approvers;
stale policy; and any tampered field or environment mismatch. Assert that
concurrent duplicate claims dispatch once in the harness, changed bytes under
the same operation key fail, and a lost reply stays unknown without blind
retry. These tests would check the protocol logic, not prove durable or live
behavior. Production admission would separately require independent review of
the identity, policy, durable claim/audit store, worker isolation and actual
connector reconciliation guarantees.
