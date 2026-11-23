#!/usr/bin/env python3
"""Exercise real offline Elvi, then the separate compiled On1x importer."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_elvi_consumer"
SCHEMA = PKG / "contracts/dragnet.crossref-evidence@1.schema.json"
QUERY = "hotel & rates"
URL = "https://api.crossref.org/works?query=hotel%20%26%20rates&rows=16&select=title,URL"


def check_schema_rejections(validator, evidence):
    # Change one property of the same schema-valid output for each case.
    # Runtime cases below check chronology; this only checks representation.
    for path, value, error_path in (
        (("evidence", "search"), "sha256:" + "0" * 64, ("evidence", "search")),
        (("evidence", "work"), "blake3:" + "g" * 64, ("evidence", "work")),
        (("fields", "price_minor"), "20000", ("fields",)),
        (("format",), "dragnet.crossref-evidence@2", ("format",)),
        (("fields", "title"), False, ("fields", "title")),
        (("search_times", "observed_at"), "2026-11-01T10:00:00+00:00",
         ("search_times", "observed_at")),
    ):
        invalid = json.loads(evidence)
        target = invalid
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        errors = list(validator.iter_errors(invalid))
        assert any(tuple(error.absolute_path) == error_path for error in errors), (path, errors)


def main():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    with tempfile.TemporaryDirectory(prefix="finpred-dragnet-elvi-") as tmp:
        tmp = Path(tmp)
        output = tmp / "build"
        subprocess.run([PKG / "build-crossref.sh", output], check=True)
        c = output / "dragnet-crossref-capture"
        on1x = output / "dragnet-crossref-import"
        empty = tmp / "empty"
        empty.mkdir()
        env = {**os.environ, "FINPRED_HOME": str(empty / "store"),
               "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}
        search = (FIX / "search.json").read_bytes()
        work = (FIX / "work.json").read_bytes()
        request = (FIX / "request.csv").read_bytes()

        def check(p, error):
            if error:
                assert p.returncode > 0 and not p.stdout and error.encode() in p.stderr, p
            else:
                assert p.returncode == 0 and not p.stderr, p
            assert not list(empty.iterdir())
            return p.stdout

        def capture(mode, raw=b"", error=None, query=QUERY):
            args = [c, mode] + ([query] if mode == "search" else [])
            return check(subprocess.run(args, input=raw, cwd=empty, env=env, capture_output=True,
                                        timeout=10), error)

        st = capture("search", search)
        wt = capture("work", work)
        assert st.decode().splitlines()[2:] == [URL, "10.5555/ALPHA", "10.5555/beta"]
        assert capture("search", b'{"status":"ok","message-type":"work-list",'
                       b'"message":{"items":[]}}').decode().splitlines()[2:] == [URL]

        def ingest(r=request, s=search, w=work, a=st, b=wt, error=None):
            # Real open files, no paths/URLs obtained from the adapter or snapshots.
            paths = []
            for i, contents in enumerate((r, s, w, a, b)):
                path = tmp / f"fd-{i + 3}"
                path.write_bytes(contents)
                paths.append(path)
            script = 'exec "$1" 3<"$2" 4<"$3" 5<"$4" 6<"$5" 7<"$6"'
            result = check(subprocess.run(["sh", "-c", script, "import", on1x, *paths], cwd=empty,
                                          env=env, capture_output=True, timeout=10), error)
            if error is None:
                validator.validate(json.loads(result))
            return result

        first = ingest()
        check_schema_rejections(validator, first)
        obs = json.loads(first)
        assert obs["format"] == "dragnet.crossref-evidence@1"
        assert obs["mode"] == "offline" and obs["provider"] == "crossref"
        assert obs["request_url"] == URL and obs["doi"] == "10.5555/alpha"
        assert obs["fields"] == {"title": "Frozen \"rates\" study — €200",
                                 "publisher": "Example \\ Press"}
        assert obs["as_of"] == "2026-11-01T10:00:03Z"
        assert obs["search_times"]["observed_at"] == "2026-11-01T10:00:00Z"
        assert obs["work_times"]["ingested_at"] == obs["as_of"]
        assert obs["terms_ref"] == "fixture-terms" and obs["retention_ref"] == "fixture-retention"
        assert obs["evidence"] == {
            "request": "blake3:4e502636b656a37626fee66b6c740b3b6922244da929ffdddec450a131e84c80",
            "search": "blake3:aa744f104ffa5d17ea2c5ae58aeb16a82086b02eff8084cbcdbd177a4be47b7a",
            "work": "blake3:24383272fd68b7d8106d8821b051a4d68e3f511fb6a34e1858bc0be915661b75",
            "search_decode": "blake3:426f8eb00598398a6eb9898b9212696b289e2b541daaf06b535455a49ae061cd",
            "work_decode": "blake3:50940e27c92d731aa64617e003f2493bb99f7f3410a556fc411652b585a88a67",
        }
        assert obs["evidence"]["search"] == "blake3:" + st.decode().splitlines()[1]
        assert obs["evidence"]["work"] == "blake3:" + wt.decode().splitlines()[1]
        assert obs["evidence"]["search"] != obs["evidence"]["work"]
        assert b'"price_minor"' not in first and b'"hospitality.offer"' not in first
        assert ingest() == first
        assert json.loads(ingest(r=request.replace(b"title|publisher", b"type")))["fields"] == {
            "type": "journal-article"}
        assert list(json.loads(ingest(r=request.replace(b"title|publisher", b"type|publisher|title")))[
            "fields"]) == ["type", "publisher", "title"]
        printable = "".join(map(chr, range(32, 127))).replace("\\", "")
        assert ingest(a=capture("search", search, query=printable))
        missing = work.replace(b'"type":"journal-article",', b"")
        assert json.loads(ingest(r=request.replace(b"title|publisher", b"type"), w=missing,
                                 b=capture("work", missing)))["fields"] == {"type": None}
        changed = search + b" "
        changed_obs = json.loads(ingest(s=changed, a=capture("search", changed)))
        assert changed_obs.pop("evidence") != obs.pop("evidence")
        assert changed_obs == obs

        for bad in (b"price", b"title|title", b"title|", b"|title"):
            ingest(r=request.replace(b"title|publisher", bad), error="field selection")
        ingest(s=search + b" ", error="search digest mismatch")
        ingest(w=work + b" ", error="work digest mismatch")
        ingest(a=st.replace(b"api.crossref.org", b"example.org"), error="request URL")
        ingest(a=st.replace(b"10.5555/beta", b"10.5555/alpha"), error="duplicate DOI")
        wrong = work.replace(b"10.5555/alpha", b"10.5555/other")
        ingest(w=wrong, b=capture("work", wrong), error="DOI not in frozen search")
        ingest(r=request.replace(b"10:00:03Z,", b"10:00:04Z,", 1), error="as-of")
        ingest(r=request.replace(b"10:00:02Z", b"10:00:02+01:00"), error="UTC")
        ingest(r=request.replace(b"10:00:01Z", b"09:59:59Z"), error="chronology")
        ingest(r=request.replace(b"fixture-terms", b"https://other.example"), error="policy reference")
        for bad in ("", " ", "x" * 129, "a\nb", "a\\b"):
            capture("search", search, query=bad, error="keyword")
        capture("search", b"{", error="work-list")
        capture("search", b"x" * 262145, error="snapshot size")
        capture("search", search.replace(b"doi.org", b"example.org"), error="DOI URL")
        capture("search", search.replace(b"10.5555/beta", b"10.5555/ALPHA"), error="ineligible or duplicate")
        capture("search", search.replace(b'"title":["Another result"]', b'"title":[]'),
                error="ineligible or duplicate")
        row = dict(title=["Work"], URL="https://doi.org/10.5555/alpha")
        many = dict(status="ok", message={"items": [row] * 17}, **{"message-type": "work-list"})
        capture("search", json.dumps(many).encode(), error="bounded work-list")
        capture("work", b"{}", error="work response")
        capture("work", work.replace(b"journal-article", b"a" * 1025), error="field")
        capture("work", work.replace(b"journal-article", rb"\u0000"), error="field")
        capture("live", error="usage")
    print("dragnet_elvi_offline_ok=true provider=crossref acquisition_network=disabled")


if __name__ == "__main__":
    main()
