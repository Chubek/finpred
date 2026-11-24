#!/usr/bin/env python3
"""Compiled frozen pricing cube: fixture, point-in-time evidence and replay."""
import json
from collections import Counter
from itertools import combinations, product
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/competitor"


def csv_row(*fields):
    return ",".join(map(str, fields)) + "\n"


def oracle(quotes, ages, adults, rooms, min_rooms, discount):
    """Independent exhaustive oracle over labeled rooms and child assignments."""
    alternatives = []
    for qid, pool, quantity, qa, qc, amin, amax, nights, cancel, base, fee, tax, rebate in quotes:
        if nights > 2 or cancel != "flexible":
            continue
        for members in combinations(range(len(ages)), qc):
            if all(amin <= ages[i] <= amax for i in members):
                alternatives.append((pool, quantity, qa, members, base + fee + tax - rebate))
    best = None
    for count in range(1, rooms + 1):
        for group in product(alternatives, repeat=count):
            if sum(room[2] for room in group) != adults:
                continue
            if sorted(i for room in group for i in room[3]) != list(range(len(ages))):
                continue
            use = Counter(room[0] for room in group)
            if any(use[room[0]] > room[1] for room in group):
                continue
            price = sum(room[4] for room in group) - (discount if count >= min_rooms else 0)
            if best is None or (price, count) < best:
                best = (price, count)
    return best


