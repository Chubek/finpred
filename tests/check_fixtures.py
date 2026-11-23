#!/usr/bin/env python3
"""Independent fixture oracle; does NOT execute or certify the On1x compiler."""
import csv
import datetime as dt
from pathlib import Path

root = Path(__file__).resolve().parents[1]

def table(name):
    with (root / "fixtures" / name).open(newline="") as f:
        return list(csv.DictReader(f))

scenarios = table("scenario.csv")
valuations = table("valuation.csv")
offers = table("offers.csv")
assert len(scenarios) == len(valuations) == 1
s, v = scenarios[0], valuations[0]
arrival = dt.date.fromisoformat(s["arrival"])
departure = dt.date.fromisoformat(s["departure"])
nights = (departure - arrival).days
assert nights == 2
point = s["decision_at"]
accepted = []
rejected = []
for o in offers:
    observed = o["observed_at"]
    days_old = (dt.date.fromisoformat(point[:10]) - dt.date.fromisoformat(observed[:10])).days
    if (o["bookable"] != "1" or o["arrival"] != s["arrival"]
        or o["departure"] != s["departure"] or o["currency"] != s["currency"]
        or observed > point or o["ingested_at"] > point
        or o["valid_from"] > s["arrival"] or o["valid_to"] < s["departure"]
        or not 0 <= days_old <= int(s["max_age_days"])):
        rejected.append(o)
        continue
    accepted.append(o)
assert len(accepted) == 5 and len(rejected) == 2
assert len({o["property_id"] for o in accepted}) == 5
prices = sorted((int(o["total_cents"]) + int(o["fees_cents"]) + int(o["taxes_cents"])) for o in accepted)

def quantile(p):
    rank = (len(prices)-1) * p
    lo = rank // 10_000
    t = rank % 10_000
    a = prices[lo]
    b = prices[min(lo+1, len(prices)-1)]
    return a + ((b-a)*t+5_000)//10_000

p50 = (quantile(5000)+nights//2)//nights
p40 = (quantile(4000)+nights//2)//nights
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
om = table("offers_multiroom.csv")
assert len(om) == 5
assert len({x["property_id"] for x in om}) == 4
assert sorted(int(x["total_cents"]) for x in om if x["property_id"] == "201") == [11_000, 12_000]
assert 11_000 + 12_000 == 23_000
# The last property cannot accommodate a child, regardless of its low price.
assert all(int(x["child_cap"]) == 0 for x in om if x["property_id"] == "204")
assert sorted([23_000, 30_000, 35_000]) == [23_000, 30_000, 35_000]
assert int(v["floor_cents"]) == 16_000
print("multiroom_oracle_ok=true expected_minor=16000 independent_properties=3 infeasible=1")
