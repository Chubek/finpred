#!/usr/bin/env python3
"""Check compiled named policy runs against the frozen five-property sample."""
import json
import subprocess
import tempfile
from pathlib import Path

from check_store import ENV, ROOT, invoke, replay, tree
from validate_runtime_json import validate


# Gross whole-stay cents: 30000, 33000, 35000, 38000, 40000; 2 nights;
# 26 days' lead. Expected target, selected percentile, intended, final, reason.
CASES = {
    "value-p40": (4000, 4000, 17100, 17100, "target_percentile"),
    "balanced-p55": (5500, 5500, 17800, 17800, "target_percentile"),
    "premium-p75": (7500, 7500, 19000, 19000, "target_percentile"),
    "lead-linear": (5011, 4000, 17507, 17100, "lower_percentile_shortcut"),
    "lead-quadratic": (4292, 4000, 17217, 17100, "lower_percentile_shortcut"),
}


def failure(home, diagnostic, *args, strategy):
    proc = subprocess.run([ROOT / "bin/finpred", *args], cwd=ROOT, capture_output=True, timeout=60,
                          env={**ENV, "FINPRED_HOME": str(home), "FINPRED_STRATEGY": str(strategy)})
    if (proc.returncode <= 0 or diagnostic not in proc.stdout + proc.stderr
            or b"recommendation_minor=" in proc.stdout or b"replay_ok=true" in proc.stdout):
        raise ValueError(f"unexpected {args} failure: {proc}")


def check(home, profile, expected, policy=None, **inputs):
    if policy is None:
        policy = ROOT / "strategies" / f"{profile}.ottomat"
    summary = invoke(home, "run", strategy=policy, **inputs)
    values = dict(line.split("=", 1) for line in summary.decode("ascii").splitlines())
    run_id = values["run_id"]
    target, selected, intended, price, reason = expected
    if (values["published"], values["reason"], int(values["recommendation_minor"])) != ("false", reason, price):
        raise ValueError(f"{profile}: {values}")
    manifest = home / "runs" / f"{run_id}.txt"
    version, _, _, _, strategy, rec, trace = manifest.read_text().strip().split(",")

    def artifact(digest):
        return (home / "artifacts" / f"blake3-{digest}.txt").read_bytes()

    if version != "finpred-run@2" or artifact(strategy) != policy.read_bytes():
        raise ValueError(f"{profile}: invalid manifest or strategy snapshot")
    obj = json.loads(artifact(rec))
    provenance = obj["metadata"]["provenance"]
    if provenance["strategy"] != "yieldcraft.percentile@1" or provenance["strategy_digest"] != f"blake3:{strategy}":
        raise ValueError(f"{profile}: JSON family or digest differs")
    data = obj["data"]
    if (data["intended_percentile_bps"], data["selected_percentile_bps"], data["intended_minor"],
            data["price_minor"], data["reason"]) != expected or data["published"] is not False:
        raise ValueError(f"{profile}: {data}")
    policy_line = f"strategy=yieldcraft.{profile}@1"
    for digest, lines in ((run_id, [policy_line, f"raw_strategy={strategy}"]),
                          (trace, [policy_line, f"strategy_blake3={strategy}", f"lineage_blake3={run_id}",
                                   f"intended_bps={target}", f"selected_bps={selected}",
                                   f"candidate_nightly_minor={17100 if selected == 4000 else intended}"])):
        if not set(lines).issubset(artifact(digest).decode("ascii").splitlines()):
            raise ValueError(f"{profile}: {digest} lacks expected pricing evidence")
    replay(home, summary)  # All live input paths are absent; compare bytes and store metadata.
    return run_id


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-profiles-") as tmp:
        root = Path(tmp)
        home = root / "store"
        ids = {check(home, name, expected) for name, expected in CASES.items()}
        if len(ids) != len(CASES):
            raise ValueError("named strategies collided on identical inputs")
        # Same validated declaration under a different name, different bytes.
        # Pricing follows contents; run identity includes the exact bytes.
        alias = root / "value-p40.ottomat"
        premium = (ROOT / "strategies/premium-p75.ottomat").read_bytes()
        for content in (premium.replace(b"\n", b"\r\n"), premium.replace(b"ottmat ", b"ottomat ", 1)):
            alias.write_bytes(content)
            identity = check(home, "premium-p75", CASES["premium-p75"], policy=alias)
            if identity in ids:
                raise ValueError("strategy byte change reused an existing run ID")
            ids.add(identity)
        # Tighten the movement limit around the 17500 previous rate. The lead
        # shortcut still selects P40 (17100) before the movement floor (17300).
        valuation = root / "tight.csv"
        raw = (ROOT / "fixtures/valuation.csv").read_bytes()
        valuation.write_bytes(raw.replace(b",5000,500\n", b",200,500\n"))
        run_id = check(home, "lead-linear", (5011, 4000, 17507, 17300, "guardrail_adjustment"),
                       valuation=valuation)
        validate(home)
        # Only legacy declarations can ever enter the v1 calculation.
        manifest = home / "runs" / f"{run_id}.txt"
        manifest.write_bytes(manifest.read_bytes().replace(b"finpred-run@2,", b"finpred-run@1,", 1))
        before = tree(home)
        failure(home, b"v1 requires the legacy scenario strategy", "replay", run_id, strategy=root / "absent")
        if tree(home) != before:
            raise ValueError("rejected v1 replay modified the store")
        # A valid-looking filename must not admit unknown policy or graph contents.
        bad = root / "premium-p75.ottomat"
        valid = (ROOT / "strategies" / bad.name).read_bytes()
        for invalid in (valid.replace(b"premium-p75", b"premium-p76"),
                        valid.replace(b"target_bps 7500", b"target_bps 7400"),
                        valid.replace(b"gate pricing.recommendation@1", b"gate pricing.valuation@1")):
            bad.write_bytes(invalid)
            failure(root / "denied", b"invalid graph or incompatible strategy", "run", strategy=bad)
        if (root / "denied").exists():
            raise ValueError("invalid strategy created a store")
    print("strategy_profiles_ok=true profiles=5")


if __name__ == "__main__":
    main()
