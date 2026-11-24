#!/usr/bin/env python3
"""Operator conformance with frozen revisions, isolated stores and read-only replay."""
from copy import deepcopy
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from check_forecast_baselines import CONSUMER, MOVING, ROOT, SEASONAL, request, schema, snapshot


def main():
    data = json.loads((CONSUMER / "chronology.json").read_bytes())
    releases = data["snapshots"]
    cutoff = data["scoring_cutoff"]
    with tempfile.TemporaryDirectory(prefix="finpred-forecast-cli-") as tmp:
        work = Path(tmp)
        home = work / "forecast"
        pricing = work / "pricing"
        env = os.environ | {"FINPRED_FORECAST_HOME": str(home), "FINPRED_HOME": str(pricing)}

        def run(*args, rejects=None):
            proc = subprocess.run([ROOT / "bin/finpred", "forecast", *args], cwd=work, env=env,
                                  capture_output=True, text=True, timeout=30)
            if rejects:
                assert proc.returncode and not proc.stdout and rejects in proc.stderr, proc
                return None
            assert proc.returncode == 0 and not proc.stderr, proc
            return proc.stdout

        def id_of(*args):
            result = run(*args)
            assert re.fullmatch(r"[0-9a-f]{64}\n", result), result
            return result.strip()

        def put_release(name, release):
            path = work / name
            path.write_text(snapshot(release))
            return id_of("import", path)

        def catalog(name, ids):
            path = work / name
            path.write_text("".join(f"{item}\n" for item in sorted(ids)))
            return id_of("catalog", path)

        def tree():
            return {p.relative_to(home): (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
                    for p in home.rglob("*.txt")}

        def replay(identity, kind):
            before = tree()
            raw = run("replay", identity)
            assert tree() == before
            parsed = json.loads(raw)
            schema(kind).validate(parsed)
            return parsed

        invalid = work / "invalid"
        invalid.write_text("{}\n")
        run("import", invalid, rejects="invalid Eurostat")
        assert not home.exists()
        ids = {name: put_release(name, release) for name, release in releases.items()}
        assert id_of("import", work / "season") == ids["season"]
        all_releases = catalog("all", ids.values())
        actual_catalog = catalog("actual-catalog", [ids["actuals"]])
        old_catalog = catalog("old", [ids["season"], ids["january"]])
        invalid.write_text((ids["season"] + "\n") * 2)
        run("catalog", invalid, rejects="unique and sorted")
        invalid.write_text("f" * 64 + "\n")
        run("catalog", invalid, rejects="missing snapshot")
        invalid.write_text(all_releases + "\n")
        run("catalog", invalid, rejects="invalid Eurostat")

        scores = []
        for origin, moving in zip(data["origins"][1:], [180, 200], strict=True):
            req = work / origin["target"]
            req.write_text(request(origin))
            issue = id_of("issue", all_releases, MOVING, origin["cutoff"], req)
            output = replay(issue, "analysis.guest-nights-forecast")
            assert output["estimate"] == {"numerator": moving, "denominator": 1}
            assert id_of("issue", all_releases, MOVING, origin["cutoff"], req) == issue
            score = id_of("score", issue, actual_catalog, cutoff)
            scored = replay(score, "analysis.guest-nights-score")
            assert scored["actual"] - moving == 30
            assert scored["actuals_parent"] == "blake3:" + ids["actuals"]
            scores.append(score)
            run("score", issue, actual_catalog, origin["cutoff"], rejects="no release visible")

        march = data["origins"][1]
        req = work / march["target"]
        season = id_of("issue", all_releases, SEASONAL, march["cutoff"], req)
        output = replay(season, "analysis.guest-nights-forecast")
        assert output["estimate"]["numerator"] == 110
        unknown = id_of("issue", old_catalog, MOVING, march["cutoff"], req)
        assert replay(unknown, "analysis.guest-nights-forecast")["state"] == "unknown"
        unknown_score = id_of("score", unknown, actual_catalog, cutoff)
        assert replay(unknown_score, "analysis.guest-nights-score")["state"] == "unknown"

        conflict = deepcopy(releases["february"])
        conflict["values"]["2024-01"] = 999
        conflict_id = put_release("conflict", conflict)
        tied = catalog("tie", [*ids.values(), conflict_id])
        before = tree()
        run("issue", tied, MOVING, march["cutoff"], req, rejects="ambiguous release vintage")
        assert tree() == before

        # A newer complete revision is chosen after it becomes visible. The
        # original issuance stays tied to its own cutoff and catalog.
        revised = deepcopy(releases["january_revision"])
        revised["values"] = releases["february"]["values"] | revised["values"]
        latest = catalog("latest", [*ids.values(), put_release("revised", revised)])
        old_issue = id_of("issue", latest, MOVING, march["cutoff"], req)
        assert replay(old_issue, "analysis.guest-nights-forecast")["estimate"]["numerator"] == 180
        late = "2024-02-25T00:00:00Z"
        late_req = work / "late"
        late_req.write_text(request(march, issued_at=late))
        late_issue = id_of("issue", latest, MOVING, late, late_req)
        estimate = replay(late_issue, "analysis.guest-nights-forecast")["estimate"]
        assert Fraction(estimate["numerator"], estimate["denominator"]) == Fraction(570, 3)

        plan = work / "plan"
        header = f"{MOVING},2024-02,2024-03-01T00:00:00Z,2024-03,2024-04,{cutoff}\n"
        plan.write_text(header + "\n".join(reversed(scores)) + "\n")
        run("holdout", plan, rejects="holdout rejected")
        plan.write_text(header + "\n".join(scores) + "\n")
        report = id_of("holdout", plan)
        output = replay(report, "analysis.guest-nights-holdout")
        assert (output["expected"], output["scored"], output["unknown"]) == (2, 2, 0)
        assert output["mae"] == {"numerator": 30, "denominator": 1}
        assert output["bias"] == {"numerator": -30, "denominator": 1}

        # Read-only bounded audit of immutable forecast issue, score and
        # holdout archives, across three kinds of replay.
        audit_ids = sorted({*scores, report, season, unknown, unknown_score})
        audit_path = work / "audit.ids"
        audit_path.write_text("".join(f"{item}\n" for item in audit_ids))
        before = tree()
        audit = run("audit", audit_path)
        assert tree() == before
        result = json.loads(audit)
        schema("analysis.forecast-audit", ROOT / "contracts").validate(result)
        assert result["verified"] == len(audit_ids)
        assert result["pricing_input"] is False and result["read_only"] is True
        assert audit == json.dumps(result, separators=(",", ":")) + "\n"
        assert run("audit", audit_path) == audit

        def reject_audit(content, message):
            invalid.write_text(content)
            snapshot_before = tree()
            run("audit", invalid, rejects=message)
            assert tree() == snapshot_before

        reject_audit(audit_ids[0].upper() + "\n", "invalid canonical identity")
        reject_audit(audit_ids[0] + "\n" + audit_ids[0] + "\n", "strictly increasing")
        reject_audit("".join(x + "\n" for x in reversed(audit_ids)), "strictly increasing")
        reject_audit("f" * 64 + "\n", "missing snapshot")
        reject_audit("".join(f"{i:064x}\n" for i in range(129)), "outside size profile")
        one = work / "single-audit.ids"
        one.write_text(audit_ids[0] + "\n")
        assert json.loads(run("audit", one))["verified"] == 1

        for release in releases:
            (work / release).unlink()
        req.unlink()
        plan.unlink()
        assert replay(report, "analysis.guest-nights-holdout") == output
        assert run("audit", audit_path) == audit
        obj = home / "artifacts" / f'blake3-{ids["actuals"]}.txt'
        obj.write_bytes(obj.read_bytes() + b"\n")
        before = tree()
        run("replay", report, rejects="snapshot digest mismatch")
        run("audit", audit_path, rejects="snapshot digest mismatch")
        assert tree() == before
        assert not pricing.exists()
    print("forecast_cli_ok=true revisions=point_in_time holdout=replayed pricing_store=untouched")


if __name__ == "__main__":
    main()
