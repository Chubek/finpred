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
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins/forecast_baselines"
MODEL_SOURCE = PACKAGE / "source/forecast_baselines/model.on1x"
SCORE_SOURCE = PACKAGE / "source/forecast_baselines/score.on1x"
EVALUATION_SOURCE = PACKAGE / "source/forecast_baselines/evaluation.on1x"
CONSUMER = ROOT / "tests/forecast_score_consumer/main.on1x"
SCHEMA = PACKAGE / "contracts/analysis.guest-nights-score@1.schema.json"
EVALUATION_SCHEMA = PACKAGE / "contracts/analysis.guest-nights-evaluation@1.schema.json"
HOLDOUT_SCHEMA = PACKAGE / "contracts/analysis.guest-nights-holdout@1.schema.json"
SCORING_POLICY = ("guest-nights-score@1;replay-issued-forecast;actual-visible-at-scoring-cutoff;"
                  "score-after-issuance-and-at-or-after-target-month-end;"
                  "signed-estimate-minus-actual;missing-actual-before-insufficient-evidence")
HOLDOUT_POLICY = ("guest-nights-holdout@1;one-model-frozen-between-validation-end-and-holdout-start;"
                  "complete-contiguous-window-max-24;"
                  "replay-expected-evaluation;one-scoring-cutoff;known-only-exact-mae-and-signed-bias")
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


def check_evaluation(exe, env, directory, digest, validator, inputs, forecast, score, *, negatives=False):
    trusted = inputs | {"FROZEN_FORECAST": forecast, "FORECAST_PARENT": digest(forecast),
                        "REQUEST_PARENT": digest(inputs["REQUEST"]),
                        "MODEL_CODE": digest(env["CODE_BYTES"]),
                        "SCORING_CODE": digest(env["SCORING_CODE_BYTES"])}
    result = invoke(exe, env, directory, "evaluate", **trusted)
    run_id, manifest, artifact = result.splitlines(keepends=True)
    data = json.loads(score)
    expected = {
        "kind": "analysis.guest-nights-evaluation", "version": 1, "pricing_input": False,
        "model": data["model"], "model_code_digest": data["code_digest"],
        "model_policy_digest": data["policy_digest"], "scoring_code_digest": trusted["SCORING_CODE"],
        "scoring_policy_digest": digest(SCORING_POLICY), "training_cutoff": inputs["TRAIN_CUTOFF"],
        "scoring_cutoff": inputs["SCORE_CUTOFF"], "training_snapshot": inputs["TRAIN_PARENT"],
        "actuals_snapshot": inputs["ACTUAL_PARENT"], "request": trusted["REQUEST_PARENT"],
        "forecast": trusted["FORECAST_PARENT"], "score": digest(score), "state": data["state"],
    }
    validator.validate(json.loads(manifest))
    assert manifest == serialized(expected) and run_id.strip() == digest(manifest)
    assert artifact == score
    replay = trusted | {"EVALUATION_ID": run_id.strip(), "MANIFEST": manifest, "SCORE": artifact}
    assert invoke(exe, env, directory, "replay", **replay) == result
    if negatives:
        def reject(status, **changes):
            invoke(exe, env, directory, "replay", failure=50 + status, **(replay | changes))

        def rehashed(**changes):
            forged = serialized(expected | changes)
            return {"MANIFEST": forged, "EVALUATION_ID": digest(forged)}

        reject(1, SCORING_CODE="untrusted")
        reject(1, SCORING_CODE=digest("different scoring code"))
        reject(3, MODEL=SEASONAL)
        reject(1, CODE_BYTES="different model code")
        reject(2, REQUEST=inputs["REQUEST"].replace('"horizon_months":1', '"horizon_months":2'))
        reject(2, ACTUAL_RAW=inputs["ACTUAL_RAW"] + "\n")
        reject(2, TRAIN_RAW=inputs["TRAIN_RAW"] + "\n")
        reject(2, FROZEN_FORECAST=forecast + "\n")
        reject(2, REQUEST_PARENT=digest("unrelated request"))
        reject(2, TRAIN_RAW=" " * 4097, TRAIN_PARENT=digest(" " * 4097))
        reject(3, SCORE_CUTOFF="2024-03-31T23:59:59Z")
        reject(4, EVALUATION_ID=digest("wrong run"))
        reject(4, MANIFEST=manifest + "\n")
        reject(4, **rehashed(actuals_snapshot=inputs["TRAIN_PARENT"]))
        reject(4, **rehashed(model_policy_digest=digest("different model policy")))
        reject(4, **rehashed(scoring_policy_digest=digest("different scoring policy")))
        reject(4, **rehashed(scoring_cutoff="2024-07-01T00:00:00Z"))
        reject(4, **rehashed(version=2))
        reject(5, SCORE=score + "\n")
        forged_score = serialized(data | {"actual": data["actual"] + 1})
        reject(5, SCORE=forged_score, **rehashed(score=digest(forged_score)))
    return replay


