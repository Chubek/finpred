#!/usr/bin/env python3
"""Validate persisted v1 envelopes in a test FINPRED_HOME (requires jsonschema>=4).

Run after successful fixture runs, before corruption tests:
    python3 tests/validate_runtime_json.py "$FINPRED_HOME"
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from normalized_oracle import from_csv

try:
    from jsonschema import Draft202012Validator, ValidationError
except ImportError:
    sys.exit("validate_runtime_json requires Python package jsonschema>=4")


ROOT = Path(__file__).resolve().parents[1]
SCENARIO, OFFER, VALUATION, REC = (
    "hospitality.scenario", "hospitality.offer", "pricing.valuation", "pricing.recommendation"
)
LINEAGE_POLICY = """finpred-run-lineage@2
engine=finpred.yieldcraft-engine@1
mode=recommendation
strategy=yieldcraft.percentile@1
graph=yieldcraft.fixed-graph@1
node=0,input,none,hospitality.scenario@1,read
node=1,source,hospitality.scenario@1,hospitality.offer@1,read
node=2,transform,hospitality.offer@1,hospitality.offer@1,pure
node=3,algorithm,hospitality.offer@1,pricing.distribution@1,pure
node=4,strategy,pricing.distribution@1,pricing.recommendation@1,pure
node=5,gate,pricing.recommendation@1,pricing.recommendation@1,pure
node=6,output,pricing.recommendation@1,pricing.recommendation@1,record
model=none
matcher=yieldcraft.asof-whole-stay-property-min@1
quantile=yieldcraft.type7-stay-half-up-night-half-up@1
curve=yieldcraft.p40-p75-linear-quadratic-90d@1
shortcut=yieldcraft.p40-strict-saving@1
guardrail=yieldcraft.floor-cap-movement-intersection@1
"""


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def reject_number(token):
    # Draft 2020-12 accepts 1.0 as an integer; these contracts require integer tokens.
    raise ValueError(f"non-integer JSON number: {token}")


def validate(home):
    validators = {}
    for kind in (SCENARIO, OFFER, VALUATION, REC):
        schema = json.loads((ROOT / "contracts" / f"{kind}@1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema)

    artifacts = home / "artifacts"
    excluded = set()
    expected = set()
    recommendations = {}
    lineages = {}
    manifests = sorted((home / "runs").glob("*.txt"))
    if not manifests:
        raise ValueError(f"{home}: no persisted run manifests")
    for manifest in manifests:
        text = manifest.read_bytes().decode("ascii")
        if not re.fullmatch(r"finpred-run@[12](,[0-9a-f]{64}){6}\n", text
                            ) or not re.fullmatch("[0-9a-f]{64}", manifest.stem):
            raise ValueError(f"{manifest}: invalid manifest")
        version, sd, od, vd, strategy, rec, trace = text[:-1].split(",")
        paths = [artifacts / f"blake3-{d}.txt" for d in (sd, od, vd, strategy, rec, trace)]
        for path in paths:
            if not path.is_file():
                raise ValueError(f"{manifest}: missing artifact {path.name}")
        # Every object except the referenced raw snapshots and trace must be JSON.
        excluded.update((paths[0], paths[1], paths[2], paths[3], paths[5]))
        rows = {SCENARIO: [], VALUATION: [], OFFER: []}
        for kind, digest, path in zip((SCENARIO, OFFER, VALUATION), (sd, od, vd), paths):
            with path.open(encoding="ascii", newline="") as source:
                for row in csv.DictReader(source):
                    if kind == OFFER:
                        ident = f"property:{int(row['property_id'])}:room:{int(row['room_id'])}"
                    elif kind == SCENARIO:
                        ident = f"scenario:{int(row['scenario_id'])}"
                    else:
                        ident = f"valuation:{int(row['valuation_id'])}"
                    payload = json.dumps(from_csv(kind, row), sort_keys=True)
                    key = (kind, ident, (f"blake3:{digest}",), payload)
                    expected.add(key)
                    rows[kind].append(key)
        ident = f"recommendation:{manifest.stem}"
        expected.add((REC, ident, tuple(f"blake3:{d}" for d in (sd, od, vd)), None))
        recommendations[ident] = (paths[4], f"blake3:{strategy}")
        if version == "finpred-run@2":
            lineage = artifacts / f"blake3-{manifest.stem}.txt"
            excluded.add(lineage)
            lineages[lineage] = (sd, od, vd, strategy, rows)
            suffix = f"lineage_blake3={manifest.stem}\n".encode("ascii")
            if not paths[5].read_bytes().endswith(suffix):
                raise ValueError(f"{manifest}: trace does not link to lineage")

    seen = {}
    counts = Counter()
    for path in sorted(set(artifacts.iterdir()) - excluded):
        try:
            match = re.fullmatch(r"blake3-([0-9a-f]{64})\.txt", path.name)
            if not match:
                raise ValueError("noncanonical object filename")
            obj = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=unique_keys,
                             parse_float=reject_number, parse_constant=reject_number)
            kind = obj["kind"]
            validators[kind].validate(obj)
            provenance = obj["metadata"]["provenance"]
            ident = obj["id"]
            metadata = obj["metadata"]
            payload = None if kind == REC else json.dumps(
                (obj["data"], metadata["times"], metadata["units"]), sort_keys=True)
            key = (kind, ident, tuple(provenance["source_artifacts"]), payload)
            if key not in expected:
                raise ValueError(f"unexpected ID, source artifacts or normalized payload for {kind} {ident}")
            if kind == REC and recommendations[ident] != (path, provenance["strategy_digest"]):
                raise ValueError(f"recommendation or strategy digest differs from manifest for {ident}")
            if key in seen:
                raise ValueError(f"duplicate representation of {kind} {ident}")
            seen[key] = match[1]
            counts[kind] += 1
        except ValidationError as e:
            raise ValueError(f"{path}:{e.json_path}: {e.message}") from e
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"{path}: {e}") from e
    if missing := expected - seen.keys():
        raise ValueError(f"missing {len(missing)} envelope(s), first: {min(missing)}")
    for path, (sd, od, vd, strategy, rows) in lineages.items():
        s, = rows[SCENARIO]
        v, = rows[VALUATION]
        parents = (f"raw_scenario={sd}\nraw_offers={od}\nraw_valuation={vd}\nraw_strategy={strategy}\n"
                   f"normalized_scenario={seen[s]}\nnormalized_valuation={seen[v]}\n"
                   f"offer_count={len(rows[OFFER])}\n")
        offers = "".join(f"normalized_offer={seen[key]}\n" for key in rows[OFFER])
        if path.read_bytes() != (LINEAGE_POLICY + parents + offers).encode("ascii"):
            raise ValueError(f"{path}: lineage differs from policy and ordered source/contract IDs")
    for kind in validators:
        if not counts[kind]:
            raise ValueError(f"no emitted {kind} envelopes")
    print("runtime_json_ok=true", *(f"{kind}={counts[kind]}" for kind in validators))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path, help="store from successful fixture runs")
    try:
        validate(parser.parse_args().home)
    except (OSError, KeyError, ValueError) as e:
        sys.exit(str(e))
