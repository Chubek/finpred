#!/usr/bin/env python3
"""Check read-only evidence against exhaustive guest assignments on tiny inputs."""
import csv
from datetime import date
from itertools import product
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from check_store import ENV, FIXTURES, ROOT, invoke, tree


def eligibility(s, o):
    at = s["decision_at"]
    age = (date.fromisoformat(at[:10]) - date.fromisoformat(o["observed_at"][:10])).days
    for condition, reason in (
        (o["bookable"] == "0", "not_bookable"),
        (any(o[k] != s[k] for k in ("arrival", "departure")), "stay_mismatch"),
        (o["currency"] != s["currency"], "currency_mismatch"),
        (o["observed_at"] > at, "future_observed"),
        (o["ingested_at"] > at, "future_ingested"),
        (o["valid_from"] > s["arrival"] or o["valid_to"] < s["departure"], "validity_mismatch"),
        (age > int(s["max_age_days"]), "stale"),
    ):
        if condition:
            return reason
    return "eligible"


def gross(room):
    return sum(int(room[k]) for k in ("total_cents", "fees_cents", "taxes_cents"))


def cheapest(s, rooms):
    """Assign named guests directly; no subset enumeration or occupancy DP."""
    adults, children = int(s["adults"]), int(s["children"])
    # This is intentionally a *small-fixture* oracle, not a general solver.
    if len(rooms) ** (adults + children) > 5000:
        raise ValueError("fixture exceeds oracle assignment bound")
    winner = None
    allocation = None
    for seats in product(range(len(rooms)), repeat=adults + children):
        used = sorted(set(seats))
        if len(used) > int(s["max_rooms"]):
            continue
        guests = [(seats[:adults].count(i), seats[adults:].count(i)) for i in used]
        if any(not (1 <= a <= int(rooms[i][1]["adult_cap"])
                    and c <= int(rooms[i][1]["child_cap"])
                    and a + c <= int(rooms[i][1]["total_cap"]))
               for i, (a, c) in zip(used, guests)):
            continue
        price = sum(gross(rooms[i][1]) for i in used)
        # The documented lowest-mask tie prefers omission of the latest
        # differing row. For equal rooms, minimizing the prior occupancy
        # is equivalent to maximizing occupancy of the latest room first.
        key = (price, len(used), tuple(reversed(used)),
               tuple((-a, -c) for a, c in reversed(guests)))
        if winner is None or key < winner:
            winner = key
            allocation = [(rooms[i], a, c) for i, (a, c) in zip(used, guests)]
    return allocation


def oracle(s, offers):
    lines = []
    accepted, seen = {}, {}
    for n, o in enumerate(offers, 1):
        p = int(o["property_id"])
        seen[p] = True
        reason = eligibility(s, o)
        lines.append(f"row={n},{p},{int(o['room_id'])},{reason}")
        if reason == "eligible":
            accepted.setdefault(p, []).append((n, o))

    matched = 0
    for p, rooms in accepted.items():
        allocation = cheapest(s, rooms)
        status = "matched" if allocation else "no_feasible_bundle"
        lines.append(f"property={p},{status},{len(rooms)},{2**len(rooms)-1}")
        if allocation:
            matched += 1
            price = sum(gross(o) for (_, o), _, _ in allocation)
            lines.append(f"bundle={p},{price},{len(allocation)}")
            for (n, o), a, c in allocation:
                lines.append(f"allocation={p},{n},{int(o['room_id'])},{a},{c},{gross(o)}")
    for p in seen:
        if p not in accepted:
            lines.append(f"property={p},no_eligible_rows,0,0")
    required = int(s["min_properties"])
    status = "adequate" if matched >= required else "insufficient_evidence"
    lines.append(f"sample={matched},{required},{status}")
    return "\n".join(lines) + "\n"