def generated(invoke, tmp, sources):
    rng = random.Random(9804)
    snapshots = "hospitality.competitor-snapshot@1\n"
    cells = "\n".join(sources[1].read_text().splitlines()[:2]) + "\n"
    cases = []
    for case in range(1, 25):
        arrival, departure = f"2027-02-{case:02d}", f"2027-02-{case+2:02d}"
        ages = sorted(rng.randrange(18) for _ in range(case % 4))
        adults = 2 + case % 2
        rooms = min(adults, 2 + case % 2)
        capacity = {1: rng.randrange(1, 3), 2: rng.randrange(1, 3)}
        quotes = []
        for qid in range(1, 6):
            pool = 1 + qid % 2
            a, c = rng.randrange(1, 3), rng.randrange(0, 4)
            lo, hi = (0, 17) if c == 0 or qid % 2 else sorted(rng.sample(range(18), 2))
            quotes.append((qid, pool, capacity[pool], a, c, lo, hi,
                           3 if qid == 4 else 2, "nonrefundable" if qid == 5 else "flexible",
                           rng.randrange(200, 501), rng.randrange(15), rng.randrange(10), rng.randrange(20)))
        # Ensure both feasible controls and infeasible randomized cases.
        if case % 5 == 0:
            quotes.append((6, 3, 1, adults, len(ages), 0, 17, 1, "flexible", 900, 0, 0, 0))
        snapshots += csv_row("release", case, case, "oracle", arrival, departure, "EUR",
                             "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                             "2027-01-01T00:00:00Z", 1, 2, 30)
        snapshots += "".join(csv_row("quote", *q) for q in quotes)
        cells += csv_row(case, arrival, departure, "2027-01-01T00:00:00Z", adults,
                         "|".join(map(str, ages)), rooms, "EUR", "flexible", 0, 1, 50000, 1)
        cases.append((ages, adults, quotes, oracle(quotes, ages, adults, rooms, 2, 30)))
    snapshot_file, cell_file = tmp / "random-snapshots", tmp / "random-cells"
    snapshot_file.write_text(snapshots)
    cell_file.write_text(cells)
    response = json.loads(invoke("evaluate", snapshot_file, cell_file, sources[2]))
    results = response["cube"]["cells"]
    assert len(results) == len(cases)
    assert any(case[3] is None for case in cases) and any(case[3] is not None for case in cases)
    for result, (ages, adults, quotes, expected) in zip(results, cases, strict=True):
        if expected is None:
            assert result["status"] == "no_feasible_bundle", result
            continue
        price, count = expected
        assert result["recommendation_minor"] == price, (result, expected)
        comparable, = result["comparables"]
        assert comparable["total_minor"] == price and len(comparable["rooms"]) == count, comparable
        entries = comparable["rooms"]
        used = Counter(room["pool"] for room in entries)
        guests = []
        assert sum(room["adults"] for room in entries) == adults
        for room in entries:
            _, pool, qty, a, c, lo, hi, _, _, base, fee, tax, rebate = quotes[room["quote"] - 1]
            children = [i for i in range(len(ages)) if room["child_mask"] & (1 << i)]
            assert len(children) == c and all(lo <= ages[i] <= hi for i in children)
            assert room["pool"] == pool and used[pool] <= qty and room["adults"] == a
            assert room["gross_minor"] == base + fee + tax - rebate
            guests.extend(children)
        assert sorted(guests) == list(range(len(ages)))


def variants(invoke, tmp, sources):
    original = sources[1].read_text().splitlines()
    base_cell = original[2].split(",")
    cell_file, policies = tmp / "variants", tmp / "strategies"
    policies.write_text(sources[2].read_text() + (
        "3,power,2000,8000,60,3,0,type7,0,off,0,22000,1000000\n"
        "4,exponential,7000,9000,60,2,0,weighted,0,bps,10000,0,1000000\n"
        "5,piecewise,5000,3000,60,29,7500,type7,0,off,0,0,1000000\n"
    ))
    cells = []
    for id_, changes in enumerate((
        {12: 3}, {12: 4}, {12: 5}, {9: 0}, {7: "USD"}, {8: "nonrefundable"}, {8: "any"},
    ), 1):
        row = base_cell.copy()
        row[0] = id_
        for field, value in changes.items():
            row[field] = value
        cells.append(csv_row(*row))
    cell_file.write_text("\n".join(original[:2]) + "\n" + "".join(cells))
    report = json.loads(invoke("evaluate", sources[0], cell_file, policies))["cube"]
    p, exp, piece, stale, fx, nonrefund, mixed = report["cells"]
    assert (p["target_bps"], p["recommendation_minor"], p["reason"]) == (2677, 22000, "guardrail_adjustment")
    assert (exp["target_bps"], exp["intended_minor"], exp["recommendation_minor"]) == (7644, 24000, 17500)
    assert exp["selected_bps"] == 0 and exp["reason"] == "lower_percentile_shortcut"
    assert (piece["target_bps"], piece["recommendation_minor"]) == (7500, 22500)
    assert stale["status"] == "stale_observations" and fx["status"] == "no_observations"
    assert nonrefund["status"] == "insufficient_evidence"
    assert [entry["total_minor"] for entry in nonrefund["comparables"]] == [1000]
    assert [entry["total_minor"] for entry in mixed["comparables"]] == [1000, 21000, 24000]
    assert report["market_evaluations"] == 5


def capacity(invoke, tmp, sources):
    rows = ["hospitality.competitor-snapshot@1\n"]
    for i in range(64):
        rows.append(csv_row("release", 999999999900 + i, 999999999900 + i, "p" * 32,
                            "2027-02-01", "2027-02-03", "EUR", "2027-01-01T00:00:00Z",
                            "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z", 10000, 0, 0))
        rows.append(csv_row("quote", 999999999999, 999999999999, 4, 1, 0, 0, 17, 1,
                            "flexible", 10**12, 0, 0, 0))
    snapshot, cells = tmp / "capacity-snapshots", tmp / "capacity-cells"
    snapshot.write_text("".join(rows))
    header = "\n".join(sources[1].read_text().splitlines()[:2]) + "\n"
    requests = [
        csv_row(999999999900 + i, "2027-02-01", "2027-02-03", f"2027-01-01T00:01:{i:02d}Z",
                4, "", 4, "EUR", "flexible", 0, 64, 50000, 1)
        for i in range(49)
    ]
    cells.write_text(header + "".join(requests[:48]))
    rendered = invoke("evaluate", snapshot, cells, sources[2], timeout=90)
    report = json.loads(rendered)
    assert report["cube"]["market_evaluations"] == 48
    assert all(len(c["comparables"]) == 64 for c in report["cube"]["cells"])
    assert all(c["comparables"][0]["total_minor"] == 4 * 10**12 for c in report["cube"]["cells"])
    assert invoke("replay", report["cube_id"], timeout=90) == rendered
    cells.write_text(header + "".join(requests))
    invoke("evaluate", snapshot, cells, sources[2], error="expected 1..48 cells")


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-competitor-") as tmp:
        tmp = Path(tmp)
        home = tmp / "store"
        env = {**os.environ, "FINPRED_CUBE_HOME": str(home)}

        def invoke(*args, error=None, overrides=None, trace=None, timeout=30):
            prefix = [] if trace is None else ["strace", "-f", "-e", "trace=network", "-o", trace, "--"]
            p = subprocess.run(
                [*prefix, "./bin/finpred", "cube", *map(str, args)], cwd=ROOT,
                env={**env, **(overrides or {})}, capture_output=True, timeout=timeout,
            )
            if error is not None:
                assert p.returncode != 0 and error in p.stderr.decode(), p
                assert not p.stdout, p
            else:
                assert p.returncode == 0, p
            if trace is not None:
                assert "(" not in trace.read_text(), trace.read_text()
            return p.stdout

        sources = [FIXTURES / f"{kind}.csv" for kind in ("snapshots", "cells", "policies")]
        staged = [Path(shutil.copyfile(source, tmp / source.name)) for source in sources]
        rendered = invoke("evaluate", *staged)
        report = json.loads(rendered)
        assert report["cube_id"] == "588f6bcfcf9128268cd1f81bcc11f0b855828edfd86804fc91c6a44217c211d2"
        for source in staged:
            source.unlink()
        result = report["cube"]
        schema = json.loads((ROOT / "contracts/pricing.competitor-cube@1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(result)
        assert result["published"] is False
        a, b, c, d, e = result["cells"]
        assert [entry["total_minor"] for entry in a["comparables"]] == [17500, 21000, 24000]
        assert [room["quote"] for room in a["comparables"][0]["rooms"]] == [2, 3]
        assert a["recommendation_minor"] == 21000 and a["reason"] == "target_percentile"
        assert b["target_bps"] == 6208 and b["recommendation_minor"] == 21000
        assert [entry["release"] for entry in c["comparables"]] == [1, 3]
        assert c["status"] == "insufficient_evidence" and c["recommendation_minor"] is None
        assert d["status"] == "no_observations" and not d["comparables"]
        assert e["status"] == "budget_exhausted" and not e["comparables"]
        assert result["market_evaluations"] == 4

        def snapshot():
            return [(p, p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(home.rglob("*.txt"))]

        before = snapshot()
        network_traced = bool(shutil.which("strace"))
        assert invoke("replay", report["cube_id"], trace=tmp / "replay.trace" if network_traced else None) == rendered
        assert snapshot() == before
        assert invoke("evaluate", *sources) == rendered
        assert snapshot() == before
        invoke("replay", "0" * 64, error="missing snapshot")
        invoke("replay", "not-a-digest", error="malformed BLAKE3 digest")
        manifest = home / f"artifacts/blake3-{report['cube_id']}.txt"
        parent = home / f"artifacts/blake3-{manifest.read_text().splitlines()[1]}.txt"
        original = parent.read_bytes()
        parent.write_bytes(original + b"\n")
        damaged = snapshot()
        invoke("replay", report["cube_id"], error="snapshot digest mismatch")
        assert snapshot() == damaged
        parent.write_bytes(original)
        for kind, initial, replacement, diagnostic in (
            (0, "quote,2,1,1,", "quote,2,1,2,", "inconsistent shared pool quantity"),
            (0, "release,4,102,demo,", "release,4,102,other,", "assigned to multiple providers"),
            (0, "2027-01-02T00:00:00Z", "2027-01-01T12:00:00Z", "ambiguous release"),
            (0, "2027-01-01T12:01:00Z", "2027-01-01T11:01:00Z", "invalid release"),
            (0, ",10000,2,500", ",10000,2,50000", "bundle discount not supported"),
            (0, ",1000,0,0,0", ",1000,0,0,1001", "invalid quote"),
            (1, ",5|10,", ",10|5,", "unsorted child ages"),
            (1, ",10000,1", ",10000,999", "unknown cell policy"),
            (2, ",minor,1500,0,1000000", ",minor,1500,1000001,1000000", "invalid target"),
        ):
            changed = tmp / "invalid"
            changed.write_text(sources[kind].read_text().replace(initial, replacement, 1))
            paths = sources.copy()
            paths[kind] = changed
            unchanged = snapshot()
            invoke("evaluate", *paths, error=diagnostic)
            assert snapshot() == unchanged
        invoke("publish", error="usage:")
        invoke("evaluate", *sources, error="capability denied", overrides={"FINPRED_MODE": "execution"})
        generated(invoke, tmp, sources)
        variants(invoke, tmp, sources)
        capacity(invoke, tmp, sources)
        print(f"competitor_cube_ok=true fixture={report['cube_id']} oracle_cases=24 malformed_cases=9 "
              f"policy_variants=7 capacity=48x64 network_traced={int(network_traced)}")


if __name__ == "__main__":
    main()
