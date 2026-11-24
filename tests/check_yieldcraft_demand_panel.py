#!/usr/bin/env python3
"""Test On1x panel fits against an independent two-pass weighted oracle."""
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp")
TOOL = ROOT / "bin/yieldcraft-demand"
KINDS = ("constant_elasticity", "log_linear", "ridge_log_linear", "partially_pooled_elasticity")
CUTOFF = "2026-11-09T00:00:00Z"
REFERENCE, TARGET = 10000, 173
GROUPS = ("early", "late")


def arms():
    # Mechanics-only fixtures: unequal exposure weights, genuine within-window
    # variation, changing mix and base levels, a different later slope, no PII.
    return [
        (day, group, price, assigned, kept, 0, assigned - kept, 0, 0)
        for day in range(1, 11)
        for gi, group in enumerate(GROUPS)
        for pi, price in enumerate((8000, 10000, 12500))
        for assigned in [50 + 13 * day + 19 * gi + 11 * pi]
        for kept in [round(assigned * (0.64 - 0.13 * gi + 0.015 * day
                                       - (0.10 + 0.006 * day) * pi))]
    ]


def arm_text(row):
    day, *arm = row
    stamps = [f"2026-11-{day:02}T{hour:02}:00:00Z" for hour in (1, 2, 3, 4)]
    return ",".join(stamps + list(map(str, arm)))


def oracle(rows, kind):
    elasticity = kind in ("constant_elasticity", "partially_pooled_elasticity")
    penalty = 0.0025 if kind in KINDS[2:] else 0
    pool = 1000 if kind == KINDS[3] else 0

    def x(price):
        ratio = price / REFERENCE
        return math.log(ratio) if elasticity else ratio - 1

    train = [row for row in rows if row[0] <= 8]
    holdout = [row for row in rows if row[0] > 8]

    def y(row):
        return math.log((row[4] + 0.5) / (row[3] + 1))

    moments = []
    for day in range(1, 9):
        xx = xy = 0
        for group in GROUPS:
            block = [r for r in train if r[:2] == (day, group)]
            weight = sum(r[3] for r in block)
            cx = sum(r[3] * x(r[2]) for r in block) / weight
            cy = sum(r[3] * y(r) for r in block) / weight
            xx += sum(r[3] * (x(r[2]) - cx) ** 2 for r in block)
            xy += sum(r[3] * (x(r[2]) - cx) * (y(r) - cy) for r in block)
        moments.append((xx, xy))
    sxx, sxy = map(sum, zip(*moments))
    w = sum(r[3] for r in train)
    slope = sxy / (sxx + penalty * w)
    se = None if penalty else math.sqrt((8 / 7) * sum((xy - slope * xx) ** 2 for xx, xy in moments)) / sxx
    pooled = sum(r[3] * (y(r) - slope * x(r[2])) for r in train) / w
    intercepts, baselines = {}, {}
    for group in GROUPS:
        group_rows = [r for r in train if r[1] == group]
        group_w = sum(r[3] for r in group_rows)
        adjusted = sum(r[3] * (y(r) - slope * x(r[2])) for r in group_rows)
        intercepts[group] = (adjusted + pool * pooled) / (group_w + pool)
        baselines[group] = sum(r[4] for r in group_rows) / group_w

    def predict(group, price):
        return min(1, math.exp(intercepts[group] + slope * x(price)))

    def loss(predictor):
        return sum(kept * (1 - p) ** 2 + (assigned - kept) * p ** 2
                   for _, group, price, assigned, kept, *_ in holdout
                   for p in [predictor(group, price)]) / sum(r[3] for r in holdout)

    return (slope, se, intercepts, predict, loss(predict),
            loss(lambda group, _: baselines[group]), sxx / w)


