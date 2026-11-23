#!/usr/bin/env python3
"""Compile the two pure models and compare them to a point-in-time Fraction oracle."""
from copy import deepcopy
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / "tests/forecast_baseline_consumer"
PACKAGE = ROOT / "plugins/forecast_baselines"
MODEL_FILE = PACKAGE / "source/forecast_baselines/model.on1x"
MOVING = "forecast.moving-average-3@1"
SEASONAL = "forecast.seasonal-naive-12@1"
SYNTHETIC_EVIDENCE = "blake3:" + "0" * 64


def serialized(doc):
    return json.dumps(doc, separators=(",", ":")) + "\n"


def snapshot(release):
    values = release["values"]
    return serialized({
        "format": "dragnet.eurostat-accommodation-nights@1",
        "source": "Eurostat", "source_series": "tour_occ_nim",
        "provider_updated_at": release["updated"], "geography": "EU27_2020",
        "activity": "I551-I553", "residence": "TOTAL", "unit": "guest_nights",
        "status": "complete" if len(values) == 3 and None not in values.values() else "partial",
        "mode": "offline_snapshot", "observed_at": release["received"], "received_at": release["received"],
        "ingested_at": release["ingested"], "as_of": release["ingested"],
        "terms_ref": "synthetic", "retention_ref": "synthetic",
        "raw_evidence": SYNTHETIC_EVIDENCE, "capture_evidence": SYNTHETIC_EVIDENCE,
        "raw_bytes": 1, "pricing_input": False,
        "observations": [{"period": p, "nights": v, "provider_flag": None} for p, v in values.items()],
    })


def request(origin, **changes):
    return serialized({"issued_at": origin["issued"], "target_month": origin["target"], "horizon_months": 1} | changes)


def shift_month(period, delta):
    year, month = map(int, period.split("-"))
    y, m = divmod(12 * year + month - 1 + delta, 12)
    return f"{y:04}-{m + 1:02}"


def visible(releases, cutoff):
    values = {}
    for release in sorted(releases.values(), key=lambda r: r["ingested"]):
        if release["ingested"] <= cutoff:
            values.update(release["values"])
    return values


def oracle(model, origin, values):
    months = ([shift_month(origin["issued"][:7], -i) for i in range(1, 4)] if model == MOVING
              else [shift_month(origin["target"], -12)])
    selected = [values.get(m) for m in months]
    return None if None in selected else Fraction(sum(selected), len(selected))


