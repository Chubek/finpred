#!/usr/bin/env python3
"""Independent fixture oracle; does NOT execute or certify the On1x compiler."""
import csv
import datetime as dt
from itertools import product
from pathlib import Path

root = Path(__file__).resolve().parents[1]

def table(name):
    with (root / "fixtures" / name).open(newline="") as f:
        return list(csv.DictReader(f))

def eligible(o, scenario):
    point = scenario["decision_at"]
    observed = o["observed_at"]
    days_old = (dt.date.fromisoformat(point[:10]) - dt.date.fromisoformat(observed[:10])).days
    return (o["bookable"] == "1" and o["arrival"] == scenario["arrival"]
            and o["departure"] == scenario["departure"] and o["currency"] == scenario["currency"]
            and observed <= o["ingested_at"] <= point
            and o["valid_from"] <= scenario["arrival"] and o["valid_to"] >= scenario["departure"]
            and 0 <= days_old <= int(scenario["max_age_days"]))

scenarios = table("scenario.csv")
valuations = table("valuation.csv")
offers = table("offers.csv")
assert len(scenarios) == len(valuations) == 1
s, v = scenarios[0], valuations[0]
arrival = dt.date.fromisoformat(s["arrival"])
departure = dt.date.fromisoformat(s["departure"])
nights = (departure - arrival).days
assert nights == 2
accepted = [o for o in offers if eligible(o, s)]
assert len(accepted) == 5 and len(offers) - len(accepted) == 2
assert len({o["property_id"] for o in accepted}) == 5
prices = sorted((int(o["total_cents"]) + int(o["fees_cents"]) + int(o["taxes_cents"])) for o in accepted)

def quantile(prices, p):
    rank = (len(prices)-1) * p
    lo = rank // 10_000
    t = rank % 10_000
    a = prices[lo]
    b = prices[min(lo+1, len(prices)-1)]
    return a + ((b-a)*t+5_000)//10_000

p50 = (quantile(prices, 5000)+nights//2)//nights
p40 = (quantile(prices, 4000)+nights//2)//nights
assert (p50, p40) == (17_500, 17_100), (p50, p40)
chosen = p40 if p50-p40 < int(v["shortcut_cents"]) else p50
low = max(int(v["floor_cents"]), int(v["current_cents"])-int(v["max_move_cents"]))
high = min(int(v["cap_cents"]), int(v["current_cents"])+int(v["max_move_cents"]))
final = max(low, min(high, chosen))
assert final == 17_100
print("oracle_ok=true price_minor=17100 independent_properties=5 rejected=2")

# Second fixture exercises two-room matching, one property per comparable,
# infeasible child allocations and a hard floor that overrides the percentile.
sm = table("scenario_multiroom.csv")[0]
om = [o for o in table("offers_multiroom.csv") if eligible(o, sm)]
assert len(om) == 5
assert len({x["property_id"] for x in om}) == 4
# Enumerate assignments of individual guests on this tiny fixture. This is
# independent of the On1x room-subset and dynamic-programming matcher.
adults, children = int(sm["adults"]), int(sm["children"])
cheapest = {}
for prop in {o["property_id"] for o in om}:
    rooms = [o for o in om if o["property_id"] == prop]
    assert len({o["room_id"] for o in rooms}) == len(rooms)
    for assignment in product(range(len(rooms)), repeat=adults + children):
        used = set(assignment)
        if len(used) > int(sm["max_rooms"]):
            continue
        for i in used:
            a = assignment[:adults].count(i)
            c = assignment[adults:].count(i)
            if not (1 <= a <= int(rooms[i]["adult_cap"]) and
                    c <= int(rooms[i]["child_cap"]) and a+c <= int(rooms[i]["total_cap"])):
                break
        else:
            gross = sum(int(rooms[i][k]) for i in used
                        for k in ("total_cents", "fees_cents", "taxes_cents"))
            cheapest[prop] = min(gross, cheapest.get(prop, gross))
assert cheapest == {"201": 23_000, "202": 30_000, "203": 35_000}, cheapest
totals = sorted(cheapest.values())
stay = (dt.date.fromisoformat(sm["departure"]) - dt.date.fromisoformat(sm["arrival"])).days
intended = (quantile(totals, int(sm["target_bps"])) + stay//2)//stay
lower = (quantile(totals, 4000) + stay//2)//stay
candidate = lower if intended - lower < int(v["shortcut_cents"]) else intended
result = max(low, min(high, candidate))
assert (intended, lower, candidate, result) == (15_000, 14_300, 15_000, 16_000)
print(f"multiroom_oracle_ok=true expected_minor={result} independent_properties={len(totals)} infeasible=1")