def micro(x):
    return round(x * 1_000_000)


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yieldcraft-panel-", dir=TMP) as tmp:
        work = Path(tmp)
        env = {**os.environ, "FINPRED_BUILD_DIR": str(work), "TMPDIR": str(work),
               "FINPRED_HOME": str(work / "unused-store")}

        def invoke(*args, error=None):
            proc = subprocess.run([TOOL, *map(str, args)], cwd=work, env=env,
                                  capture_output=True, timeout=120)
            if error:
                assert proc.returncode != 0 and error.encode() in proc.stdout + proc.stderr, proc
                assert b'"predictions"' not in proc.stdout and b"replay_ok=true" not in proc.stdout, proc
            else:
                assert proc.returncode == 0, proc
            return proc.stdout

        invoke("build")
        scenario, panel, report_file, hash_input = [work / f for f in ("scenario", "panel", "report", "hash")]
        scenario.write_text((ROOT / "fixtures/scenario.csv").read_text()
                            .replace("2026-12-18,2,0,2,", "2026-12-17,2,0,1,"))

        def digest_bytes(value):
            hash_input.write_bytes(value)
            return invoke("scenario-digest", hash_input).decode().strip()

        sd = invoke("scenario-digest", scenario).decode().strip()
        schema = json.loads((ROOT / "contracts/pricing.demand-estimation@2.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
        rows = arms()

        def data(rows, kind=KINDS[0]):
            return (
                "pricing.first-party-demand-panel@1\n"
                "scenario_blake3,property,product,currency,price_basis,assignment,train_as_of,"
                "reference_price_minor,target_exposures,model\n"
                f"{sd},hotel-1,standard,EUR,room_night,observational,{CUTOFF},{REFERENCE},{TARGET},{kind}\n"
                "started_at,ended_at,finalized_at,ingested_at,group,price_minor,assigned,kept,"
                "cancelled,nonpurchase,unavailable,unresolved\n"
                + "".join(arm_text(row) + "\n" for row in rows)
            )

        def fit(raw, error=None):
            panel.write_bytes(raw.encode())
            output = invoke("panel", scenario, panel, error=error)
            if not error:
                report = json.loads(output)
                schema_validator.validate(report)
                return report, output

        model_ids = set()
        for model in KINDS:
            raw = data(rows, model)
            report, output = fit(raw)
            slope, se, intercepts, predict, model_loss, baseline_loss, variance = oracle(rows, model)
            assert report["slope_micros"] == micro(slope)
            assert report["window_cluster_slope_se_micros"] == (micro(se) if se is not None else None)
            assert report["within_window_feature_variance_micros"] == micro(variance)
            assert report["holdout"]["brier_micros"] == micro(model_loss)
            assert report["holdout"]["group_rate_baseline_brier_micros"] == micro(baseline_loss)
            assert report["holdout"]["windows"] == 2 and report["training_windows"] == 8
            assert report["training_latest_ingested_at"] == "2026-11-08T04:00:00Z"
            assert report["holdout"]["first_started_at"] == "2026-11-09T01:00:00Z"
            assert report["holdout"]["latest_ingested_at"] == "2026-11-10T04:00:00Z"
            assert report["holdout"]["assigned"] == sum(row[3] for row in rows if row[0] > 8)
            assert report["training_assigned"] == sum(row[3] for row in rows if row[0] <= 8)
            for group in report["groups"]:
                label = group["group"]
                assert group["log_intercept_micros"] == micro(intercepts[label])
                assert group["predictions"] == [
                    {"price_minor": price, "kept_rate_micros": micro(predict(label, price)),
                     "expected_room_nights_milli": round(predict(label, price) * TARGET * 1000)}
                    for price in (8000, 10000, 12500)
                ]
            model_ids.add(report["model_id"])
            report_file.write_bytes(output)
            assert invoke("panel-replay", scenario, panel, report_file, report["id"]) == b"demand_panel_replay_ok=true\n"
            invoke("panel-replay", scenario, panel, report_file, report["model_id"], error="identity or bytes differ")
        assert len(model_ids) == len(KINDS)

        raw = data(rows)
        original, output = fit(raw)
        canonical = raw.splitlines()[2] + "\n" + "".join(arm_text(row) + "\n" for row in rows if row[0] <= 8)
        train_hash = digest_bytes(canonical.encode())
        model_hash = digest_bytes(f"yieldcraft.observational-panel@1\n{train_hash}\n".encode())
        source_hash = digest_bytes(raw.encode())
        assert original["training"] == f"blake3:{train_hash}"
        assert original["exposure"] == f"blake3:{source_hash}"
        assert original["model_id"] == f"blake3:{model_hash}"
        expected_id = digest_bytes(f"pricing.demand-estimation@2\n{model_hash}\n{source_hash}\n".encode())
        assert original["id"] == f"blake3:{expected_id}"

        holdout_change = [row if row[0] <= 8 else (*row[:4], 0, 0, row[3], 0, 0) for row in rows]
        changed, _ = fit(data(holdout_change))
        assert changed["model_id"] == original["model_id"] and changed["id"] != original["id"]
        assert changed["groups"] == original["groups"] and changed["holdout"] != original["holdout"]
        report_file.write_bytes(output)
        invoke("panel-replay", scenario, panel, report_file, original["id"], error="identity or bytes differ")
        changed, _ = fit(raw.replace("\n", "\r\n"))
        assert changed["model_id"] == original["model_id"] and changed["id"] != original["id"]
        # Reverse the training association, preserving design and support. A
        # fit is evidence even when its slope points in an unexpected direction.
        reversed_outcomes = [(*row[:4], row[6], 0, row[4], 0, 0) for row in rows]
        reversed_report, _ = fit(data(reversed_outcomes))
        assert reversed_report["model_id"] != original["model_id"] and reversed_report["slope_micros"] > 0
        assert reversed_report["decision_eligible"] is False
        assert fit(data([r for r in rows if r[0] >= 6]))[0]["window_cluster_slope_se_micros"] is None
        no_response_identification = [row for row in rows if row[2] == 10000]
        single_group = [row for row in rows if row[1] == "early"]
        gap_prices = [row if row[0] <= 8 or row[2] != 10000 else (*row[:2], 11000, *row[3:]) for row in rows]
        assert fit(data(gap_prices))[0]["groups"] == original["groups"]
        maximum = [(day, "early", 8000 + 10 * i, 1_000_000, 600_000 - 200 * i, 0,
                    400_000 + 200 * i, 0, 0)
                   for day in range(6, 10)
                   for i in range(64)]
        maximum_report, _ = fit(data(maximum))
        assert maximum_report["training_assigned"] == 192_000_000
        assert maximum_report["holdout"]["assigned"] == 64_000_000
        assert len(maximum_report["groups"][0]["predictions"]) == 64

        for bad, error in (
            (raw.replace("observational", "randomized"), "observational panel required"),
            (raw.replace(",EUR,", ",USD,"), "currency or price basis mismatch"),
            (raw.replace("2026-11-09T04", "2026-11-21T04"), "invalid or future-dated"),
            (raw.replace("2026-11-08T04", "2026-11-09T04"), "straddles training cutoff"),
            (raw.replace("2026-11-01T04:00:00Z", "2026-11-01T05:00:00Z", 1), "inconsistent clocks"),
            (data(rows[6:12] + rows[:6] + rows[12:]), "ordered and nonoverlapping"),
            (data(rows[:1] + rows[:1] + rows[1:]), "prices must increase"),
            (data([(*row[:2], 7999, *row[3:]) if row[0] == 9 and row[2] == 8000 else row for row in rows]),
             "outside training support"),
            (data([(*row[:1], "later", *row[2:]) if row[0] == 9 and row[1] == "late" else row for row in rows]),
             "outside training support"),
            (data([(*row[:-2], 1, 0) if row == rows[0] else row for row in rows]), "finalized and bookable"),
            (data(no_response_identification), "insufficient overlapping"),
            (data(single_group, KINDS[3]), "needs at least two groups"),
            (data([r for r in rows if r[0] <= 8]), "insufficient overlapping"),
        ):
            fit(bad, error)
        assert not (work / "unused-store").exists()
    print("yieldcraft_demand_panel_ok=true model_oracles=4 temporal_isolation=true typed_replay=true")


if __name__ == "__main__":
    main()