def schema(name):
    doc = json.loads((PACKAGE / f"contracts/{name}@1.schema.json").read_bytes())
    Draft202012Validator.check_schema(doc)
    return Draft202012Validator(doc, format_checker=FormatChecker())


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    chronology = json.loads((CONSUMER / "chronology.json").read_bytes())
    releases = chronology["snapshots"]
    origins = chronology["origins"]
    actuals = releases["actuals"]
    source = MODEL_FILE.read_text()
    request_schema = schema("analysis.guest-nights-forecast-request")
    forecast_schema = schema("analysis.guest-nights-forecast")
    with tempfile.TemporaryDirectory(prefix="finpred-forecast-baselines-") as tmp:
        work = Path(tmp)
        exe = work / "consumer"
        build_env = os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, mulib / "on1x/tools/on1x-build.py", CONSUMER / "main.on1x",
                        "--backend", "c11", "--on1xc", compiler, "--mulib-root", mulib,
                        "-I", ROOT / "source", "-I", PACKAGE / "source", "-o", exe],
                       env=build_env, cwd=work, check=True, timeout=90)
        run_dir = work / "offline"
        run_dir.mkdir()
        child_env = build_env | {"CODE_BYTES": source, "FINPRED_HOME": str(run_dir / "absent")}
        counts = {"accepted": 0, "rejected": 0}

        def run(case, rc=0, **inputs):
            proc = subprocess.run([exe], env=child_env | {"CASE": case} | inputs,
                                  cwd=run_dir, capture_output=True, timeout=5)
            assert proc.returncode == rc and not proc.stderr, (case, rc, proc)
            assert bool(proc.stdout) != bool(rc) and not list(run_dir.iterdir()), (case, proc)
            if rc:
                counts["rejected"] += 1
            elif case not in ("digest", "project"):
                counts["accepted"] += 1
            return proc.stdout.decode()

        def digest(text):
            result = run("digest", SNAPSHOT=text).strip()
            assert result.startswith("blake3:") and len(result) == 71
            return result

        def args(model, origin, release):
            raw = snapshot(release)
            request_bytes = request(origin)
            request_schema.validate(json.loads(request_bytes))
            return {"MODEL": model, "CUTOFF": origin["cutoff"], "SNAPSHOT": raw,
                    "PARENT": digest(raw), "REQUEST": request_bytes}

        def check(payload, expected, *, origin):
            out = run("forecast", **payload)
            doc = json.loads(out)
            forecast_schema.validate(doc)
            got = doc["estimate"]
            estimate = (None if expected is None else
                        {"numerator": expected.numerator, "denominator": expected.denominator})
            assert got == estimate and (got is None or all(type(n) is int for n in got.values())), (out, estimate)
            assert doc["model"] == payload["MODEL"]
            assert doc["code_digest"] == digest(source)
            assert doc["policy_digest"] != doc["code_digest"] and len(doc["policy_digest"]) == 71
            assert doc["training"] == digest(run("project", **payload))
            assert doc["kind"] == "analysis.guest-nights-forecast" and doc["version"] == 1
            assert doc["pricing_input"] is False and doc["currency"] is None
            assert doc["unit"] == "guest_nights" and doc["uncertainty"] == "unavailable"
            assert doc["state"] == ("unknown" if expected is None else "available")
            assert doc["reason"] == ("insufficient_evidence" if expected is None else None)
            assert doc["horizon_months"] == 1
            assert (doc["issued_at"], doc["training_cutoff"], doc["target_month"]) == (
                origin["issued"], origin["cutoff"], origin["target"])
            return doc, out

        scoring = {"cutoff": chronology["scoring_cutoff"], **{k: origins[-1][k] for k in ("issued", "target")}}
        actual_doc = json.loads(run("project", **args(MOVING, scoring, actuals)))
        observed_actuals = {row["period"]: row["nights"] for row in actual_doc["observations"]}
        expected_walk = {MOVING: (170, 180, 200), SEASONAL: (100, 110, 120)}
        expected_holdout = {MOVING: (30, 900), SEASONAL: (105, 11050)}
        policies = set()
        evidence = []
        for model in (MOVING, SEASONAL):
            holdout = []
            for i, origin in enumerate(origins):
                training_key = origin["training"] if model == MOVING else "season"
                payload = args(model, origin, releases[training_key])
                expected = oracle(model, origin, visible(releases, origin["cutoff"]))
                assert expected == expected_walk[model][i], expected
                doc, out = check(payload, expected, origin=origin)
                assert out == run("forecast", **payload)
                evidence.append((model, origin["target"], digest(out)))
                policies.add(doc["policy_digest"])
                error = expected - observed_actuals[origin["target"]]
                if origin["split"] == "holdout":
                    holdout.append(error)
                if i == 1:
                    # The later revision and roll-forward snapshot are not visible at this origin.
                    for late in ("january_revision", "march", "actuals"):
                        run("forecast", rc=13, **args(model, origin, releases[late]))
                    assert out == run("forecast", **payload)
            mae = sum(map(abs, holdout)) / len(holdout)
            mse = sum(e * e for e in holdout) / len(holdout)
            assert len(holdout) == 2 and (mae, mse) == expected_holdout[model]
        assert len(policies) == 2

        february = origins[1]
        training = releases["february"]
        exact = february | {"cutoff": training["ingested"]}
        check(args(MOVING, exact, training), Fraction(180), origin=exact)
        before = exact | {"cutoff": "2024-02-10T12:00:01Z"}
        run("forecast", rc=13, **args(MOVING, before, training))
        for edits, estimate in (
            ({"2024-01": 191}, Fraction(541, 3)),
            ({"2024-01": 0}, Fraction(350, 3)),
            ({"2024-01": None}, None),
            ({"2023-11": 999999999999, "2023-12": 999999999999, "2024-01": 999999999998},
             Fraction(2999999999996, 3)),
        ):
            release = training | {"values": training["values"] | edits}
            assert oracle(MOVING, february, release["values"]) == estimate
            check(args(MOVING, february, release), estimate, origin=february)
        release = deepcopy(training)
        release["values"].pop("2023-12")
        check(args(MOVING, february, release), None, origin=february)
        season = releases["season"]
        partial = season | {"values": {"2023-02": None, "2023-03": 0}}
        check(args(SEASONAL, february, partial), Fraction(0), origin=february)
        check(args(SEASONAL, february, training), None, origin=february)

        base = args(MOVING, february, training)
        run("forecast", rc=11, **(base | {"PARENT": SYNTHETIC_EVIDENCE}))
        run("forecast", rc=1, **(base | {"MODEL": "forecast.moving-average-3@2"}))
        run("budget", rc=4, **base)
        for edits in ({"target_month": "2024-02"}, {"target_month": "2024-13"},
                      {"horizon_months": 2}, {"issued_at": "2024-02-14T00:00:00Z"}):
            run("forecast", rc=5, **(base | {"REQUEST": request(february, **edits)}))
        projected = run("project", **base)
        run("verify", **(base | {"PROJECTED": projected}))
        run("verify", rc=20, **(base | {"PROJECTED": projected.replace('"nights":190', '"nights":191')}))
        for a, b in (('"unit":"guest_nights"', '"unit":"EUR"'), ('"version":1', '"version":2'),
                     ('"pricing_input":false', '"pricing_input":true'),
                     ('"cutoff":"2024-02-15', '"cutoff":"2024-02-16'),
                     ('"period":"2024-01"', '"period":"2023-12"'),
                     ('"period":"2024-01"', '"period":"2024-02"'),
                     ('"nights":190', '"nights":-1'), ('"nights":190', '"nights":null'),
                     ('"state":"available","parent"', '"state":"partial","parent"')):
            changed = projected.replace(a, b, 1)
            assert changed != projected
            run("model-reject", rc=5, **(base | {"PROJECTED": changed}))
        print(f"forecast_baselines_ok=true models=2 compiled_calls={counts['accepted']} "
              f"rejections={counts['rejected']} holdout_mae=30,105 holdout_mse=900,11050")
        for model, target, artifact in evidence:
            print(f"{model} {target} {artifact}")


if __name__ == "__main__":
    main()
