#!/usr/bin/env python3
"""Compile and replay synthetic guest-night vintages against a Fraction/UTC oracle."""
from datetime import datetime
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

sys.dont_write_bytecode = True
from check_forecast_scores import ROOT, PACKAGE, invoke, serialized, shift_month, snapshot

MOVING = "forecast.vintage-moving-average-3@1"
SEASONAL = "forecast.vintage-seasonal-naive-12@1"
LAST = "forecast.vintage-last-complete-month@1"
CONSUMER = ROOT / "tests/forecast_vintage_consumer/main.on1x"
PREFIX = "analysis.guest-nights-vintage-"
TRAIN_CUTOFF = "2024-04-15T00:00:00Z"
ISSUED = "2024-04-17T00:00:00Z"
SCORE_CUTOFF = "2024-07-15T00:00:00Z"


def release(published, visible, period, value, *, captured=None, flag=None):
    captured = captured or visible
    doc = json.loads(snapshot({
        "updated": published,
        "received": f"{captured}T00:00:00Z",
        "ingested": f"{captured}T00:00:00Z",
        "values": {period: value},
    }))
    doc["as_of"] = f"{visible}T00:00:00Z"
    doc["observations"][0]["provider_flag"] = flag
    return serialized(doc)


def pair(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def clock(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def expected_row(raws, period, cutoff, digest):
    candidates = []
    for raw in raws:
        doc = json.loads(raw)
        if clock(doc["as_of"]) <= clock(cutoff):
            for obs in doc["observations"]:
                if obs["period"] == period:
                    candidates.append((clock(doc["provider_updated_at"]), clock(doc["as_of"]),
                                       digest(raw), obs, doc))
    if not candidates:
        return dict(period=period, state="absent", nights=None, provider_flag=None,
                    provider_updated_at=None, source_as_of=None, snapshot=None)
    newest = max(c[0] for c in candidates)
    tied = [c for c in candidates if c[0] == newest]
    assert len({(c[3]["nights"], c[3]["provider_flag"]) for c in tied}) == 1
    _, _, root, obs, doc = min(tied, key=lambda c: (c[1], c[2]))
    return dict(period=period, state="available" if obs["nights"] is not None else "unknown",
                nights=obs["nights"], provider_flag=obs["provider_flag"],
                provider_updated_at=doc["provider_updated_at"], source_as_of=doc["as_of"],
                snapshot=root)


def schemas():
    docs = {suffix: json.loads((PACKAGE / "contracts" /
                                f"{PREFIX}{suffix}@1.schema.json").read_bytes())
            for suffix in ("request", "catalog", "forecast", "evaluation")}
    registry = Registry().with_resources((d["$id"], Resource.from_contents(d))
                                         for d in docs.values())
    result = {}
    for suffix, doc in docs.items():
        Draft202012Validator.check_schema(doc)
        result[suffix] = Draft202012Validator(doc, registry=registry, format_checker=FormatChecker())
    return result


def exercise(exe, env, offline):
    valid = schemas()
    hashes = {}
    runs = 0
    rejects = 0

    def digest(payload):
        if payload not in hashes:
            hashes[payload] = invoke(exe, env, offline, "digest", BYTES=payload).strip()
        return hashes[payload]

    def catalog(side, raws, *, ordered=True):
        entries = [(digest(raw), raw) for raw in raws]
        if ordered:
            entries.sort()
        doc = {"kind": PREFIX + "catalog", "version": 1, "snapshots": [p for p, _ in entries]}
        if ordered and len(set(doc["snapshots"])) == len(entries):
            valid["catalog"].validate(doc)
        inputs = {f"{side}_ID": digest(serialized(doc)), f"{side}_COUNT": str(len(entries))}
        for i, (parent, raw) in enumerate(entries):
            inputs[f"{side}_{i}_ID"] = parent
            inputs[f"{side}_{i}_RAW"] = raw
        return inputs

    def run(task, inputs, expected=None):
        nonlocal runs
        raw = invoke(exe, env, offline, task, **inputs)
        assert raw == invoke(exe, env, offline, task, **inputs)
        root, data = raw.splitlines(keepends=True)
        value = json.loads(data)
        assert root.strip() == digest(data) and serialized(value) == data
        valid["forecast" if task == "issue" else "evaluation"].validate(value)
        if expected is not None:
            assert value == expected
        runs += 1
        return root.strip(), data, value

    def reject(status, task, inputs, **changes):
        nonlocal rejects
        invoke(exe, env, offline, task, failure=40 + status, **(inputs | changes))
        rejects += 1

    jan = release("2024-02-05T10:00:00+0000", "2024-02-06", "2024-01", 100)
    feb = release("2024-03-05T10:00:00+0000", "2024-03-06", "2024-02", 200)
    mar = release("2024-04-05T10:00:00+0000", "2024-04-06", "2024-03", 301, flag="p")
    # Publication and capture are earlier than the issue cutoff, but local
    # source-as-of is later; supplier/confidence alone cannot reveal this row.
    feb_new = release("2024-04-09T10:00:00+0000", "2024-04-16", "2024-02", 500,
                      captured="2024-04-10")
    jan_stale = release("2024-02-04T11:00:00+0000", "2024-04-07", "2024-01", 1000)
    jan_same = release("2024-02-05T11:00:00+0100", "2024-02-07", "2024-01", 100)
    jan_conflict = release("2024-02-05T11:00:00+0100", "2024-02-07", "2024-01", 101)
    jan_new = release("2024-04-08T10:00:00+0000", "2024-04-09", "2024-01", 150)
    feb_null = release("2024-04-12T10:00:00+0000", "2024-04-14", "2024-02", None)
    past_jun = release("2023-07-03T10:00:00+0000", "2023-07-04", "2023-06", 400)
    first_actual = release("2024-07-04T10:00:00+0000", "2024-07-05", "2024-06", 250)
    revised_actual = release("2024-07-20T10:00:00+0000", "2024-07-21", "2024-06", 0)
    null_actual = release("2024-07-22T10:00:00+0000", "2024-07-23", "2024-06", None)
    train = [jan, feb, mar, jan_stale, jan_same, past_jun]
    actuals = [first_actual, revised_actual, null_actual]

    def request(issued, horizon):
        doc = {"kind": PREFIX + "request", "version": 1, "issued_at": issued,
               "target_month": shift_month(issued[:7], horizon), "horizon_months": horizon}
        valid["request"].validate(doc)
        return serialized(doc)

    base = {"MODEL_CODE": digest(env["MODEL_SUBJECT"]), "SCORING_CODE": digest(env["SCORING_SUBJECT"]),
            "TRAIN_CUTOFF": TRAIN_CUTOFF, "SCORE_CUTOFF": SCORE_CUTOFF}

    def issued(model, raws, horizon=2, *, cutoff=TRAIN_CUTOFF, issue_time=ISSUED):
        req = request(issue_time, horizon)
        settings = base | {"REQUEST": req, "TRAIN_CUTOFF": cutoff, "MODEL": model}
        inputs = settings | catalog("TRAIN", raws)
        fid, forecast, data = run("issue", inputs)
        target = shift_month(issue_time[:7], horizon)
        assert data["target_month"] == target and data["horizon_months"] == horizon
        assert (data["issued_at"], data["training_cutoff"]) == (issue_time, cutoff)
        assert data["request"] == digest(req)
        assert data["model_code_digest"] == base["MODEL_CODE"] and data["model"] == model
        if model == SEASONAL:
            periods = [shift_month(target, -12)]
        else:
            periods = [shift_month(issue_time[:7], step) for step in
                       (range(-3, 0) if model == MOVING else [-1])]
        rows = [expected_row(raws, m, cutoff, digest) for m in periods]
        assert data["training"] == rows
        n = [row["nights"] for row in rows]
        expected = None if None in n else Fraction(sum(n), len(n))
        assert data["estimate"] == (None if expected is None else pair(expected))
        return inputs | {"FORECAST_ID": fid, "FORECAST": forecast}, expected

    bound, estimate = issued(MOVING, train)
    with_future, _ = issued(MOVING, train + [feb_new, first_actual])
    assert bound["FORECAST"] == with_future["FORECAST"]
    assert bound["TRAIN_ID"] != with_future["TRAIN_ID"]
    assert estimate == Fraction(601, 3)
    at_visibility, new = issued(MOVING, train + [feb_new], cutoff="2024-04-16T00:00:00Z")
    assert new == Fraction(901, 3) and at_visibility["FORECAST"] != bound["FORECAST"]
    season, seasonal = issued(SEASONAL, train)
    assert seasonal == 400
    assert issued(LAST, train)[1] == 301
    for horizon in range(1, 12):
        if horizon != 2:
            assert issued(MOVING, train, horizon)[1] == estimate
    assert issued(SEASONAL, train, 1)[1] is None
    assert issued(SEASONAL, train, 11)[1] == 301
    assert issued(MOVING, train + [feb_null])[1] is None
    assert issued(MOVING, [jan, mar])[1] is None
    assert issued(MOVING, [])[1] is None
    assert issued(MOVING, train + [jan_conflict, jan_new])[1] == 217
    assert issued(SEASONAL, train + [jan_conflict])[1] == 400
    high = 999999999999
    assert issued(LAST, [release("2024-04-05T10:00:00+0000", "2024-04-06", "2024-03", high)])[1] == high
    three_rows = snapshot({"updated": "2024-04-05T10:00:00+0000", "received": "2024-04-06T00:00:00Z",
                           "ingested": "2024-04-06T00:00:00Z",
                           "values": {"2024-01": high, "2024-02": high, "2024-03": high - 1}})
    assert issued(MOVING, [three_rows])[1] == Fraction(high * 3 - 1, 3)
    captures = [jan.replace('"terms_ref":"synthetic"', f'"terms_ref":"synthetic-{i}"')
                for i in range(62)]
    assert issued(MOVING, captures + [feb, mar])[1] == estimate

    def evaluated(frozen, predicted, raw_actuals, cutoff=SCORE_CUTOFF):
        inputs = frozen | catalog("ACTUAL", raw_actuals) | {"SCORE_CUTOFF": cutoff}
        eid, body, data = run("evaluate", inputs)
        archive = inputs | {"EVALUATION_ID": eid, "EVALUATION": body}
        assert run("replay", archive, data)[:2] == (eid, body)
        target = json.loads(frozen["REQUEST"])["target_month"]
        actual = expected_row(raw_actuals, target, cutoff, digest)
        assert data["actual"] == actual and data["scoring_cutoff"] == cutoff
        assert data["forecast"] == frozen["FORECAST_ID"]
        assert data["actuals_catalog"] == inputs["ACTUAL_ID"] and data["training_catalog"] == inputs["TRAIN_ID"]
        assert data["scoring_code_digest"] == inputs["SCORING_CODE"]
        if actual["nights"] is None or predicted is None:
            assert data["reason"] == ("missing_actual" if actual["nights"] is None else "insufficient_evidence")
        else:
            error = predicted - actual["nights"]
            assert data["error"] == pair(error) and data["absolute_error"] == pair(abs(error))
        return archive

    archive = evaluated(bound, estimate, actuals)
    evaluated(with_future, estimate, actuals, "2024-07-21T00:00:00Z")
    evaluated(bound, estimate, actuals, "2024-07-23T00:00:00Z")
    evaluated(bound, estimate, actuals, "2024-07-01T00:00:00Z")
    evaluated(season, seasonal, actuals)
    unknown, missing = issued(MOVING, train + [feb_null])
    evaluated(unknown, missing, actuals)
    evaluated(unknown, missing, [])
    exact = release("2024-07-04T10:00:00+0000", "2024-07-05", "2024-06", 400)
    evaluated(season, seasonal, [exact])
    huge = release("2024-07-04T10:00:00+0000", "2024-07-05", "2024-06", high)
    evaluated(bound, estimate, [huge])

    # Walk successive origins on the same frozen full catalog. The February
    # revision and the April count enter only the second training window;
    # May and July outcomes are still in the future at their issuance.
    april = release("2024-05-03T10:00:00+0000", "2024-05-05", "2024-04", 320)
    may = release("2024-06-03T10:00:00+0000", "2024-06-05", "2024-05", 350)
    july = release("2024-08-03T10:00:00+0000", "2024-08-05", "2024-07", 410)
    timeline = train + [feb_new, april, may, first_actual, july]
    for as_of, when, horizon, predicted in (
        (TRAIN_CUTOFF, ISSUED, 1, Fraction(601, 3)),
        ("2024-05-15T00:00:00Z", "2024-05-17T00:00:00Z", 2, Fraction(1121, 3)),
    ):
        saved, prediction = issued(MOVING, timeline, horizon, cutoff=as_of, issue_time=when)
        assert prediction == predicted
        evaluated(saved, prediction, timeline, "2024-08-15T00:00:00Z")

    reject(3, "issue", bound | catalog("TRAIN", train + [jan_conflict]))
    reject(3, "evaluate", archive | catalog("ACTUAL", actuals + [
        release("2024-07-04T11:00:00+0100", "2024-07-06", "2024-06", 250, flag="p")]))
    reject(2, "issue", bound, TRAIN_ID=digest("unrelated catalog"))
    reject(2, "issue", bound, TRAIN_COUNT="1")
    reject(1, "issue", bound, TRAIN_COUNT="65")
    reject(2, "issue", bound | catalog("TRAIN", [jan, jan]))
    reject(2, "issue", bound | catalog("TRAIN", sorted([jan, feb], key=digest, reverse=True), ordered=False))
    reject(2, "issue", bound, TRAIN_0_RAW=bound["TRAIN_0_RAW"] + "\n")
    future_bad = feb_new.replace('"pricing_input":false', '"pricing_input":true')
    reject(2, "issue", bound | catalog("TRAIN", train + [future_bad]))
    reject(1, "issue", bound, TRAIN_CUTOFF="2024-04-18T00:00:00Z")
    reject(1, "issue", bound, MODEL_CODE=digest("wrong model code"))
    reject(1, "issue", bound, MODEL="forecast.moving-average-3@1")
    reject(1, "issue", bound, REQUEST=bound["REQUEST"].replace('"horizon_months":2', '"horizon_months":1'))
    reject(1, "issue", bound, REQUEST=bound["REQUEST"].replace('"horizon_months":2', '"horizon_months":12'))
    reject(1, "issue", bound, REQUEST=bound["REQUEST"] + "\n")
    reject(1, "evaluate", archive, SCORE_CUTOFF="2024-06-30T23:59:59Z")
    reject(1, "evaluate", archive, SCORING_CODE=digest("wrong scoring code"))
    reject(2, "evaluate", archive, ACTUAL_ID=digest("wrong actual catalog"))
    reject(4, "evaluate", archive, FORECAST_ID=digest("wrong forecast ID"))
    forged = serialized(json.loads(archive["FORECAST"]) | {"estimate": pair(Fraction(0))})
    reject(4, "evaluate", archive, FORECAST=forged, FORECAST_ID=digest(forged))
    reject(5, "replay", archive, EVALUATION_ID=digest("wrong evaluation ID"))
    reject(5, "replay", archive, EVALUATION=archive["EVALUATION"] + "\n")
    forged = serialized(json.loads(archive["EVALUATION"]) | {"error": pair(Fraction(0))})
    reject(5, "replay", archive, EVALUATION=forged, EVALUATION_ID=digest(forged))
    reject(5, "replay", archive | catalog("TRAIN", train + [feb_new]))
    reject(5, "replay", archive | catalog("ACTUAL", [first_actual]))
    print(f"forecast_vintage_ok=true deterministic_runs={runs} rejected={rejects} "
          "models=3 horizons=1..11 exact_fraction_oracle=true fixture=synthetic")


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    with tempfile.TemporaryDirectory(prefix="finpred-forecast-vintage-") as directory:
        work = Path(directory)
        exe = work / "vintage-consumer"
        env = os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, str(mulib / "on1x/tools/on1x-build.py"), str(CONSUMER),
                        "--backend", "c11", "--on1xc", str(compiler), "--mulib-root", str(mulib),
                        "-I", str(ROOT / "source"), "-I", str(ROOT), "-I", str(PACKAGE / "source"),
                        "-o", str(exe)], cwd=work, env=env, check=True, timeout=120)
        offline = work / "empty-store"
        offline.mkdir()

        def test_subject(*names):
            # These fixture pins describe test sources, not production binaries.
            framed = "finpred.test-vintage-source-subject@1\n"
            for name in names:
                path = PACKAGE / "source/forecast_baselines" / f"{name}.on1x"
                raw = path.read_text(encoding="ascii")
                framed += f"{name}\n{len(raw)}:{raw}"
            return framed

        env |= {"FINPRED_HOME": str(offline / "absent"),
                "MODEL_SUBJECT": test_subject("model", "vintage", "vintage_replay"),
                "SCORING_SUBJECT": test_subject("vintage_replay", "vintage", "model")}
        exercise(exe, env, offline)


if __name__ == "__main__":
    main()
