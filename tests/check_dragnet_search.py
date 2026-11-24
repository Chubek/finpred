#!/usr/bin/env python3
"""Compile real Elvi/readability + On1x policy; never contact a live provider."""
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import tempfile
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"


def main():
    with tempfile.TemporaryDirectory(prefix="dragnet-search-") as tmp:
        tmp = Path(tmp)
        subprocess.run(["sh", PKG / "build.sh", tmp / "build"], check=True)
        exe = tmp / "build/dragnet"
        mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
        on1xc = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
        independent = tmp / "independent-consumer"
        subprocess.run(["python3", mulib / "on1x/tools/on1x-build.py",
                        ROOT / "tests/dragnet_batch_consumer.on1x", "--backend", "c11",
                        "--cc", os.environ.get("CC", "cc"), "--mulib-root", mulib,
                         "--on1xc", on1xc, "-I", ROOT / "source", "-I", ROOT, "-o", independent],
                       check=True, cwd=tmp)
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "libcurl"], text=True))
        subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra",
                        "-Werror", "-pedantic", "-I" + str(Path(os.environ.get(
                            "MULIB_ROOT", ROOT / "third_party/mulib")) / "include"),
                        ROOT / "tests/dragnet_transport_policy.c", *flags, "-lm",
                        "-o", tmp / "socket-policy"], check=True)
        subprocess.run([tmp / "socket-policy"], check=True)
        search = tmp / "search.html"
        page = tmp / "page.html"
        config = tmp / "Dragnet.json"
        offer = (ROOT / "fixtures/offers.csv").read_text().splitlines()[1]
        url = "https://hotel.example/rooms"
        google = "https://www.google.com/search?q=hotel%20rates&num=2"
        bing = "https://www.bing.com/search?q=hotel%20rates&go=&form=QBLH&filt=all&count=2"
        base = dict(version=1, provider="google", keywords=["hotel rates"],
                    extraction="basic", as_of="2026-11-24T00:00:00Z",
                    max_results=2, interval_seconds=60, transport="offline",
                    fixtures={google: str(search), bing: str(search), url: str(page)})
        schema = json.loads((PKG / "contracts/Dragnet.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        validator.validate(base)
        validator.validate(json.loads((PKG / "examples/Dragnet.json").read_text()))
        output_schema = json.loads((PKG / "contracts/dragnet.page@1.schema.json").read_text())
        Draft202012Validator.check_schema(output_schema)
        output_validator = Draft202012Validator(output_schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER)
        framing_schema = json.loads((PKG / "contracts/dragnet.batch@1.schema.json").read_text())
        Draft202012Validator.check_schema(framing_schema)
        framing = Draft202012Validator(framing_schema)
        env = {**os.environ, "DRAGNET_CONFIG": str(config), "DRAGNET_MODE": "once",
               "DRAGNET_OUTPUT": "jsonl",
               "DRAGNET_ALLOWED_HOSTS": "", "FINPRED_HOME": str(tmp / "forbidden-store"),
               "DRAGNET_ALLOW_LLM": "0", "OPENAI_MODEL": "fixture-model",
               "OPENAI_BASE_URL": "https://api.openai.com/v1",
               "OPENAI_API_KEY": "test-only-secret", "OPENAI_ACCESS_TOKEN": "",
               "HTTPS_PROXY": "http://127.0.0.1:1"}
        cases = 0
        handoffs = 0
        consumers = 0
        yieldcraft_runs = 0

        def write_search(provider="google", extra=""):
            anchor = f'<a href="{url}"><h3>hotel rates</h3></a>'
            if provider == "bing":
                anchor = f'<h2><a href="{url}">hotel rates</a></h2>'
            search.write_text(anchor + anchor + extra)

        def run(settings=None, error=None):
            nonlocal cases
            cases += 1
            config.write_text(json.dumps(settings or base))
            p = subprocess.run([exe], env=env, cwd=tmp, capture_output=True, timeout=15)
            if error:
                assert p.returncode != 0 and not p.stdout and error in p.stderr, p
            else:
                assert p.returncode == 0 and not p.stderr, p
                for line in p.stdout.splitlines():
                    output_validator.validate(json.loads(line))
            assert not (tmp / "forbidden-store").exists()
            return p.stdout

        def handoff(settings=None, error=None):
            nonlocal handoffs
            handoffs += 1
            config.write_text(json.dumps(settings or base))
            p = subprocess.run([ROOT / "bin/dragnet", "--handoff", "--config", config.name],
                               env={**env, "FINPRED_DRAGNET_BUILD_DIR": str(exe.parent)},
                               cwd=tmp, capture_output=True, timeout=15)
            if error:
                assert p.returncode != 0 and not p.stdout and error in p.stderr, p
                return b""
            assert p.returncode == 0 and not p.stderr, p
            lines = p.stdout.splitlines()
            framing.validate(json.loads(lines[0]))
            framing.validate(json.loads(lines[-1]))
            assert json.loads(lines[0])["format"] == "dragnet.batch@1"
            end = json.loads(lines[-1])
            assert end["format"] == "dragnet.batch-end@1" and end["pages"] == len(lines) - 2
            for line in lines[1:-1]:
                output_validator.validate(json.loads(line))
            return p.stdout

        capture = tmp / "capture.jsonl"

        def independent_run(data, mode="inspect", trace=None):
            capture.write_bytes(data)
            args = [independent]
            if trace:
                args = ["strace", "-f", "-qq", "-e", "trace=network", "-o", trace, *args]
            completed = subprocess.run(args, env={"CAPTURE": str(capture), "CAPTURE_TEST_MODE": mode},
                                       cwd=tmp, capture_output=True, timeout=15)
            assert completed.returncode == 0 and not completed.stderr, completed
            if trace:
                assert not trace.read_text().strip()
            return completed.stdout

        def rehash(payload, count=1):
            digest = independent_run(payload, "digest").decode().strip()
            trailer = dict(format="dragnet.batch-end@1", pages=count, batch_digest=digest)
            return payload + json.dumps(trailer, separators=(",", ":")).encode() + b"\n"

        def consume(data, command="dragnet-inspect", cutoff=base["as_of"], error=None):
            nonlocal consumers
            consumers += 1
            capture.write_bytes(data)
            run_env = {k: v for k, v in os.environ.items() if not k.startswith("FINPRED_")}
            run_env.update(FINPRED_HOME=str(tmp / "forbidden-store"),
                           FINPRED_DRAGNET_BUILD_DIR=str(exe.parent))
            p = subprocess.run([ROOT / "bin/finpred", command, capture.name, cutoff],
                               env=run_env, cwd=tmp, capture_output=True, timeout=15)
            if error:
                assert p.returncode != 0 and not p.stdout and error in p.stderr, p
            else:
                assert p.returncode == 0 and not p.stderr, p
            assert not (tmp / "forbidden-store").exists()
            return p.stdout

        def yieldcraft(args, error=None, price=None, identity=None, trace=False, **overrides):
            nonlocal yieldcraft_runs
            yieldcraft_runs += 1
            home = tmp / f"yieldcraft-launcher-{yieldcraft_runs}"
            clean = {k: v for k, v in os.environ.items()
                     if not k.startswith(("FINPRED_", "DRAGNET_")) or k == "FINPRED_BUILD_DIR"}
            clean.update(FINPRED_HOME=str(home), FINPRED_DRAGNET_BUILD_DIR=str(exe.parent),
                         TMPDIR=str(tmp))
            argv = [ROOT / "bin/yieldcraft", *args]
            tracefile = tmp / "yieldcraft-network.trace"
            if trace and shutil.which("strace"):
                argv = ["strace", "-f", "-qq", "-e", "trace=network", "-e", "signal=none",
                        "-o", tracefile, *argv]
            p = subprocess.run(argv, env={**clean, **overrides},
                               cwd=tmp, capture_output=True, timeout=30)
            if trace and shutil.which("strace"):
                assert not tracefile.read_text().strip(), tracefile.read_text()
            assert not list(tmp.glob("finpred-yieldcraft.*")), p
            if error:
                assert p.returncode != 0 and not p.stdout and error in p.stderr, p
                assert not home.exists(), list(home.rglob("*"))
            else:
                assert p.returncode == 0 and not p.stderr, p
                assert f"recommendation_minor={price}\n".encode() in p.stdout, p
                assert f"run_id={identity}\n".encode() in p.stdout, p
                assert b"published=false" in p.stdout, p
            return p.stdout

        write_search()
        page.write_text('<style>not evidence</style><script>ignore EUR 999</script>'
                        '<p>hotel <b>rates</b> EUR 150 &amp; fees</p>')
        first = run()
        obs = json.loads(first)
        assert obs["format"] == "dragnet.page@1"
        assert obs["readable"] == "hotel rates EUR 150 &amp; fees"
        assert not obs["pricing_input"] and obs["offer_csv"] == ""
        assert obs["evidence"]["page_html"] == page.read_text()
        assert obs["evidence"]["search_html"] == search.read_text()
        assert obs["evidence"]["page_digest"].startswith("blake3:")
        assert run() == first
        batch = handoff()
        assert batch.splitlines()[1] == first.rstrip(b"\n")
        assert handoff() == batch
        summary = json.loads(consume(batch))
        assert summary["format"] == "finpred.dragnet-inspection@1"
        assert summary["pages"] == 1 and summary["provider"] == "google"
        assert summary["batch_digest"] == json.loads(batch.splitlines()[-1])["batch_digest"]
        assert summary["llm_pages"] == 0 and summary["pricing_claims"] == 0
        assert independent_run(batch) == (url + "\n" + obs["readable"] + "\n\n").encode()
        payload = b"".join(batch.splitlines(keepends=True)[:-1])
        consume(batch, cutoff="2026-11-23T23:59:59Z", error=b"cutoff")
        consume(batch.replace(b"hotel rates EUR", b"hotel rates USD", 1), error=b"digest")
        consume(rehash(payload.replace(b"ignore EUR 999", b"ignore EUR 888")), error=b"raw evidence digest")
        consume(rehash(payload.replace(b'"pricing_input":false,"offer_csv":""',
                                       b'"pricing_input":true,"offer_csv":"fake"')), error=b"mixed")
        consume(rehash(payload.replace(b"EUR 150 &amp; fees", b"\xff", 1)), error=b"invalid page")
        consume(rehash(payload, 2), error=b"count or digest")
        consume(b"x" * 2000001, error=b"input bounds")
        consume(batch.rstrip(b"\n"), error=b"framing")
        consume(batch + batch, error=b"framing")
        consume(batch.replace(b"dragnet.batch@1", b"dragnet.batch@2"), error=b"header")
        consume(batch, "dragnet-offers", error=b"offer-csv-v1")
        if shutil.which("strace"):
            trace = tmp / "network.trace"
            traced = subprocess.run(["strace", "-f", "-qq", "-e", "trace=network",
                                     "-o", trace, exe], env=env, cwd=tmp, capture_output=True, timeout=15)
            assert traced.returncode == 0 and traced.stdout == first and not traced.stderr, traced
            assert not trace.read_text().strip(), trace.read_text()
        write_search("bing")
        assert json.loads(run({**base, "provider": "bing"}))["url"] == url
        write_search()
        page.write_text("<script>hotel rates</script>unrelated")
        assert run() == b""  # Keywords in scripts/search title are not evidence.
        empty = handoff()
        assert json.loads(consume(empty))["pages"] == 0
        consume(empty, cutoff="2026-11-23T23:59:59Z", error=b"cutoff")
        page.write_text(f"<p>hotel rates FINPRED_OFFER_V1 {offer} END_FINPRED_OFFER</p>")
        settings = {**base, "extraction": "offer-csv-v1"}
        normalized = json.loads(run(settings))
        assert normalized["pricing_input"] and normalized["offer_csv"] == offer
        # No inferred dates, occupancy, currency, tax or bookability.
        page.write_text(page.read_text().replace(",EUR,", ",USD,"))
        run(settings, b"unsupported currency")
        page.write_text(f"hotel rates FINPRED_OFFER_V1 {offer} END_FINPRED_OFFER")
        run({**settings, "as_of": "2026-11-19T00:00:00Z"}, b"exceeds as_of")
        page.write_text(page.read_text() * 2)
        run(settings, b"ambiguous")
        page.write_text("hotel rates FINPRED_OFFER_V1 incomplete")
        run(settings, b"incomplete")
        page.write_text("hotel rates")
        run({**base, "extraction": "gpt"}, b"offline gpt requires llm_fixtures")
        run({**base, "provider": "shell"}, b"provider must")
        run({**base, "keywords": ["  "]}, b"empty keyword")
        run({**base, "keywords": ["hotel\nrates"]}, b"controls")
        run({**base, "max_results": 11}, b"bound exceeded")
        run({**base, "interval_seconds": 1}, b"bound exceeded")
        run({**base, "as_of": "yesterday"}, b"UTC")
        run({**base, "as_of": "now"}, b"UTC")
        run({**base, "environment": {"PATH": "do-not-execute"}}, b"requires gpt extraction")
        run({**base, "version": 2}, b"invalid Dragnet.json")
        run({**base, "fixtures": {google: str(search)}}, b"missing offline snapshot")
        page.write_bytes(b"hotel rates\x00ignored")
        run(error=b"embedded NUL")
        page.write_text("x" * 262145)
        run(error=b"size or file type")
        page.write_text("hotel rates")
        # Real MuLIB OpenAI protocol decoding, frozen Responses snapshots.
        llm_response = tmp / "response.json"
        response = dict(id="resp_fixture", status="completed", error=None,
            output=[dict(type="message", content=[dict(type="output_text", text="Stay dates unavailable.")])])
        llm_response.write_text(json.dumps(response))
        gpt = {**base, "extraction": "gpt", "llm_fixtures": {url: str(llm_response)}}
        analyzed = json.loads(run(gpt))
        assert analyzed["llm_text"] == "Stay dates unavailable."
        assert not analyzed["pricing_input"] and analyzed["offer_csv"] == ""
        assert analyzed["evidence"]["llm_model"] == "fixture-model"
        assert analyzed["evidence"]["llm_endpoint"] == "https://api.openai.com/v1/responses"
        request = json.loads(analyzed["evidence"]["llm_request"])
        assert request["store"] is False and request["max_output_tokens"] == 1024
        assert request["input"] == "hotel rates" and "untrusted page" in request["instructions"]
        assert "tools" not in request
        assert "test-only-secret" not in json.dumps(analyzed)
        task = 'Extract the central bank policy decision; preserve "quotes".'
        detailed = handoff({**gpt, "llm_task": task})
        detailed_page = json.loads(detailed.splitlines()[1])
        assert task in json.loads(detailed_page["evidence"]["llm_request"])["instructions"]
        assert json.loads(consume(detailed))["llm_pages"] == 1
        assert b"Stay dates unavailable." in independent_run(detailed)
        run({**gpt, "llm_task": "x" * 2049}, b"llm_task must")
        run({**base, "llm_task": task}, b"requires gpt")
        llm_response.write_text(json.dumps({**response, "status": "incomplete"}))
        run(gpt, b"incomplete")
        llm_response.write_text(json.dumps({**response, "output": [dict(type="function_call")]}))
        run(gpt, b"tools/actions are denied")
        llm_response.write_text(json.dumps({**response, "output": [],
                                            "choices": [{"text": "not Responses output"}]}))
        run(gpt, b"malformed")
        llm_response.write_text("{")
        run(gpt, b"malformed")
        llm_response.write_text(json.dumps(response))
        envfile = tmp / ".env"
        envfile.write_text("OPENAI_MODEL=dotenv-model\nOPENAI_API_KEY=dotenv-secret\n")
        envfile.chmod(0o600)
        # Process environment > literal dotenv > config environment.
        assert json.loads(run(gpt))["evidence"]["llm_model"] == "fixture-model"
        del env["OPENAI_MODEL"]
        assert json.loads(run(gpt))["evidence"]["llm_model"] == "dotenv-model"
        envfile.chmod(0o644)
        run(gpt, b"private regular file")
        envfile.unlink()
        config.chmod(0o600)
        inline = {**gpt, "environment": {"OPENAI_MODEL": "inline-model", "OPENAI_API_KEY": "inline-secret"}}
        inlined = run(inline)
        assert json.loads(inlined)["evidence"]["llm_model"] == "inline-model"
        assert b"inline-secret" not in inlined and b"test-only-secret" not in inlined
        run({**inline, "environment": {"PATH": "do-not-execute"}}, b"unknown configuration")
        env["OPENAI_MODEL"] = "fixture-model"
        live_gpt = {k: v for k, v in {**gpt, "transport": "https"}.items()
                    if k not in ("fixtures", "llm_fixtures")}
        run(live_gpt, b"data-egress capability denied")
        env["DRAGNET_ALLOW_LLM"] = "1"
        run(live_gpt, b"LLM host capability denied")
        env["DRAGNET_ALLOW_LLM"] = "0"
        # Failure after a valid page must not emit a partial cycle.
        write_search(extra='<a href="https://other.example/"><h3>second</h3></a>')
        run(error=b"missing offline snapshot")
        handoff(error=b"missing offline snapshot")
        write_search()
        run({k: v for k, v in {**base, "transport": "https"}.items() if k != "fixtures"},
            b"host capability denied")
        run({k: v for k, v in {**base, "transport": "https", "as_of": "now"}.items() if k != "fixtures"},
            b"host capability denied")
        # Foreground daemon emits a complete cycle and cancels during its wait.
        config.write_text(json.dumps(base))
        p = subprocess.Popen([exe], env={**env, "DRAGNET_MODE": "daemon",
                                        "DRAGNET_OUTPUT": "handoff"},
                             cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                assert selector.select(10), "daemon did not emit first cycle"
            cycle = b"".join(p.stdout.readline() for _ in range(3))
            assert json.loads(cycle.splitlines()[1])["url"] == url
            assert json.loads(consume(cycle))["pages"] == 1
            p.send_signal(signal.SIGTERM)
            stdout, stderr = p.communicate(timeout=3)
            assert p.returncode == 0 and not stdout and not stderr, (stdout, stderr)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        # The same handoff transports a non-hospitality capture. Consume the
        # saved frame after deleting original fixture files and config.
        results_url = "https://www.google.com/search?q=central%20bank&num=2"
        story_url = "https://example.org/decision"
        search.write_text(f'<a href="{story_url}"><h3>central bank decision</h3></a>')
        story = 'The central bank said "hold" — café.'
        page.write_text(f"<blockquote>{story}</blockquote>")
        finance = handoff({**base, "keywords": ["central bank"],
                           "fixtures": {results_url: str(search), story_url: str(page)}})
        search.unlink()
        page.unlink()
        config.unlink()
        trace = tmp / "consumer.trace" if shutil.which("strace") else None
        assert independent_run(finance, trace=trace) == f"{story_url}\n{story}\n\n".encode()
        assert json.loads(consume(finance))["pricing_claims"] == 0
        # Export complete, explicit page offers and run the unchanged Yieldcraft
        # CLI. No price/date/occupancy inference or pricing-store write by Dragnet.
        for suffix, price, identity in (
            ("", 17100, "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"),
            ("_multiroom", 16000, "7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b"),
        ):
            original = (ROOT / f"fixtures/offers{suffix}.csv").read_text()
            fixtures = {google.replace("num=2", "num=10"): str(search)}
            anchors = []
            for i, row in enumerate(original.splitlines()[1:]):
                source_url = f"https://hotel.example/offer/{i}"
                snapshot = tmp / f"offer-{i}.html"
                snapshot.write_text(f"<p>hotel rates FINPRED_OFFER_V1 {row} END_FINPRED_OFFER</p>")
                fixtures[source_url] = str(snapshot)
                anchors.append(f'<a href="{source_url}"><h3>hotel rates</h3></a>')
            search.write_text("".join(anchors))
            config.write_text(json.dumps({**settings, "max_results": 10, "fixtures": fixtures}))
            exported = subprocess.run([exe], env={**env, "DRAGNET_OUTPUT": "offers-csv"},
                                      capture_output=True, timeout=15)
            assert exported.returncode == 0 and not exported.stderr, exported
            assert exported.stdout == original.encode()
            shared = handoff({**settings, "max_results": 10, "fixtures": fixtures})
            projected = consume(shared, "dragnet-offers")
            assert projected == exported.stdout
            assert json.loads(consume(shared))["pricing_claims"] == len(anchors)
            output = tmp / "offers.csv"
            output.write_bytes(projected)
            run_env = {k: v for k, v in os.environ.items() if not k.startswith("FINPRED_")}
            run_env.update(FINPRED_OFFERS=str(output),
                           FINPRED_SCENARIO=str(ROOT / f"fixtures/scenario{suffix}.csv"),
                           FINPRED_VALUATION=str(ROOT / "fixtures/valuation.csv"),
                           FINPRED_HOME=str(tmp / f"yieldcraft{suffix}"))
            result = subprocess.run([ROOT / "bin/finpred", "run"], env=run_env,
                                    capture_output=True, timeout=30)
            assert result.returncode == 0, result
            assert f"recommendation_minor={price}\n".encode() in result.stdout, result
            assert f"run_id={identity}\n".encode() in result.stdout, result
            assert b"published=false" in result.stdout
            scenario = tmp / f"scenario input{suffix}.csv"
            scenario.write_bytes((ROOT / f"fixtures/scenario{suffix}.csv").read_bytes())
            cutoff = scenario.read_text().splitlines()[1].split(",")[3]
            saved = tmp / f"retained capture{suffix}.jsonl"
            config_name = "Dragnet.json"
            settings_for_run = {**settings, "max_results": 10, "fixtures": fixtures, "as_of": cutoff}
            config.write_text(json.dumps(settings_for_run))
            invoke = ["--scenario", scenario.name, "--dragnet", config_name]
            fresh = yieldcraft(invoke + ["--save-capture", saved.name], price=price, identity=identity,
                               trace=not suffix,
                               FINPRED_OFFERS=str(tmp / "must-not-read.csv"), FINPRED_ENGINE="scalar")
            assert saved.is_file() and saved.stat().st_mode & 0o077 == 0
            assert json.loads(consume(saved.read_bytes(), cutoff=cutoff))["pages"] == len(anchors)
            # Non-overwriting save, and a later capture must not drive an earlier scenario.
            yieldcraft(invoke + ["--save-capture", saved.name], error=b"already exists")
            capture.write_bytes(shared)
            yieldcraft(["--scenario", scenario.name, "--capture", capture.name], error=b"cutoff")
            config.write_text(json.dumps({**settings_for_run, "extraction": "basic", "fixtures": {}}))
            yieldcraft(invoke, error=b"offer-csv-v1")
            config.write_text(json.dumps({**settings_for_run, "fixtures": {}}))
            yieldcraft(invoke, error=b"missing offline snapshot",
                       FINPRED_OFFERS=str(ROOT / f"fixtures/offers{suffix}.csv"))
            live = {k: v for k, v in {**settings_for_run, "transport": "https", "as_of": "now"}.items()
                    if k != "fixtures"}
            config.write_text(json.dumps(live))
            yieldcraft(invoke, error=b"host capability denied", DRAGNET_ALLOWED_HOSTS="www.google.com")
            search.write_text("<p>No search results.</p>")
            config.write_text(json.dumps(settings_for_run))
            yieldcraft(invoke, error=b"no structured offers")
            capture.write_bytes(saved.read_bytes().rsplit(b"\n", 2)[0] + b"\n")
            yieldcraft(["--scenario", scenario.name, "--capture", capture.name], error=b"framing")
            search.unlink()
            config.unlink()
            from_capture = yieldcraft(["--scenario", scenario.name, "--capture", saved.name],
                                      price=price, identity=identity)
            assert from_capture == fresh
        yieldcraft(["--market-positioning"], price=17100,
                   identity="28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db")
        yieldcraft(["--capture", "missing", "--allow-host", "example.org"], error=b"require --dragnet")
        yieldcraft(["--capture", "missing", "--dragnet", "missing"], error=b"choose one")
        yieldcraft(["--dragnet", "missing"], error=b"execution is forbidden", FINPRED_MODE="execution")
        broken = tmp / "invalid scenario.csv"
        broken.write_text("malformed\n")
        yieldcraft(["--dragnet", "missing", "--scenario", broken.name], error=b"scenario: expected")
        print(f"dragnet_search_ok=true cases={cases} handoffs={handoffs} consumers={consumers} "
              f"yieldcraft_launcher={yieldcraft_runs} "
              "independent_consumer=passed daemon_cancel=passed "
              "yieldcraft=17100,16000 golden_v2=unchanged network=disabled "
              f"network_trace={'passed' if shutil.which('strace') else 'skipped'}")


if __name__ == "__main__":
    main()
