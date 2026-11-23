#!/usr/bin/env python3
"""Compiled, point-in-time forecast scoring vs an independent Fraction oracle.

This is analysis-only, with no network and no FinPRED store. For machines
without the pinned On1x compiler, --oracle-only runs just the independent
fixture/schema arithmetic checks and does NOT claim compiled verification.
"""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins/forecast_baselines"
MODEL_SOURCE = PACKAGE / "source/forecast_baselines/model.on1x"
SCORE_SOURCE = PACKAGE / "source/forecast_baselines/score.on1x"
CONSUMER = ROOT / "tests/forecast_score_consumer/main.on1x"
SCHEMA = PACKAGE / "contracts/analysis.guest-nights-score@1.schema.json"
sys.dont_write_bytecode = True
MOVING = "forecast.moving-average-3@1"
SEASONAL = "forecast.seasonal-naive-12@1"
EVIDENCE = "blake3:" + "0" * 64


def serialized(document):
    return json.dumps(document, separators=(",", ":")) + "\n"


def snapshot(release):
    values = release["values"]
    return serialized({
        "format": "dragnet.eurostat-accommodation-nights@1",
        "source": "Eurostat", "source_series": "tour_occ_nim",
        "provider_updated_at": release["updated"], "geography": "EU27_2020",
        "activity": "I551-I553", "residence": "TOTAL", "unit": "guest_nights",
        "status": "complete" if len(values) == 3 and None not in values.values() else "partial",
        "mode": "offline_snapshot", "observed_at": release["received"],
        "received_at": release["received"], "ingested_at": release["ingested"],
        "as_of": release["ingested"], "terms_ref": "synthetic", "retention_ref": "synthetic",
        "raw_evidence": EVIDENCE, "capture_evidence": EVIDENCE,
        "raw_bytes": 1, "pricing_input": False,
        "observations": [{"period": p, "nights": v, "provider_flag": None}
                         for p, v in values.items()],
    })


def request(origin):
    return serialized({"issued_at": origin["issued"],
                       "target_month": origin["target"], "horizon_months": 1})


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
    months = ([shift_month(origin["issued"][:7], -i) for i in range(1,4)]
              if model == MOVING else [shift_month(origin["target"], -12)])
    selected = [values.get(m) for m in months]
    return None if None in selected else Fraction(sum(selected), len(selected))


def baseline():
    chronology = json.loads((ROOT / "tests/forecast_baseline_consumer/chronology.json").read_text())
    validator = Draft202012Validator(json.loads(SCHEMA.read_bytes()),
                                   format_checker=FormatChecker())
    Draft202012Validator.check_schema(validator.schema)
    origin = chronology["origins"]
    releases = chronology["snapshots"]
    actuals = releases["actuals"]["values"]
    expectations = {}
    for model in (MOVING, SEASONAL):
        for point in origin:
            cutoff = point["cutoff"]
            if model == MOVING:
                release = releases[point["training"]]
            else:
                release = releases["season"]
            estimate = oracle(model, point, visible(releases, cutoff))
            truth = Fraction(actuals[point["target"]])
            assert estimate is not None
            expectations[(model, point["target"])] = (release, estimate, truth)
    # Independent schema/metric oracle, also executed by --oracle-only.
    for (model, month), (_, predicted, actual) in expectations.items():
        error = predicted - actual
        def pair(value):
            return {"numerator": value.numerator, "denominator": value.denominator}
        digest = "blake3:" + "0" * 64
        observation = next(x for x in origin if x["target"] == month)
        reference = {
            "kind": "analysis.guest-nights-score", "version": 1, "unit": "guest_nights",
            "currency": None, "pricing_input": False, "model": model,
            "code_digest": digest, "policy_digest": digest,
            "forecast": digest, "training": digest, "actuals": digest,
            "actuals_parent": digest, "issued_at": observation["issued"],
            "training_cutoff": observation["cutoff"],
            "scoring_cutoff": chronology["scoring_cutoff"], "target_month": month,
            "state": "scored", "reason": None, "actual": int(actual),
            "estimate": pair(predicted), "error": pair(error),
            "absolute_error": pair(abs(error)),
        }
        validator.validate(reference)
        reference["state"] = "unknown"
        reference["reason"] = "missing_actual"
        for name in ("actual", "estimate", "error", "absolute_error"):
            reference[name] = None
        validator.validate(reference)
        reference["pricing_input"] = True
        assert not validator.is_valid(reference)
    assert [expectations[(MOVING, x["target"])][1] for x in origin] == [170, 180, 200]
    assert [expectations[(SEASONAL, x["target"])][1] for x in origin] == [100, 110, 120]
    for model, expected in ((MOVING, Fraction(30)), (SEASONAL, Fraction(105))):
        holdout = [abs(expectations[(model, x["target"])][1] -
                       expectations[(model, x["target"])][2])
                   for x in origin if x["split"] == "holdout"]
        assert sum(holdout) / len(holdout) == expected
    return chronology, validator, expectations


