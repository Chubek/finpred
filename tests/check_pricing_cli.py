#!/usr/bin/env python3
"""Compiled Yieldcraft CLI: assert the decision, evidence counts and pre-clamp values."""
import csv
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def fixture(table):
    with (ROOT / "fixtures" / f"{table}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def room(property_id, room_id, base, **fields):
    return {**fixture("offers")[0], "property_id": property_id, "room_id": room_id,
            "total_cents": base, "fees_cents": 0, "taxes_cents": 0, **fields}


def check(name, *, scenario=None, valuation=None, offers=None, price=None,
          reason="target_percentile", trace=None, error=None, tz="UTC"):
    tables = {"scenario": [{**fixture("scenario")[0], **(scenario or {})}],
              "valuation": [{**fixture("valuation")[0], **(valuation or {})}],
              "offers": fixture("offers") if offers is None else offers}
    with tempfile.TemporaryDirectory(prefix="finpred-pricing-") as tmp:
        home = Path(tmp) / "store"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FINPRED_") or k == "FINPRED_EXE"}
        env.update(FINPRED_HOME=str(home), TZ=tz)
        for table, rows in tables.items():
            out = Path(tmp) / f"{table}.csv"
            with out.open("w", newline="") as f:
                writer = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            env[f"FINPRED_{table.upper()}"] = str(out)
        proc = subprocess.run([ROOT / "bin/finpred", "run"], env=env, cwd=ROOT,
                              text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=60)
        lines = proc.stdout.splitlines()
        if error is None:
            expected = {f"recommendation_minor={price}", f"reason={reason}", "published=false"}
            ok = proc.returncode == 0 and expected.issubset(lines)
        else:
            ok = (proc.returncode > 0 and error in proc.stdout and
                  not any(line.startswith("recommendation_minor=") for line in lines) and
                  not list(home.rglob("*.txt")))
        if not ok:
            raise RuntimeError(f"{name}: exit={proc.returncode}, output:\n{proc.stdout}")
        if trace:
            digest = dict(line.split("=", 1) for line in lines if "=" in line)["trace_digest"]
            evidence = (home / "artifacts" / f"blake3-{digest}.txt").read_text()
            missing = {f"{k}={v}" for k, v in trace.items()} - set(evidence.splitlines())
            if missing:
                raise RuntimeError(f"{name}: missing {missing} in trace:\n{evidence}")


def main():
    cases = 0

    def run(name, **kwargs):
        nonlocal cases
        check(name, **kwargs)
        cases += 1

    no_shortcut = {"shortcut_cents": 0}
    run("exact shortcut threshold", valuation={"shortcut_cents": 400}, price=17500)
    for curve, bps, price in [("linear", 5011, 17507), ("quadratic", 4292, 17217)]:
        run(curve, scenario={"target_bps": 0, "curve": curve}, valuation=no_shortcut,
            price=price, trace={"intended_bps": bps})
    for field, bound, price in [("cap_cents", 17000, 17000), ("max_move_cents", 200, 17300)]:
        run(f"{field} after shortcut", valuation={field: bound}, price=price,
            reason="guardrail_adjustment", trace={"selected_bps": 4000, "candidate_nightly_minor": 17100})
    run("upper movement", valuation={"current_cents": 16600, "max_move_cents": 100},
        price=16700, reason="guardrail_adjustment")
    run("empty guardrail intersection", valuation={"floor_cents": 20000, "max_move_cents": 0},
        error="guardrail")

    sample = {"min_properties": 3}
    # Four cheap rooms at A would push a room-weighted median below B.
    # The cheapest unit at A deliberately comes last.
    skewed = [room(1, i, gross) for i, gross in enumerate([23000, 22000, 21000, 20000], 1)]
    skewed += [room(2, 1, 32000, taxes_cents=2500, fees_cents=1500), room(3, 1, 44000)]
    # 2^4-1 nonempty subsets at A, one each at B and C. A partial search
    # must not issue a price even if it found a feasible bundle already.
    for name, ordered in [("biased inventory", skewed), ("permuted inventory", skewed[::-1])]:
        run(name, scenario={**sample, "search_budget": 17}, valuation=no_shortcut, offers=ordered,
            price=18000, trace={"independent_properties": 3, "lower_nightly_minor": 16400,
                                "search_subsets": 17})
    run("one node short", scenario={**sample, "search_budget": 16}, offers=skewed, error="budget")
    run("one property with many rooms", scenario=sample, offers=skewed[:4], error="insufficient_evidence")
    many = [room(1, i, 20000) for i in range(1, 11)] + skewed[-2:]
    run("ten rooms at one property", scenario=sample, offers=many, valuation=no_shortcut,
        price=18000, trace={"search_subsets": 1025, "independent_properties": 3})
    run("room inventory limit", scenario=sample, offers=[room(1, i, 10) for i in range(1, 12)],
        error="more than 10")
    run("duplicate room", offers=[*skewed, skewed[0]], error="duplicate")

    party = {**sample, "children": 2}
    # Only allocation A=(1 adult,2 children), B=(1 adult,0 children) works.
    # Property 4 has ample aggregate capacity but cannot fit its children in
    # room A alongside the required adult. Property 5 could work only if
    # the single inventory unit were reused.
    rooms = [room(1, 1, 17000, adult_cap=1, child_cap=2, total_cap=3),
             room(1, 2, 19000, adult_cap=1, total_cap=1),
             room(2, 1, 30000, child_cap=2, total_cap=4),
             room(3, 1, 40000, child_cap=2, total_cap=4),
             room(4, 1, 100, child_cap=2, total_cap=2),
             room(4, 2, 100, total_cap=3),
             room(5, 1, 500, adult_cap=1, child_cap=1)]
    run("joint adult/child assignment", scenario=party, offers=rooms, valuation=no_shortcut,
        price=18000, trace={"independent_properties": 3, "infeasible_properties": 2})
    run("required second room unavailable", scenario={**party, "max_rooms": 1}, offers=rooms,
        error="insufficient_evidence")
    # Both the two-room bundle at A (36000) and one larger room fit. Adding
    # mandatory fees changes which is cheaper without changing base prices.
    for fee, price in [(0, 17000), (4000, 18000)]:
        run(f"compare feasible bundles after fees {fee}", scenario=party, valuation=no_shortcut,
            offers=rooms + [room(1, 3, 34000, fees_cents=fee, child_cap=2, total_cap=4)],
            price=price, trace={"independent_properties": 3})
    # Full 81-state occupancy table: four mixed rooms are needed at each
    # property. A genuinely free bundle is feasible evidence, not missing.
    maximum_party = [room(p, i, base, child_cap=2, total_cap=4)
                     for p, base in enumerate([0, 0, 10000], 1) for i in range(1, 5)]
    run("zero-price evidence at maximum occupancy",
        scenario={**sample, "adults": 8, "children": 8, "max_rooms": 4},
        offers=maximum_party, valuation={"floor_cents": 0, "current_cents": 0},
        price=0, trace={"independent_properties": 3, "infeasible_properties": 0})

    # The CLI reserves p=0 for its lead curve; the lowest pinned target is P40.
    # At P75 the two tied central/top values must interpolate to exactly the tie.
    tied = [room(p, 1, v) for p, v in enumerate([40000, 30000, 40000], 1)]
    for p, price in [(4000, 19000), (7500, 20000), (10000, 20000)]:
        run(f"type7 tie/end {p}", scenario={**sample, "target_bps": p}, offers=tied,
            valuation=no_shortcut, price=price, trace={"selected_bps": p})
    run("unique P100 maximum", scenario={**sample, "target_bps": 10000},
        offers=skewed, valuation=no_shortcut, price=22000, trace={"selected_bps": 10000})

    # Half-cent Type 7 at P75 => 34001 whole-stay cents, then a second
    # half-cent => 17001/night. Truncation at either stage fails.
    for top, price in [(34001, 17001), (34000, 17000)]:
        offers = [room(1, 1, 30000), room(2, 1, 34000), room(3, 1, top)]
        run(f"two half-up stages {top}", scenario={**sample, "target_bps": 7500},
            offers=offers, valuation=no_shortcut, price=price)
    # Rounding each room to a nightly rate before the quantile gives 17000
    # instead of 17001 for the interior P60 rank (1.2).
    run("interpolate whole stay before division", scenario={**sample, "target_bps": 6000},
        offers=[room(1, 1, 30000), room(2, 1, 34000), room(3, 1, 34004)],
        valuation=no_shortcut, price=17001)

    limit = 10**12
    # Force four full-price rooms per comparable. At P75 the rank lies
    # between whole-stay totals 8 and 4e12, exercising the large product
    # during interpolation without a final clamp masking a wrong result.
    expensive = [room(p, i, gross-2, taxes_cents=1, fees_cents=1, adult_cap=1, total_cap=1)
                 for p, gross in enumerate([2, 2, limit], 1) for i in range(1, 5)]
    run("maximum bundle and interpolation", scenario={**sample, "adults": 4, "max_rooms": 4,
                                                       "target_bps": 7500}, offers=expensive,
        valuation={"current_cents": limit, "cap_cents": limit, "max_move_cents": limit,
                   "shortcut_cents": 0}, price=limit, reason="guardrail_adjustment",
        trace={"intended_nightly_minor": limit + 2, "lower_nightly_minor": 4})
    run("gross exceeds limit by one", offers=[room(1, 1, limit-1, taxes_cents=1, fees_cents=1)],
        error="gross price")

    # 2027-03-28 begins daylight saving time in Europe/Berlin: 47 elapsed
    # hours, but exactly two civil nights. Both curves saturate past 90 days.
    stay = {"arrival": "2027-03-27", "departure": "2027-03-29"}
    for curve in ("linear", "quadratic"):
        run(f"DST and lead saturation {curve}", scenario={**sample, **stay, "target_bps": 0, "curve": curve},
            offers=[room(i, 1, gross, **stay, valid_to=stay["departure"])
                    for i, gross in enumerate([30000, 34000, 40000], 1)],
            valuation=no_shortcut, price=18500, tz="Europe/Berlin",
            trace={"intended_bps": 7500, "nights": 2})
    same_day = {"arrival": "2026-11-20", "departure": "2026-11-22"}
    for curve in ("linear", "quadratic"):
        run(f"zero lead {curve}", scenario={**sample, **same_day, "target_bps": 0, "curve": curve},
            offers=[{**o, **same_day} for o in skewed], valuation=no_shortcut, price=16400,
            trace={"intended_bps": 4000})
    print(f"pricing_cli_ok=true cases={cases}")


if __name__ == "__main__":
    main()
