# Read-only batch audit of archived forecasts

Run `./bin/finpred forecast audit audit.ids` to verify a sorted list of
one to 128 existing issuance, score or holdout archive IDs. The file must
contain one lowercase 64-character BLAKE3 hex ID plus LF per line, in
strict ascending order, with no duplicates.

The audit invokes the existing replay verifier for each archive, so all
frozen sources and original model/score/holdout outputs must still match
their recorded identities. It emits one canonical JSON
`analysis.forecast-audit@1` record without publishing any new artifact.

`input_digest` is BLAKE3 of the exact ID-list bytes. `evidence_digest`
is BLAKE3 of the ASCII text formed by this header and one line for each
archive: `finpred.forecast-audit-evidence@1\n` followed by
`<archive-id>:<BLAKE3-of-replayed-output>\n`.

Malformed IDs and sorting are rejected before replay. Missing or corrupted
archives fail the entire audit, without partial success output. Replaying
is still subject to the private cooperating-writer store's limitations;
this witness does not authenticate providers, enable price publication,
or certify power-loss durability.

CI exercises the compiled forecast CLI through
`tests/check_forecast_cli.py`. No archived pricing, scalar, or forecasting
run format is modified.
