# FinPRED integration requirements

The six workstreams start from `85b8a0b`. A workstream is accepted for the
behavior its end-to-end tests exercise, not for a planned API or schema alone.

## Contract boundaries

| Producer | Consumer boundary |
| --- | --- |
| Yieldcraft demand | Publish demand in explicit units at supported price/currency points, with training/evidence and model identity. Distinguish fitted means, parameter uncertainty and predictive distributions; an observational fit does not authorize a causal claim. |
| Forecasting | Bind forecast targets to an origin and horizon, series unit/frequency, point-in-time input vintages and model identity. Keep unobserved, numeric zero, and unavailable intervals distinct. Evaluation must not let later releases enter training or model selection. |
| Automat, Ottomat, SDK | Resolve only declared compatible ports and trusted handlers. Bind operation/version, arguments, ordered evidence, executable or source identity (label which), configuration and relevant model identities. Replay validates those inputs and recomputes without acquisition or writes. |
| Yieldcraft optimization and Poindexter | Consume typed evidence, not scraped CLI output. Require compatible units, cutoffs and support. Show unknowns and unsupported assumptions, and do not imply that a recommendation, scenario or observation caused an economic outcome. |
| Dragnet and storage | Treat access permission, provider authentication, content integrity and acquisition time as separate facts. Keep verified recovery, synchronization success and power-loss durability separate. External financial execution remains disabled. |

Keep existing versions, readers and fixture bytes. Add a new version for an
incompatible schema, representation or semantic change. Document byte
canonicalization, exact number representation, identity boundaries, admission
conditions and resource limits. Files that differ only because of temporary
paths must not create different identities. A content digest is not a
signature or an authorization. Keep policy and orchestration in On1x and use
MuLIB for reusable numerical kernels; host-specific operations must have a
narrow, explicit boundary.

## Merge gates

1. Review each worker diff and focused positive and negative tests before
   integrating it. Wire mandatory checks into the relevant existing suite.
2. Check that both dependency gitlinks, historical golden fixtures and
   archive semantics remain intact. Do not remove checks, accept arbitrary
   failures, or mark hard requirements optional to turn a job green.
3. Build the application and run all six suites, the compiler/GrammarEmbed
   integration, native storage tests, the Poindexter viewport and real GUI
   checks, and the real offline sandbox. Test packaging from independent
   output directories when changing release assembly. Record unsupported
   hosts separately from test passes.
4. Report the exact revision, toolchain, test commands and results. Hosted
   CI, local CI-equivalent commands, loopback/offline evidence, and real
   provider or hardware results are different kinds of evidence.

The [hosted baseline](https://github.com/Chubek/finpred/actions/runs/45479500972)
had passing Pricing, Forecasting, Plugins, and Storage jobs. Compiler and
Security failed at `make test-compiler` and `make test-security` respectively.
The upstream compiler/GrammarEmbed step passed. Public annotations identify
the failed steps but not their detailed diagnostics; a local result does not
retroactively change those hosted conclusions.
