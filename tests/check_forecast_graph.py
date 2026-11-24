#!/usr/bin/env python3
"""Compile a host-owned two-model graph and verify frozen replay evidence."""
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from check_forecast_baselines import (
    CONSUMER, MODEL_FILE, MOVING, PACKAGE, ROOT, SEASONAL, SYNTHETIC_EVIDENCE,
    oracle, request, serialized, shift_month, visible,
)


def frame(value):
    return f"{len(value.encode('ascii'))}:{value}"


def fields(wire):
    rest = wire.encode("ascii")
    values = []
    while rest:
        size, mark, rest = rest.partition(b":")
        assert mark and size.isdigit() and str(int(size)).encode() == size
        n = int(size)
        assert n <= len(rest)
        values.append(rest[:n].decode("ascii"))
        rest = rest[n:]
    return values


def decode(wire):
    status, sep, tail = wire.partition("\n")
    assert status == "ok" and sep
    graph_id, invocations, trace, *entries = fields(tail)
    assert invocations == "2" and len(entries) == 15
    triples = list(zip(entries[::3], entries[1::3], entries[2::3], strict=True))
    assert [entry[0] for entry in triples] == ["moving-history", "request", "seasonal-history", "moving", "seasonal"]
    return graph_id, trace, triples


def latest_snapshot(releases, cutoff, months):
    # Host policy for this fixture only. Choose one complete window from the
    # per-snapshot calendar and ingestion times; do not splice revisions.
    eligible = [(r["ingested"], name, r) for name, r in releases.items()
                if r["ingested"] <= cutoff and months <= r["values"].keys()]
    assert eligible
    eligible.sort(key=lambda option: option[0])
    if len(eligible) > 1:
        assert eligible[-1][0] != eligible[-2][0]
    _, name, release = eligible[-1]
    return name, release