def invoke(exe, env, directory, case, *, failure=None, **inputs):
    environment = env | {"CASE": case, **inputs}
    p = subprocess.run([str(exe)], env=environment, cwd=directory,
                       capture_output=True, timeout=12)
    if failure is None:
        assert p.returncode == 0 and p.stdout and not p.stderr, (case, p)
    else:
        assert p.returncode == failure and not p.stdout and not p.stderr, (case, p)
    assert not list(directory.iterdir()), "scoring must not create/alter a store"
    return p.stdout.decode("ascii")


def rational(pair):
    return Fraction(pair["numerator"], pair["denominator"])


def compiled(chronology, validator, expected):
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    if not compiler.is_file():
        raise RuntimeError(f"missing pinned On1x compiler: {compiler}; compiled scoring not tested")
    if not (mulib / "on1x/tools/on1x-build.py").is_file():
        raise RuntimeError(f"missing MuLIB source checkout: {mulib}")
    with tempfile.TemporaryDirectory(prefix="finpred-forecast-score-") as temp:
        work = Path(temp)
        exe = work / "score-consumer"
        env = os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, str(mulib / "on1x/tools/on1x-build.py"),
                        str(CONSUMER), "--backend", "c11", "--on1xc", str(compiler),
                        "--mulib-root", str(mulib), "-I", str(ROOT / "source"),
                        "-I", str(PACKAGE / "source"), "-o", str(exe)],
                       cwd=work, env=env, check=True, timeout=120)
        offline = work / "empty-store"
        offline.mkdir()
        env |= {"CODE_BYTES": MODEL_SOURCE.read_text(),
                "FINPRED_HOME": str(offline / "absent")}
        def digest(payload):
            return invoke(exe,env,offline,"digest",BYTES=payload).strip()

        current = chronology["origins"]
        releases = chronology["snapshots"]
        score_at = chronology["scoring_cutoff"]
        actual_raw = snapshot(releases["actuals"])
        parent = digest(actual_raw)
        assert parent.startswith("blake3:") and len(parent) == 71
        hits = {MOVING:[], SEASONAL:[]}
        references = {}
        count = 0
        for model in (MOVING, SEASONAL):
            for point in current:
                training, forecast_number, realized = expected[(model,point["target"])]
                train_raw = snapshot(training)
                inputs = {"MODEL": model, "TRAIN_RAW": train_raw,
                          "TRAIN_PARENT": digest(train_raw), "TRAIN_CUTOFF": point["cutoff"],
                          "REQUEST": request(point), "ACTUAL_RAW": actual_raw,
                          "ACTUAL_PARENT": parent, "SCORE_CUTOFF": score_at}
                forecast = invoke(exe,env,offline,"forecast",**inputs)
                result = invoke(exe,env,offline,"score",FROZEN_FORECAST=forecast,**inputs)
                assert result == invoke(exe,env,offline,"score",FROZEN_FORECAST=forecast,**inputs)
                data = json.loads(result)
                validator.validate(data)
                assert data["state"] == "scored" and data["reason"] is None
                assert (data["issued_at"],data["training_cutoff"],data["scoring_cutoff"],data["target_month"]) == (
                    point["issued"], point["cutoff"], score_at, point["target"])
                assert data["forecast"] == digest(forecast)
                assert data["actuals_parent"] == parent
                assert data["training"] != data["actuals"]
                assert data["model"] == model and data["pricing_input"] is False
                assert data["actual"] == realized
                assert rational(data["estimate"]) == forecast_number
                assert rational(data["error"]) == forecast_number - realized
                assert rational(data["absolute_error"]) == abs(forecast_number - realized)
                if point["split"] == "holdout":
                    hits[model].append(rational(data["absolute_error"]))
                references[(model,point["target"])] = digest(result)
                count += 1

                if model == MOVING and point["target"] == "2024-03":
                    invoke(exe,env,offline,"score",failure=36,**inputs,
                           FROZEN_FORECAST=forecast.replace('"target_month":"2024-03"',
                                                            '"target_month":"2024-02"'))
                    invoke(exe,env,offline,"score",failure=34,
                           **(inputs | {"ACTUAL_PARENT":"blake3:"+"0"*64}),
                           FROZEN_FORECAST=forecast)
                    invoke(exe,env,offline,"score",failure=32,
                           **(inputs | {"TRAIN_PARENT":"blake3:"+"0"*64}),
                           FROZEN_FORECAST=forecast)
                    invoke(exe,env,offline,"score",failure=35,
                           **(inputs | {"SCORE_CUTOFF":"2024-03-31T23:59:59Z"}),
                           FROZEN_FORECAST=forecast)
                    invoke(exe,env,offline,"score",failure=34,
                           **(inputs | {"SCORE_CUTOFF":"2024-04-01T00:00:00Z"}),
                           FROZEN_FORECAST=forecast)
                    invoke(exe,env,offline,"score",failure=31,
                           **(inputs | {"MODEL":"forecast.unregistered@1"}),
                           FROZEN_FORECAST=forecast)

        assert len(references) == 6 and len(set(references.values())) == 6
        assert sum(hits[MOVING]) / 2 == 30
        assert sum(hits[SEASONAL]) / 2 == 105

        # A zero is an observed result, not an unknown value.
        point = current[1]
        training = releases[point["training"]]
        normal = {"MODEL": MOVING, "TRAIN_CUTOFF": point["cutoff"],
                  "REQUEST": request(point), "TRAIN_RAW": snapshot(training),
                  "TRAIN_PARENT": digest(snapshot(training)), "SCORE_CUTOFF": score_at}
        frozen = invoke(exe,env,offline,"forecast",**normal)
        zero = releases["actuals"] | {"values": releases["actuals"]["values"] | {"2024-03":0}}
        raw_zero = snapshot(zero)
        scored = json.loads(invoke(exe,env,offline,"score",**normal,
                                   FROZEN_FORECAST=frozen,ACTUAL_RAW=raw_zero,
                                   ACTUAL_PARENT=digest(raw_zero)))
        validator.validate(scored)
        assert scored["actual"] == 0 and rational(scored["error"]) == 180

        missing = releases["actuals"] | {"values": releases["actuals"]["values"] | {"2024-03":None}}
        raw_missing = snapshot(missing)
        unscored = json.loads(invoke(exe,env,offline,"score",**normal,
                                     FROZEN_FORECAST=frozen,ACTUAL_RAW=raw_missing,
                                     ACTUAL_PARENT=digest(raw_missing)))
        validator.validate(unscored)
        assert unscored["state"] == "unknown" and unscored["reason"] == "missing_actual"

        unavailable_training = training | {"values":training["values"] | {"2024-01":None}}
        raw_unknown = snapshot(unavailable_training)
        missing_inputs = normal | {"TRAIN_RAW":raw_unknown,"TRAIN_PARENT":digest(raw_unknown)}
        unknown_forecast = invoke(exe,env,offline,"forecast",**missing_inputs)
        unscored = json.loads(invoke(exe,env,offline,"score",**missing_inputs,
                                     FROZEN_FORECAST=unknown_forecast,
                                     ACTUAL_RAW=actual_raw,ACTUAL_PARENT=parent))
        validator.validate(unscored)
        assert unscored["state"] == "unknown" and unscored["reason"] == "insufficient_evidence"

        frac_training = training | {"values":training["values"] | {"2024-01":191}}
        raw_fraction = snapshot(frac_training)
        fractional_inputs = normal | {"TRAIN_RAW":raw_fraction,"TRAIN_PARENT":digest(raw_fraction)}
        fractional_forecast = invoke(exe,env,offline,"forecast",**fractional_inputs)
        fractional = json.loads(invoke(exe,env,offline,"score",**fractional_inputs,
                                       FROZEN_FORECAST=fractional_forecast,
                                       ACTUAL_RAW=actual_raw,ACTUAL_PARENT=parent))
        validator.validate(fractional)
        assert rational(fractional["estimate"]) == Fraction(541,3)
        assert rational(fractional["error"]) == Fraction(-89,3)
        assert rational(fractional["absolute_error"]) == Fraction(89,3)
        assert not list(offline.iterdir())
        print(f"forecast_scores_ok=true scored={count} unknown=2 fractional=1 replay=exact store_writes=0")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--oracle-only", action="store_true", help="check test fixture arithmetic without compiling On1x")
    args = p.parse_args()
    chronology, validator, expectations = baseline()
    if args.oracle_only:
        print("forecast_scores_oracle_ok=true compiled=NOT_RUN")
    else:
        compiled(chronology, validator, expectations)


if __name__ == "__main__":
    main()