def table(path):
    with path.open(encoding="ascii", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with path.open("w", encoding="ascii", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generated(root):
    scenario, = table(FIXTURES / "scenario_multiroom.csv")
    template = table(FIXTURES / "offers_multiroom.csv")[0]
    offers = []

    def add(p, r, caps=(4, 2, 6), base=1, fee=0, tax=0, **edits):
        offers.append(dict(template, property_id=str(p), room_id=str(r),
                           adult_cap=str(caps[0]), child_cap=str(caps[1]), total_cap=str(caps[2]),
                           total_cents=str(base), fees_cents=str(fee), taxes_cents=str(tax), **edits))

    # Interleave eligible/rejected properties. IDs deliberately disagree
    # with source order. Cover all reachable rejection codes and precedence.
    add(305, 1, bookable="0", arrival="2026-12-15")
    add(303, 2, arrival="2026-12-15")  # Same room has an eligible observation later.
    add(301, 7, (3, 2, 4), 14000)
    add(302, 8, (3, 2, 4), 14000)
    add(301, 1, (3, 2, 4), 16000)
    add(306, 1, observed_at="2026-11-20T10:00:01Z", ingested_at="2026-11-20T10:00:01Z")
    add(302, 6, (3, 2, 4), 14000)
    add(305, 2, ingested_at="2026-11-20T10:00:01Z")
    add(303, 3, base=18000, fee=9000, tax=1000)
    add(301, 4, base=29000, fee=400, tax=600)  # Same gross as pair; one room wins.
    add(302, 1, (3, 2, 4), 14000)  # Three tied pairs, several valid allocations.
    add(303, 2, base=26000, fee=300, tax=700)  # Higher base but lower gross.
    add(304, 1, (4, 2, 5))  # Separate capacities fit, combined capacity does not.
    add(306, 2, valid_to="2026-12-17", observed_at="2026-10-31T00:00:00Z")
    add(303, 4, observed_at="2026-10-31T00:00:00Z")
    for r in (9, 5, 3, 1):
        add(307, r, (1, 1, 2), 5123)  # All four rooms required; children must split.
    budget = 7 + 7 + 3 + 1 + 15  # All nonempty subsets of properties with eligible rooms.
    scenario.update(adults="4", children="2", max_rooms="4", search_budget=str(budget))
    inputs = {"scenario": root / "scenario.csv", "offers": root / "offers.csv"}
    write_csv(inputs["scenario"], [scenario])
    write_csv(inputs["offers"], offers)
    return inputs, scenario, budget


def object_path(home, digest):
    return home / "artifacts" / f"blake3-{digest}.txt"


def manifest(home, run_id):
    return (home / "runs" / f"{run_id}.txt").read_text("ascii").strip().split(",")


def absent(home):
    return {k: home / "absent" for k in ("scenario", "offers", "valuation", "strategy")}


def verify(home, run_id, version):
    v, scenario, offers, *_ = manifest(home, run_id)
    assert v == f"finpred-run@{version}", v
    s, = table(object_path(home, scenario))
    body = oracle(s, table(object_path(home, offers)))
    before = tree(home)
    replay = invoke(home, "replay", run_id, **absent(home))
    expected = replay + (f"evidence_begin\nevidence_version=yieldcraft.property-evidence@1\n"
                         f"source_run_id={run_id}\n{body}evidence_end\n").encode("ascii")
    for _ in range(2):
        actual = invoke(home, "evidence", run_id, **absent(home))
        if actual != expected:
            raise ValueError(f"{run_id}: report differs from independent oracle\n"
                             f"expected:\n{expected.decode()}\ngot:\n{actual.decode()}")
        if tree(home) != before:
            raise ValueError(f"{run_id}: verified read changed store")


def failed(home, args, diagnostics, inputs):
    before = tree(home) if home.exists() else None
    proc = subprocess.run([ROOT / "bin/finpred", *args], cwd=ROOT,
                          env={**ENV, "FINPRED_HOME": str(home),
                               **{f"FINPRED_{k.upper()}": str(v) for k, v in inputs.items()}},
                          capture_output=True, timeout=60)
    output = proc.stdout + proc.stderr
    if (proc.returncode <= 0 or not any(message in output for message in diagnostics)
            or re.search(rb"(?m)^(?:replay_ok=|run_id=|recommendation_minor=|evidence_|source_run_id=|"
                         rb"row=|property=|allocation=|bundle=|sample=)", output)
            or (tree(home) if home.exists() else None) != before):
        raise ValueError(f"{args}: expected read-only failure ({diagnostics!r}): {proc}")


def corrupt(home, run_id, version):
    v, _, _, _, _, _, trace = manifest(home, run_id)
    assert v == f"finpred-run@{version}"
    # Even an excluded observation and late-verified outputs must be intact
    # before the first evidence or success record is printed.
    rejected, = [p for p in (home / "artifacts").glob("*.txt")
                 if b'"id":"property:106:room:1"' in p.read_bytes()]
    targets = [rejected, object_path(home, trace)]
    if version == 2:
        targets.append(object_path(home, run_id))
    for path in targets:
        original = path.read_bytes()
        path.write_bytes(b"!" + original[1:])
        try:
            failed(home, ["evidence", run_id], [b"snapshot digest mismatch"], absent(home))
        finally:
            path.write_bytes(original)
    # Every referenced digest is genuine. A manifest under another run's
    # name still cannot attest to the inputs, result, or allocations.
    other, = [p for p in (home / "runs").glob("*.txt") if p.stem != run_id]
    other.write_bytes((home / "runs" / f"{run_id}.txt").read_bytes())
    failed(home, ["evidence", other.stem], [b"divergence"], absent(home))


def main(reference, main_id, multi_id):
    verify(reference, main_id, 2)
    verify(reference, multi_id, 2)
    with tempfile.TemporaryDirectory(prefix="finpred-evidence-") as tmp:
        root = Path(tmp)
        legacy = root / "v1"
        fixture = json.loads((FIXTURES / "replay_v1.json").read_bytes())
        for name, data in fixture["files"].items():
            if not re.fullmatch(r"(?:artifacts/blake3-|runs/)[a-f0-9]{64}\.txt", name):
                raise ValueError(f"invalid fixture path: {name}")
            path = legacy / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.encode("ascii"))
        for run_id in fixture["runs"]:
            verify(legacy, run_id, 1)
        legacy_main, = [k for k, summary in fixture["runs"].items()
                        if "recommendation_minor=17100" in summary.splitlines()]
        corrupt(legacy, legacy_main, 1)

        # Corruption tests only touch disposable copies.
        copy = root / "v2"
        shutil.copytree(reference, copy)
        corrupt(copy, main_id, 2)
        inputs, s, budget = generated(root)
        home = root / "generated"
        summary = invoke(home, "run", **inputs)
        run_id = re.search(rb"(?m)^run_id=([a-f0-9]{64})$", summary)[1].decode("ascii")
        verify(home, run_id, 2)
        s["search_budget"] = str(budget - 1)
        write_csv(inputs["scenario"], [s])
        failed(root / "exhausted", ["run"], [b"search budget exhausted"], inputs)
        # No successful run can have an exhausted budget. Commit a smaller
        # inventory under budget 32, then substitute that genuine scenario
        # digest in the original manifest on this private store. Evidence may
        # detect the identity mismatch first, but must never expose a prefix.
        room, = [o for o in table(inputs["offers"])
                 if o["property_id"] == "301" and o["room_id"] == "4"]
        write_csv(inputs["offers"], [dict(room, property_id=p) for p in (401, 402, 403)])
        donor = invoke(home, "run", **inputs)
        donor_id = re.search(rb"(?m)^run_id=([a-f0-9]{64})$", donor)[1].decode("ascii")
        edited = manifest(home, run_id)
        edited[1] = manifest(home, donor_id)[1]
        (home / "runs" / f"{run_id}.txt").write_text(",".join(edited) + "\n", encoding="ascii")
        failed(home, ["evidence", run_id], [b"search budget exhausted", b"divergence"], absent(home))
    print("evidence_cli_ok=true v1_runs=2 v2_runs=3")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3])
