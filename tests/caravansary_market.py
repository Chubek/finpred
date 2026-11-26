#!/usr/bin/env python3
"""Offline market acceptance: canonical replay, worker boundaries and denials."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "plugins/caravansary/examples"
CLOCK = "2026-11-26T10:00:00Z"
SERIES = "rooms-sold-backtest.json"
PRICES = "pricing-input.json"
SCRIPT = "canal-market.caf"
GRANTS = "host-grants.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_bytes(canonical(value) + b"\n")
    return path


class CLI:
    def __init__(self, exe):
        self.exe = exe
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CARAVANSARY_")}

    def invoke(self, *args, stdin=None):
        return subprocess.run(
            [self.exe, *map(str, args)],
            cwd=ROOT,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=15,
            check=False,
        )

    def ok(self, *args, stdin=None):
        proc = self.invoke(*args, stdin=stdin)
        assert proc.returncode == 0, (args, proc.returncode, proc.stderr)
        assert not proc.stderr, (args, proc.stderr)
        value = json.loads(proc.stdout)
        assert proc.stdout == canonical(value) + b"\n", (args, proc.stdout)
        return value, proc.stdout

    def artifact(self, mode, *args):
        value, raw = self.ok(mode, *args)
        assert value["kind"] == f"caravansary.market.{mode}@1", value
        assert value["qualification"] == "fictional-offline-fixture", value
        assert value["publication_allowed"] is False, value
        body = dict(value)
        assert body.pop("artifact_digest") == digest(body), value
        return value, raw

    def deny(self, message, *args):
        proc = self.invoke(*args)
        assert proc.returncode != 0 and not proc.stdout, (args, proc.returncode, proc.stdout)
        assert message.encode() in proc.stderr, (args, proc.stderr)


def market_args(base, *, script=None, grants=None, clock=CLOCK):
    return (
        script or base / "workflows" / SCRIPT,
        "--input-root", base,
        "--host-grants", grants or base / "workflows" / GRANTS,
        "--as-of", clock,
    )


def exercise_examples(cli, tmp):
    help_result = cli.invoke("market-help")
    assert help_result.returncode == 0 and b"scrape SCRIPT --source ID" in help_result.stdout
    discover, raw = cli.artifact("discover", *market_args(EXAMPLES))
    assert raw == cli.artifact("discover", *market_args(EXAMPLES, clock="2026-11-26T10:00:00+00:00"))[1]
    captures = discover["result"]["sources"]
    assert [item["source"] for item in captures] == ["agoda_search", "booking_search"]
    for item in captures:
        evidence = item["observation"]["provenance"]
        assert evidence["qualification"] == "fictional-frozen-html", evidence
        assert evidence["content_sha256"] == item["capture_sha256"], evidence
        assert evidence["source_url"].split("/")[2].endswith(".example"), evidence
    candidates = discover["result"]["discovery"]["candidates"]
    assert set((c["provider"], c["provider_property_id"]) for c in candidates) == {
        ("agoda", "riverglass"), ("agoda", "linen-mews"),
        ("booking", "north-canal"), ("booking", "willow-court"),
    }, candidates
    assert all(c["status"] == "eligible" for c in candidates), candidates
    for c in candidates:
        key = ["caravansary.candidate-key@1", c["provider"], c["provider_property_id"]]
        assert c["candidate_id"] == "candidate:" + digest(key)

    scrape, scraped = cli.artifact("scrape", *market_args(EXAMPLES), "--source", "booking_profile")
    profile, = scrape["result"]["sources"]
    assert profile["source"] == "booking_profile", profile
    assert profile["observation"]["operation"] == "profile", profile
    prop, = profile["observation"]["properties"]
    assert prop["name"] == "North Canal & Garden House", prop

    collect, collected = cli.artifact("collect", *market_args(EXAMPLES))
    assert collect["result"]["sources"] == [captures[0], profile, captures[1]], collect
    assert collect["inputs"]["capture_sha256"]["booking_profile"] == profile["capture_sha256"]

    no_offer, abstained = cli.artifact("predict", *market_args(EXAMPLES))
    assert no_offer["status"] == "abstained", no_offer
    assert no_offer["result"]["discovery"] == discover["result"]["discovery"]
    assert no_offer["result"]["position"]["reason"] == "exact_fixture_comparables_not_supplied"
    assert "recommended_minor" not in no_offer["result"]["position"]

    prediction, predicted = cli.artifact(
        "predict", *market_args(EXAMPLES), "--pricing-input", EXAMPLES / "workflows" / PRICES,
    )
    assert prediction["status"] == "completed", prediction
    position = prediction["result"]["position"]
    assert position["status"] == "recommended", position
    assert position["recommended_minor"] == 12500 and position["clamp"] == "upper", position
    assert position["summary"]["quantile"] == 14400, position
    assert position["counts"]["selected_properties"] == 3, position
    assert [item["property_id"] for item in position["evidence"]] == [
        "canal-north", "canal-river", "canal-willow",
    ], position
    assert prediction["result"]["discovery"] == discover["result"]["discovery"]

    series = EXAMPLES / "workflows" / SERIES
    tested, backtest_raw = cli.artifact("backtest", series, "--input-root", EXAMPLES, "--as-of", CLOCK)
    assert tested["status"] == "completed", tested
    result = tested["result"]["backtest"]
    assert result["scored_folds"] == result["requested_folds"] == 3, result
    assert result["weekly_absolute_error_sum_rooms"] == 3, result
    assert [r["weekly_mean_rooms"] for r in result["folds"]] == [5, 3, 3], result
    assert result["eval_as_of"] == CLOCK, result
    changed = read(series)
    changed["history"]["observations"].pop()  # revision unavailable at every decision
    unchanged = write(tmp / "no-late-revision.json", changed)
    replay, _ = cli.artifact("backtest", unchanged, "--input-root", tmp, "--as-of", CLOCK)
    assert replay["result"] == tested["result"]
    assert replay["inputs"]["backtest_input_digest"] != tested["inputs"]["backtest_input_digest"]

    paths = []
    for name, data in (
        ("discover", raw), ("scraped", scraped), ("collected", collected),
        ("abstained", abstained), ("predicted", predicted), ("backtest", backtest_raw),
    ):
        path = tmp / f"{name}.json"
        path.write_bytes(data)
        paths.append(path)
    explained, _ = cli.ok("explain", paths[4], "--input-root", tmp)
    assert explained["kind"] == "caravansary.market.explain@1"
    assert explained["integrity"] == "content-digest-only-not-authenticated"
    assert explained["recorded_result"]["position"] == position
    assert explained["artifact"]["artifact_digest"] == prediction["artifact_digest"]
    _, fractional = cli.artifact("collect", *market_args(EXAMPLES, clock="2026-11-26T10:00:00.1Z"))
    later = tmp / "later.json"
    later.write_bytes(fractional)
    history, raw_history = cli.ok("history", later, *reversed(paths), "--input-root", tmp)
    assert history["kind"] == "caravansary.market.history@1", history
    assert history["artifacts"][-1]["as_of"] == "2026-11-26T10:00:00.100000Z", history
    same_time = [item["artifact_digest"] for item in history["artifacts"][:-1]]
    assert len(same_time) == 6 and same_time == sorted(same_time), history
    assert raw_history == cli.ok("history", *paths, later, "--input-root", tmp)[1]

    tampered = read(paths[4])
    tampered["result"]["position"]["recommended_minor"] += 1
    cli.deny("digest mismatch", "explain", write(tmp / "tampered.json", tampered), "--input-root", tmp)
    cli.deny("duplicate market artifact", "history", paths[4], paths[4], "--input-root", tmp)
    cli.deny("outside the host-approved directories", "explain", paths[4], "--input-root", EXAMPLES)
    return raw


def exercise_denials(cli, tmp, discovery_bytes):
    base = tmp / "fixtures"
    shutil.copytree(EXAMPLES / "providers", base / "providers")
    shutil.copytree(EXAMPLES / "workflows", base / "workflows")
    path = base / "workflows" / GRANTS
    original = read(path)
    changed = copy.deepcopy(original)
    changed["grants"].reverse()
    reordered = write(path.with_name("reordered.json"), changed)
    assert cli.artifact("discover", *market_args(base, grants=reordered))[1] == discovery_bytes

    script = base / "workflows" / SCRIPT
    cli.deny("explicit --input-root", "discover", script, "--host-grants", path, "--as-of", CLOCK)
    cli.deny("requires --host-grants", "discover", script, "--input-root", base, "--as-of", CLOCK)
    cli.deny("duplicate market option", "discover", *market_args(base), "--as-of", CLOCK)
    cli.deny("outside the host-approved directories", "discover", *market_args(base, script=EXAMPLES / "workflows" / SCRIPT))
    cli.deny("market source is not declared", "scrape", *market_args(base), "--source", "undeclared")
    cli.deny("no host grant", "scrape", *market_args(base), "--source", "booking_search")
    cli.deny("newer than --as-of", "discover", *market_args(base, clock="2000-01-01T00:00:00Z"))
    cli.deny("UTC timestamp", "discover", *market_args(base, clock="2026-11-26T10:00:00+01:00"))

    bad_source = script.with_name("bad-source.caf")
    text = script.read_text(encoding="utf-8")
    bad_source.write_text(text.replace('fixture="booking-candidates"', 'fixture="../providers/booking-candidates.html"'), encoding="utf-8")
    cli.deny("registry identifier", "discover", *market_args(base, script=bad_source))
    limited = script.with_name("limited.caf")
    limited.write_text(text.replace("max_candidates=8", "max_candidates=1"), encoding="utf-8")
    bounded, _ = cli.artifact("discover", *market_args(base, script=limited))
    candidates = bounded["result"]["discovery"]["candidates"]
    assert sum(c["status"] == "eligible" for c in candidates) == 1, candidates
    assert sum("candidate_limit" in c["reasons"] for c in candidates) == 3, candidates

    edited = path.with_name("edited.json")
    changed = copy.deepcopy(original)
    changed["grants"][0]["operations"].remove("discover")
    changed["grants"][1]["path"] = "not-opened.html"
    cli.deny("no host grant", "discover", *market_args(base, grants=write(edited, changed)))
    changed = copy.deepcopy(original)
    changed["grants"][0]["fixture"] = "different-id"
    cli.deny("does not match the script", "discover", *market_args(base, grants=write(edited, changed)))
    changed = copy.deepcopy(original)
    changed["grants"][0]["provider_operation"] = "profile"
    cli.deny("incompatible with discover", "discover", *market_args(base, grants=write(edited, changed)))
    changed = copy.deepcopy(original)
    changed["grants"][0]["source_url"] = "https://www.booking.com/"
    cli.deny("offline fixture", "discover", *market_args(base, grants=write(edited, changed)))
    changed["grants"][0]["source_url"] = "https://booking.example/fixtures/candidates?raw=1"
    cli.deny("offline fixture", "discover", *market_args(base, grants=write(edited, changed)))
    changed = copy.deepcopy(original)
    changed["grants"][0]["sha256"] = "0" * 64
    cli.deny("does not match host-approved SHA-256", "discover", *market_args(base, grants=write(edited, changed)))
    changed = copy.deepcopy(original)
    changed["grants"][0]["path"] = "../../outside.html"
    external = tmp / "outside.html"
    external.write_bytes((base / "providers" / "booking-candidates.html").read_bytes())
    cli.deny("outside the host-approved directories", "discover", *market_args(base, grants=write(edited, changed)))
    changed["grants"][0]["path"] = "linked.html"
    link = path.with_name("linked.html")
    link.symlink_to(external)
    cli.deny("outside the host-approved directories", "discover", *market_args(base, grants=write(edited, changed)))
    outside_grants = tmp / "outside-grants.json"
    write(outside_grants, original)
    grant_link = path.with_name("linked-grants.json")
    grant_link.symlink_to(outside_grants)
    cli.deny("outside the host-approved directories", "discover", *market_args(base, grants=grant_link))

    pricing = read(base / "workflows" / PRICES)
    wrong_prices = base / "workflows" / "changed-pricing.json"
    pricing["policy"]["scope"]["currency"] = "USD"
    cli.deny("no currency conversion", "predict", *market_args(base), "--pricing-input", write(wrong_prices, pricing))
    pricing = read(base / "workflows" / PRICES)
    pricing["verified_links"].pop()
    cli.deny("explicitly verified candidate", "predict", *market_args(base), "--pricing-input", write(wrong_prices, pricing))
    pricing = read(base / "workflows" / PRICES)
    pricing["evidence"][0]["observation"]["ingested_at"] = "2026-11-26T10:00:00.000001Z"
    result, _ = cli.artifact("predict", *market_args(base), "--pricing-input", write(wrong_prices, pricing))
    position = result["result"]["position"]
    assert position["status"] == "abstained" and "recommended_minor" not in position
    assert position["counts"]["not_yet_known"] == 1 and position["counts"]["selected_properties"] == 2

    series = read(base / "workflows" / SERIES)
    series["history"]["qualification"] = "observed"
    altered = write(base / "workflows" / "not-a-fixture.json", series)
    cli.deny("only accepts explicitly qualified fictional", "backtest", altered, "--input-root", base, "--as-of", CLOCK)
    series["history"]["qualification"] = "fixture"
    series["request"]["eval_as_of"] = "2026-11-30T10:00:00Z"
    cli.deny("unknown fields", "backtest", write(altered, series), "--input-root", base, "--as-of", CLOCK)


def exercise_companion_boundary(cli, tmp):
    market = cli.exe
    if market.resolve() == ROOT / "bin/caravansary":
        market = ROOT / cli.env.get("FINPRED_BUILD_DIR", "build/dev") / "finpred-caravansary-market"
    if market.name != "finpred-caravansary-market":
        return  # A caller-specified alternative launcher need not expose binary paths.
    sibling = market.with_name("finpred-caravansary-market-probe-v1")
    private = tmp / "deployment"
    private.mkdir()
    installed = Path(shutil.copy2(market, private))
    under_test = CLI(installed)
    args = ("scrape", *market_args(EXAMPLES), "--source", "booking_profile")
    under_test.deny("missing or untrusted fixed market probe companion", *args)
    staged = private / sibling.name
    staged.symlink_to(sibling)
    under_test.deny("missing or untrusted fixed market probe companion", *args)
    staged.unlink()
    shutil.copy2(sibling, staged)
    # A valid copy must not run from a deployment other users can modify.
    private.chmod(0o775)
    try:
        under_test.deny("missing or untrusted fixed market probe companion", *args)
    finally:
        private.chmod(0o755)
    staged.chmod(0o775)
    try:
        under_test.deny("missing or untrusted fixed market probe companion", *args)
    finally:
        staged.chmod(0o755)
    # The versioned sibling is looked up relative to the executable, not cwd.
    assert cli.artifact(*args)[1] == under_test.artifact(*args)[1]


def exercise_jobs(cli, tmp):
    state = tmp / "jobs"
    prefix = ("jobs", "--state", state)
    initialized, _ = cli.ok(*prefix, "init")
    assert initialized["kind"].startswith("caravansary.jobs."), initialized
    unregistered = cli.invoke(*prefix, "schedule", "offline-market", "--at", CLOCK, "--once", CLOCK)
    assert unregistered.returncode != 0 and not unregistered.stdout, unregistered
    data = (EXAMPLES / "providers" / "booking-profile.html").read_bytes()
    cli.ok(*prefix, "source-add", "fixture", stdin=data)
    cli.ok(*prefix, "profile-add", "reg-approved", "fixture")
    scheduled, _ = cli.ok(*prefix, "schedule", "reg-approved", "--at", CLOCK, "--once", CLOCK)
    dispatched, _ = cli.ok(*prefix, "dispatch", "--at", CLOCK)
    assert dispatched["outcome"] == "ran" and dispatched["id"] == scheduled["id"], dispatched
    idle, _ = cli.ok(*prefix, "dispatch", "--at", CLOCK)
    assert idle["outcome"] == "idle", idle

    # Real persistent scheduled scrape uses exactly the same bytes, grants
    # and frozen replay clock as the direct command; its deadline is separate.
    scheduled_script = (EXAMPLES / "workflows" / SCRIPT).read_bytes()
    manifest = (EXAMPLES / "workflows" / "scheduled-scrape.cvs").read_bytes()
    assert hashlib.sha256(scheduled_script).hexdigest().encode() in manifest
    assert hashlib.sha256(data).hexdigest().encode() in manifest
    cli.ok(*prefix, "source-add", "CanalScript", stdin=scheduled_script)
    cli.ok(*prefix, "source-add", "CanalCapture", stdin=data)
    cli.ok(*prefix, "source-add", "CanalManifest", stdin=manifest)
    registered, _ = cli.ok(*prefix, "market-profile-add", "CanalScrape", "CanalManifest")
    assert registered["runner"] == "market-scrape-v1", registered
    now, due = "2026-11-26T10:01:00Z", "2026-11-26T10:01:01Z"
    scheduled, _ = cli.ok(*prefix, "schedule", "CanalScrape", "--at", now, "--once", due)
    assert cli.invoke(*prefix, "result-show", scheduled["id"], due).returncode != 0
    dispatched, _ = cli.ok(*prefix, "dispatch", "--at", due)
    assert dispatched["outcome"] == "ran" and dispatched["result_status"] == "committed", dispatched
    _, saved = cli.ok(*prefix, "result-show", scheduled["id"], due)
    _, direct = cli.artifact("scrape", *market_args(EXAMPLES), "--source", "booking_profile")
    assert saved == direct
    reopened, _ = cli.ok("schedule", "--state", state, "CanalScrape", "--at", due, "--once", due)
    cli.ok(*prefix, "profile-disable", "CanalScrape")
    rejected, _ = cli.ok(*prefix, "dispatch", "--at", due)
    assert rejected["outcome"] == "denied", rejected
    uncommitted = cli.invoke(*prefix, "result-show", reopened["id"], due)
    assert uncommitted.returncode != 0 and not uncommitted.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=ROOT / "bin/caravansary")
    parser.add_argument("--with-jobs", action="store_true", help="also exercise native jobs launcher routing")
    args = parser.parse_args()
    cli = CLI(args.exe.absolute())
    with tempfile.TemporaryDirectory(prefix="caravansary-market-") as work:
        tmp = Path(work)
        oracle = exercise_examples(cli, tmp)
        exercise_denials(cli, tmp, oracle)
        exercise_companion_boundary(cli, tmp)
        if args.with_jobs:
            exercise_jobs(cli, tmp)
    print("Caravansary offline market checks passed")


if __name__ == "__main__":
    main()
