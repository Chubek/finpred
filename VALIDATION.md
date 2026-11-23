# Validation record

> **Archived patch-bundle validation.** This records only what the original
> bundle author ran. For current build guidance see [INSTALL.md](INSTALL.md).

## Baseline

Read-only inspection through the GitHub connector established `master` at
`6d3994a2c9caeda157592b5a556b002113ff5edf`, with a previously green
GitHub Actions workflow. The original `tests/check_dragnet_public_feeds.py`
exists and is documented as locally passing, but is absent from that workflow.

## Local patch checks

- New and modified shell scripts: `bash -n` (syntax pass).
- Python conformance test: `python -m py_compile` (syntax pass).
- GitHub Actions workflow: YAML parsing and required test steps (pass).
- ZIP content and all referenced patch paths inspected.

## Not run

The package-building container has **no network access to GitHub**, no
MuLIB/LibStone checkout, no `on1xc`, and no `jansson.pc` development package.
Consequently the new On1x dispatcher and complete feed test were **not**
compiled or executed here. The accompanying CI jobs intentionally fail on
compile/test regression instead of silently skipping them.

The compiled conformance test is a supplied regression gate, not evidence of
successful execution until a provisioned build reports success. Also not
verified: live ECB/Eurostat transfer, independently admitted storage API,
OS isolation for untrusted plugins, multi-OS portability, power-loss tests.
