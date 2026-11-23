#!/usr/bin/env python3
"""Generate the four descriptive v1 JSON Schemas from one source list."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]

s = lambda: {"type": "string", "minLength": 1}
i = lambda low=0, high=1_000_000_000_000: {"type": "integer", "minimum": low, "maximum": high}
t = lambda: {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
d = lambda: {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}
q = lambda: {"type": "string", "const": "EUR"}

def item(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

kinds = {
  "hospitality.scenario": {
    "decision_at": t(), "arrival": d(), "departure": d(), "nights": i(1,365),
    "adults": i(1,8), "children": i(0,8), "max_rooms": i(1,4),
    "min_properties": i(3,32), "target_bps": i(0,10000),
    "curve": {"enum": ["linear","quadratic"]}, "max_age_days": i(0,365), "search_budget": i(1,1000000),
  },
  "hospitality.offer": {
    "arrival":d(), "departure":d(), "valid_from":d(), "valid_to":d(),
    "adult_capacity":i(1,8), "child_capacity":i(0,8), "total_capacity":i(1,16),
    "guest_payable_cents":i(), "bookable":{"type":"boolean"},
  },
  "pricing.valuation": {
    "current_cents":i(), "floor_cents":i(), "cap_cents":i(),
    "max_move_cents":i(), "shortcut_cents":i(),
  },
  "pricing.recommendation": {
    "price_minor":i(),"intended_percentile_bps":i(4000,10000),"selected_percentile_bps":i(4000,10000),
    # Before guardrails, a one-night four-room bundle can cost 4 x 10^12 cents.
    "intended_minor":i(0,4*10**12),"lower_minor":i(0,4*10**12),"candidate_minor":i(0,4*10**12),
    "independent_properties":i(3,512),"reason": {"enum":["target_percentile","lower_percentile_shortcut","guardrail_adjustment"]},
    "published":{"const":False},"mode":{"const":"recommendation"},
  }
}
for kind, props in kinds.items():
    parent_count = 3 if kind == "pricing.recommendation" else 1
    metadata = item({
      "provenance": item({
         "source_artifacts": {"type":"array","items":{"type":"string","pattern":"^blake3:[0-9a-f]{64}$"},"minItems":parent_count,"maxItems":parent_count},
         **({"strategy":{"const":"yieldcraft.percentile@1"},"strategy_digest":{"type":"string","pattern":"^blake3:[0-9a-f]{64}$"}} if kind == "pricing.recommendation" else {}),
      }),
      "times": item({"observed_at":t(),"ingested_at":t()}),
      "units": item({"currency":q(),"price_basis":{"const":"whole_stay" if kind.startswith("hospitality.") else "room_night"}}),
      "quality": item({"status":{"const":"validated"},"evidence":{"const":"scenario_comparables" if kind == "pricing.recommendation" else "csv_import"}}),
    })
    schema = {
      "$schema":"https://json-schema.org/draft/2020-12/schema", "$id":f"https://example.invalid/finpred/{kind}@1.schema.json",
      "title":f"FinPRED {kind}@1","description":"Schema complements the On1x semantic validators; not a substitute for temporal/monetary validation.",
      "type":"object","properties":{
        "mulib":{"const":"1.0"},"kind":{"const":kind},"schema_version":{"const":"1.0"},
        "id":s(),"metadata":metadata,"data":item(props),
      },"required":["mulib","kind","schema_version","id","metadata","data"],"additionalProperties":False,
    }
    (root / "contracts" / f"{kind}@1.schema.json").write_text(json.dumps(schema,indent=2,sort_keys=True)+'\n')
print('schemas_created=4')