def check_holdout(exe, env, directory, digest, chronology, entries, fractional, missing):
    validator = Draft202012Validator(json.loads(HOLDOUT_SCHEMA.read_bytes()),
                                    format_checker=FormatChecker())
    Draft202012Validator.check_schema(validator.schema)
    plan = {"MODEL": MOVING, "MODEL_CODE": digest(env["CODE_BYTES"]),
            "SCORING_CODE": digest(env["SCORING_CODE_BYTES"]),
            "VALIDATION_THROUGH": "2024-02", "SELECTION_FROZEN_AT": "2024-03-01T00:00:00Z",
            "FIRST_TARGET": "2024-03", "LAST_TARGET": "2024-04",
            "SCORE_CUTOFF": chronology["scoring_cutoff"]}
    holdout_cases = rejections = 0

    def invoke_report(rows, plan, *, failure=None, **changes):
        per_month = {f"ENTRY_{i}_{key}": value for i, row in enumerate(rows)
                     for key, value in row.items()}
        return invoke(exe, env, directory, "holdout", failure=failure,
                      **(plan | per_month | changes))

    def report(rows, errors, plan=plan):
        nonlocal holdout_cases
        result = invoke_report(rows, plan)
        assert invoke_report(rows, plan) == result
        identifier, artifact = result.splitlines(keepends=True)
        document = json.loads(artifact)
        validator.validate(document)
        assert identifier.strip() == digest(artifact)
        known = [Fraction(x) for x in errors if x is not None]

        def mean(values):
            if not values:
                return None
            value = sum(values) / len(values)
            return {"numerator": value.numerator, "denominator": value.denominator}

        expected_rows = [{"target_month": shift_month(plan["FIRST_TARGET"], i),
                          "evaluation": row["EVALUATION_ID"],
                          "state": "unknown" if error is None else "scored"}
                         for i, (row, error) in enumerate(zip(rows, errors, strict=True))]
        expected = {
            "kind": "analysis.guest-nights-holdout", "version": 1, "unit": "guest_nights",
            "currency": None, "pricing_input": False, "split": "holdout", "model": plan["MODEL"],
            "model_code_digest": plan["MODEL_CODE"],
            "model_policy_digest": json.loads(rows[0]["MANIFEST"])["model_policy_digest"],
            "scoring_code_digest": plan["SCORING_CODE"],
            "scoring_policy_digest": digest(SCORING_POLICY),
            "aggregation_policy_digest": digest(HOLDOUT_POLICY),
            "validation_through": plan["VALIDATION_THROUGH"],
            "selection_frozen_at": plan["SELECTION_FROZEN_AT"], "first_target": plan["FIRST_TARGET"],
            "last_target": plan["LAST_TARGET"], "scoring_cutoff": plan["SCORE_CUTOFF"],
            "evaluations": expected_rows, "expected": len(rows), "scored": len(known),
            "unknown": len(rows) - len(known), "mae": mean([abs(x) for x in known]), "bias": mean(known),
        }
        assert document == expected and artifact == serialized(expected)
        holdout_cases += 1
        return identifier.strip()

    def bind(inputs, forecast, score):
        return check_evaluation(exe, env, directory, digest, evaluation_validator,
                                inputs, forecast, score)

    def reobserve(entry, actual_release):
        raw = snapshot(actual_release)
        inputs = entry | {"ACTUAL_RAW": raw, "ACTUAL_PARENT": digest(raw)}
        forecast = entry["FROZEN_FORECAST"]
        score = invoke(exe, env, directory, "score", **inputs)
        return bind(inputs, forecast, score)

    evaluation_validator = Draft202012Validator(json.loads(EVALUATION_SCHEMA.read_bytes()),
                                                format_checker=FormatChecker())
    march, april = (entries[(MOVING, month)] for month in ("2024-03", "2024-04"))
    actuals = chronology["snapshots"]["actuals"]
    report_id = report([march, april], [-30, -30])
    report([entries[(SEASONAL, month)] for month in ("2024-03", "2024-04")],
           [-100, -110], plan | {"MODEL": SEASONAL})
    zero = reobserve(april, actuals | {"values": actuals["values"] | {"2024-04": 0}})
    report([fractional, zero], [Fraction(-89, 3), 200])
    report([missing, april], [None, -30])
    unknown_april = reobserve(april, actuals | {"values": actuals["values"] | {"2024-04": None}})
    report([missing, unknown_april], [None, None])
    exact_april = reobserve(april, actuals | {"values": actuals["values"] | {"2024-04": 200}})
    report([exact_april], [0], plan | {"FIRST_TARGET": "2024-04"})
    offset_april = reobserve(april, actuals | {"values": actuals["values"] | {"2024-04": 170}})
    report([march, offset_april], [-30, 30])

    # Full supported window at the maximum absolute source value. Its sum
    # and mean are representable, but squaring even one term exceeds i64.
    high = 999999999999
    max_plan = plan | {"LAST_TARGET": "2026-02", "SCORE_CUTOFF": "2026-04-01T00:00:00Z"}
    max_rows = []
    for i in range(24):
        target = shift_month("2024-03", i)
        issue = shift_month(target, -1)
        cutoff = f"{issue}-15T00:00:00Z"
        raw = snapshot({"updated": f"{issue}-10T12:00:00+0000",
                        "received": f"{issue}-10T12:00:01Z", "ingested": f"{issue}-10T12:00:02Z",
                        "values": {shift_month(issue, j): (1 if j == -1 else 0)
                                   for j in (-3, -2, -1)}})
        truth = snapshot({"updated": "2026-03-10T12:00:00+0000", "received": "2026-03-10T12:00:01Z",
                          "ingested": "2026-03-10T12:00:02Z", "values": {target: high}})
        inputs = {"MODEL": MOVING, "TRAIN_CUTOFF": cutoff, "TRAIN_RAW": raw,
                  "TRAIN_PARENT": digest(raw), "REQUEST": request({"issued": cutoff, "target": target}),
                  "ACTUAL_RAW": truth, "ACTUAL_PARENT": digest(truth),
                  "SCORE_CUTOFF": max_plan["SCORE_CUTOFF"]}
        forecast = invoke(exe, env, directory, "forecast", **inputs)
        score = invoke(exe, env, directory, "score", FROZEN_FORECAST=forecast, **inputs)
        max_rows.append(bind(inputs, forecast, score))
    report(max_rows, [Fraction(1, 3) - high] * 24, max_plan)

    def reject(status, rows=(march, april), **changes):
        nonlocal rejections
        invoke_report(rows, plan, failure=70 + status, **changes)
        rejections += 1

    reject(1, MODEL="forecast.unregistered@1")
    reject(1, MODEL_CODE=digest("wrong linked model digest"))
    reject(1, SCORING_CODE=digest("wrong linked scoring digest"))
    reject(1, FIRST_TARGET="2024-02")
    reject(1, LAST_TARGET="2024-02")
    reject(1, LAST_TARGET="2026-03")
    reject(1, LAST_TARGET="2024-13")
    reject(1, LAST_TARGET="2024-04" + " " * 4096)
    reject(1, SELECTION_FROZEN_AT="2024-03-01T00:00:01Z")
    reject(1, SELECTION_FROZEN_AT="2024-02-29T23:59:59Z")
    reject(1, SCORE_CUTOFF="2024-04-30T23:59:59Z")
    reject(2, rows=(entries[(MOVING, "2024-02")], april))
    reject(2, rows=(march, march))
    reject(2, rows=(april, march))
    reject(2, rows=(march,))
    reject(2, ENTRY_1_TRAIN_CUTOFF="2024-03-16T00:00:00Z")
    reject(3, rows=(march, entries[(SEASONAL, "2024-04")]))
    reject(3, ENTRY_1_SCORE=april["SCORE"] + "\n")
    forged = serialized(json.loads(april["SCORE"]) |
                        {"error": {"numerator": 0, "denominator": 1},
                         "absolute_error": {"numerator": 0, "denominator": 1}})
    rehashed = serialized(json.loads(april["MANIFEST"]) | {"score": digest(forged)})
    reject(3, ENTRY_1_SCORE=forged, ENTRY_1_MANIFEST=rehashed,
           ENTRY_1_EVALUATION_ID=digest(rehashed))
    reject(3, ENTRY_1_EVALUATION_ID=march["EVALUATION_ID"])
    reject(3, ENTRY_1_ACTUAL_RAW=april["ACTUAL_RAW"] + "\n")
    reject(3, SCORE_CUTOFF="2024-06-02T00:00:00Z")
    print(f"forecast_holdout_ok=true reports={holdout_cases} rejected={rejections} max_targets=24 "
          f"replay=exact mae_bias=fractions mse_rmse=deferred fixture_report={report_id}")


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
                         "-I", str(ROOT), "-I", str(PACKAGE / "source"), "-o", str(exe)],
                       cwd=work, env=env, check=True, timeout=120)
        offline = work / "empty-store"
        offline.mkdir()
        evaluation_validator = Draft202012Validator(json.loads(EVALUATION_SCHEMA.read_bytes()),
                                                     format_checker=FormatChecker())
        Draft202012Validator.check_schema(evaluation_validator.schema)
        subjects = [SCORE_SOURCE, EVALUATION_SOURCE, *(ROOT / f"{name}.on1x" for name in (
            "source/core/date", "source/core/feed_snapshot", "source/core/format",
            "plugins/dragnet/guest_nights", "source/sdk/callable"))]
        normalize = runpy.run_path(str(ROOT / "bin/forecast-subject.py"))["v1_source"]
        scoring_subject = "finpred.test-scoring-source-subject@1\n"
        for path in subjects:
            name = path.relative_to(ROOT).as_posix()
            if path.parent == MODEL_SOURCE.parent:
                _, raw = normalize(f"forecast_baselines/{path.name}", path.read_bytes())
            else:
                name, raw = normalize(name.removeprefix("source/"), path.read_bytes())
                name = f"source/{name}"
            scoring_subject += f"{name}\n{len(raw)}:{raw.decode('ascii')}"
        _, model_bytes = normalize(f"forecast_baselines/{MODEL_SOURCE.name}", MODEL_SOURCE.read_bytes())
        env |= {"CODE_BYTES": model_bytes.decode("ascii"),
                "SCORING_CODE_BYTES": scoring_subject,
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
        entries = {}
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
                entries[(model, point["target"])] = check_evaluation(
                    exe, env, offline, digest, evaluation_validator, inputs, forecast, result,
                    negatives=model == MOVING and point["target"] == "2024-03")

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
        # The evaluation envelope must not change the canonical v1 score.
        assert references[(MOVING, "2024-03")] == (
            "blake3:3c02c80c3c46fef5257b5a6a67c6c4719f73630243e3bcabe9642d10a2e48af9")
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
        missing_actual = normal | {"ACTUAL_RAW": raw_missing, "ACTUAL_PARENT": digest(raw_missing)}
        unknown_score = invoke(exe, env, offline, "score", FROZEN_FORECAST=frozen, **missing_actual)
        unscored = json.loads(unknown_score)
        validator.validate(unscored)
        assert unscored["state"] == "unknown" and unscored["reason"] == "missing_actual"
        missing_entry = check_evaluation(exe, env, offline, digest, evaluation_validator,
                                         missing_actual, frozen, unknown_score)

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
        fractional_inputs |= {"ACTUAL_RAW": actual_raw, "ACTUAL_PARENT": parent}
        fractional_score = invoke(exe, env, offline, "score", **fractional_inputs,
                                  FROZEN_FORECAST=fractional_forecast)
        fractional = json.loads(fractional_score)
        validator.validate(fractional)
        assert rational(fractional["estimate"]) == Fraction(541,3)
        assert rational(fractional["error"]) == Fraction(-89,3)
        assert rational(fractional["absolute_error"]) == Fraction(89,3)
        evaluation_ids = [row["EVALUATION_ID"] for row in (*entries.values(), missing_entry)]
        assert len(set(evaluation_ids)) == 7
        assert not list(offline.iterdir())
        print(f"forecast_scores_ok=true scored={count} unknown=2 fractional=1 replay=exact store_writes=0")
        print(f"forecast_evaluation_ok=true runs={len(evaluation_ids)} rejected=20 replay=exact "
              f"fixture_run={evaluation_ids[1]} fixture_score={references[(MOVING, '2024-03')]}")

        fractional_entry = check_evaluation(exe, env, offline, digest, evaluation_validator,
                                            fractional_inputs, fractional_forecast, fractional_score)
        check_holdout(exe, env, offline, digest, chronology, entries, fractional_entry,
                      missing_entry)


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