def graph_code_subject(compiler_sha):
    # Share the operator's v1 source normalization, but keep the graph
    # fixture's own domain separator, framed bytes and repository paths.
    subject = runpy.run_path(str(ROOT / "bin/forecast-subject.py"))
    normalize = subject["v1_source"]
    guest = subject["GUEST_NIGHTS"]
    source = ROOT / "source"
    package_source = PACKAGE / "source"
    inputs = [
        (package_source, MODEL_FILE.relative_to(package_source).as_posix(), MODEL_FILE),
        *((source, name, ROOT / name if name == guest else source / name) for name in (
            "core/date.on1x", subject["FEED_SNAPSHOT"], "core/format.on1x", guest, "sdk/callable.on1x"
        )),
    ]
    code_subject = frame("finpred.model-graph-source-subject@1") + frame(compiler_sha)
    for base, name, path in inputs:
        legacy_name, raw = normalize(name, path.read_bytes())
        label = (base / legacy_name).relative_to(ROOT).as_posix()
        code_subject += frame(label) + frame(raw.decode("ascii"))
    return code_subject


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    fixture_path = CONSUMER / "chronology.json"
    fixture_bytes = fixture_path.read_bytes()
    chronology = json.loads(fixture_bytes)
    raw_template = (ROOT / "tests/dragnet_feeds/eurostat.json").read_bytes()
    releases = chronology["snapshots"]
    origins = chronology["origins"]
    feb = releases["february"]
    revision = releases["january_revision"]
    # Reconstruct what a later provider could publish for the same February
    # training window. It is supplied only to the host's negative fixture.
    late = revision | {"values": feb["values"] | revision["values"]}
    compiler_sha = sha256(compiler.read_bytes()).hexdigest()
    code_subject = graph_code_subject(compiler_sha)
    strategy_subject = (
        "finpred.forecast-graph-fixture-policy@1\nlatest-ingested-single-window;"
        "deny-tied-latest;verified-DATA1;same-cutoff;frozen-replay\n"
    )
    with tempfile.TemporaryDirectory(prefix="finpred-forecast-graph-") as tmp:
        work = Path(tmp).resolve()
        exe = work / "consumer"
        decoder = work / "dragnet-feed-decode"
        dragnet = ROOT / "plugins/dragnet"
        build_env = os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
        pc = ["pkg-config"]
        dependencies = ["libxml-2.0", "jansson"]
        cflags = shlex.split(subprocess.check_output(pc + ["--cflags", *dependencies], text=True))
        libs = shlex.split(subprocess.check_output(pc + ["--libs", *dependencies], text=True))
        subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                        "-Werror", "-pedantic", "-ffunction-sections", "-fdata-sections",
                        "-isystem", mulib / "include", *cflags, dragnet / "feed_decode.c",
                        "-Wl,--gc-sections", "-lm", *libs, "-o", decoder],
                       cwd=work, env=build_env, check=True, timeout=90)
        subprocess.run([sys.executable, mulib / "on1x/tools/on1x-build.py",
                        ROOT / "tests/forecast_graph_consumer/main.on1x", "--backend", "c11",
                        "--on1xc", compiler, "--mulib-root", mulib, "-I", ROOT / "source",
                         "-I", ROOT, "-I", PACKAGE / "source", "-I", dragnet / "source", "-o", exe],
                       cwd=work, env=build_env, check=True, timeout=90)
        offline = work / "offline"
        offline.mkdir()
        child_env = build_env | {"FINPRED_HOME": str(offline / "absent")}
        calls = 0

        def run(case, rc=0, **inputs):
            nonlocal calls
            process = subprocess.run([exe], cwd=offline, env=child_env | {"CASE": case} | inputs,
                                     capture_output=True, timeout=5)
            assert (process.returncode, process.stderr) == (rc, b""), (case, rc, process)
            assert bool(process.stdout) != bool(rc) and not list(offline.iterdir()), process
            if case not in ("digest", "normalize"):
                calls += 1
            return process.stdout.decode("ascii")

        def digest(text):
            result = run("digest", BYTES=text).strip()
            assert result.startswith("blake3:") and len(result) == 71
            return result

        code_id, strategy_id = digest(code_subject), digest(strategy_subject)
        child_env |= {"CODE_DIGEST": code_id, "STRATEGY_DIGEST": strategy_id}

        def normalize(release):
            # Generate original JSON-stat fixture bytes and capture metadata,
            # exercise the real offline decoder, and verify both raw parents.
            raw_doc = json.loads(raw_template)
            values = release["values"]
            raw_doc["updated"] = release["updated"]
            raw_doc["size"][-1] = len(values)
            raw_doc["dimension"]["time"]["category"]["index"] = {p: i for i, p in enumerate(values)}
            raw_doc["value"] = {str(i): n for i, n in enumerate(values.values()) if n is not None}
            raw_doc["status"] = {}
            raw = serialized(raw_doc)
            capture = (f"dragnet.feed-capture@1\neurostat,offline_snapshot,{release['received']},"
                       f"{release['ingested']},synthetic,synthetic\n")
            handoff = subprocess.run([decoder, "eurostat"], input=raw, text=True, capture_output=True,
                                     cwd=offline, env=child_env, check=True, timeout=5)
            assert not handoff.stderr
            result = run("normalize", RAW=raw, CAPTURE=capture, DECODE=handoff.stdout,
                         AS_OF=release["ingested"])
            normalized = json.loads(result)
            assert normalized["raw_evidence"] == digest(raw) and normalized["capture_evidence"] == digest(capture)
            assert normalized["raw_bytes"] == len(raw) and normalized["ingested_at"] == release["ingested"]
            assert {row["period"]: row["nights"] for row in normalized["observations"]} == values
            return result

        def frozen(origin, moving, seasonal):
            a, b = normalize(moving), normalize(seasonal)
            return {"CUTOFF": origin["cutoff"], "REQUEST": request(origin),
                    "MOVING_SNAPSHOT": a, "MOVING_PARENT": digest(a),
                    "SEASONAL_SNAPSHOT": b, "SEASONAL_PARENT": digest(b)}

        def inspect(wire, payload, expected):
            graph_id, trace, triples = decode(wire)
            entries = {name: (identity, fields(raw)) for name, identity, raw in triples}
            for name, identity, raw in triples:
                f = entries[name][1]
                is_root = name not in ("moving", "seasonal")
                assert identity == digest(raw)
                assert f[:3] == ["automat.financial-artifact@1", "input" if is_root else "node", name]
                assert f[10:12] == [payload["CUTOFF"], strategy_id] and len(f) == 16
                if is_root:
                    assert f[12:14] == ["", ""]
            assert entries["request"][1][15] == payload["REQUEST"]
            for name, handler in (("moving", MOVING), ("seasonal", SEASONAL)):
                root_name = name + "-history"
                root_id, root = entries[root_name]
                history = json.loads(root[15])
                assert history["cutoff"] == payload["CUTOFF"]
                assert history["parent"] == payload[name.upper() + "_PARENT"]
                model_id, model = entries[name]
                pin = fields(model[12])
                assert pin[:7] == [graph_id, "forecast.baselines", "1.0.0", handler, "1", "1", code_id]
                assert fields(model[13]) == ["2", "training", "", root_name, root_id, "request", "", "request",
                                             entries["request"][0]]
                forecast = json.loads(model[15])
                assert forecast["training"] == digest(root[15])
                assert forecast["model"] == handler and forecast["policy_digest"] == pin[7]
                assert forecast["code_digest"] == code_id and forecast["training_cutoff"] == payload["CUTOFF"]
                assert model[14] == "1"
                assert forecast["estimate"] == {"numerator": expected[name].numerator,
                                                "denominator": expected[name].denominator}
                assert f"{name}={handler}:{model_id}\n" in trace
            return graph_id, entries

        graph_id = None
        records = []
        for origin in origins:
            months = {shift_month(origin["issued"][:7], -i) for i in range(1, 4)}
            season = {shift_month(origin["target"], -12)}
            catalog = releases | {"future-same-window": late}
            moving_key, moving = latest_snapshot(catalog, origin["cutoff"], months)
            seasonal_key, seasonal = latest_snapshot(catalog, origin["cutoff"], season)
            assert (moving_key, seasonal_key) == (origin["training"], "season")
            payload = frozen(origin, moving, seasonal)
            expected = {"moving": oracle(MOVING, origin, visible(releases, origin["cutoff"])),
                        "seasonal": oracle(SEASONAL, origin, visible(releases, origin["cutoff"]))}
            wire = run("execute", **payload)
            plan_id, entries = inspect(wire, payload, expected)
            if graph_id is None:
                graph_id = plan_id
            assert plan_id == graph_id
            assert run("replay", **payload, EVIDENCE=wire.removeprefix("ok\n")) == wire
            records.append((payload, wire, entries))
            print(f"{origin['target']} moving={entries['moving'][0]} seasonal={entries['seasonal'][0]}")

        feb_payload, feb_wire, _ = records[1]
        # The exact same-window revision is genuine fixture bytes, but not
        # visible at the February origin; neither execute nor replay may use it.
        future = normalize(late)
        future_payload = feb_payload | {"MOVING_SNAPSHOT": future, "MOVING_PARENT": digest(future)}
        run("execute", rc=13, **future_payload)
        run("replay", rc=13, **future_payload, EVIDENCE=feb_wire.removeprefix("ok\n"))
        run("execute", rc=11, **(feb_payload | {"MOVING_PARENT": SYNTHETIC_EVIDENCE}))
        assert run("replay", **feb_payload, EVIDENCE=feb_wire.removeprefix("ok\n")) == feb_wire

        march_payload, march_wire, revised_entries = records[2]
        march = releases["march"]
        stale = march | {"values": march["values"] | {"2024-01": feb["values"]["2024-01"]}}
        stale_payload = frozen(origins[2], stale, releases["season"])
        stale_wire = run("execute", **stale_payload)
        _, stale_entries = inspect(stale_wire, stale_payload,
                                   {"moving": Fraction(190), "seasonal": Fraction(120)})
        assert all(stale_entries[n] == revised_entries[n] for n in ("request", "seasonal-history", "seasonal"))
        assert all(stale_entries[n][0] != revised_entries[n][0] for n in ("moving-history", "moving"))
        assert run("replay", **stale_payload, EVIDENCE=march_wire.removeprefix("ok\n")) == "replay_mismatch\n"

        # Rehash an envelope with a different, valid root digest in the
        # moving node's parent slot. Self-consistency does not make it lineage.
        _, trace, entries = decode(march_wire)
        forged = frame(graph_id) + frame("2") + frame(trace)
        for name, identity, raw in entries:
            if name == "moving":
                f = fields(raw)
                parents = fields(f[13])
                parents[4] = revised_entries["seasonal-history"][0]
                f[13] = "".join(map(frame, parents))
                raw = "".join(map(frame, f))
                identity = digest(raw)
            forged += frame(name) + frame(identity) + frame(raw)
        assert run("replay", **march_payload, EVIDENCE=forged) == "replay_mismatch\n"
        assert run("replay", **march_payload, EVIDENCE=march_wire.removeprefix("ok\n")) == march_wire
        print(f"forecast_graph_ok=true cases={calls} graph={graph_id} code={code_id} "
              f"chronology_sha256={sha256(fixture_bytes).hexdigest()} on1xc_sha256={compiler_sha}")


if __name__ == "__main__":
    main()
