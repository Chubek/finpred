#!/usr/bin/env python3
"""Exercise Dragnet's launcher with the compiled offline Crossref tools."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_elvi_consumer"
QUERY = "hotel & rates"
VERIFY_OK = b"crossref_replay_ok=true\n"


def request_url(query):
    return f"https://api.crossref.org/works?query={quote(query, safe='')}&rows=16&select=title,URL"


# Frozen semantics and independently recorded BLAKE3 values from the native
# Elvi/On1x fixture. Do not derive the verification target from the launcher.
GOLDEN = {
    "format": "dragnet.crossref-evidence@1",
    "mode": "offline",
    "provider": "crossref",
    "search_scope": "single_frozen_page",
    "request_url": request_url(QUERY),
    "doi": "10.5555/alpha",
    "as_of": "2026-11-01T10:00:03Z",
    "search_times": {
        "observed_at": "2026-11-01T10:00:00Z",
        "ingested_at": "2026-11-01T10:00:01Z",
    },
    "work_times": {
        "observed_at": "2026-11-01T10:00:02Z",
        "ingested_at": "2026-11-01T10:00:03Z",
    },
    "terms_ref": "fixture-terms",
    "retention_ref": "fixture-retention",
    "evidence": {
        "request": "blake3:4e502636b656a37626fee66b6c740b3b6922244da929ffdddec450a131e84c80",
        "search": "blake3:aa744f104ffa5d17ea2c5ae58aeb16a82086b02eff8084cbcdbd177a4be47b7a",
        "work": "blake3:24383272fd68b7d8106d8821b051a4d68e3f511fb6a34e1858bc0be915661b75",
        "search_decode": "blake3:426f8eb00598398a6eb9898b9212696b289e2b541daaf06b535455a49ae061cd",
        "work_decode": "blake3:50940e27c92d731aa64617e003f2493bb99f7f3410a556fc411652b585a88a67",
    },
    "fields": {"title": 'Frozen "rates" study — €200', "publisher": "Example \\ Press"},
}
GOLDEN_BYTES = (json.dumps(GOLDEN, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def snapshot(root, paths):
    """Ignore atime: reading can update it even when nothing is written."""
    result = {}
    for path in (root, *paths):
        stat = path.lstat()
        result[path] = (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_nlink,
                        stat.st_mtime_ns, stat.st_ctime_ns, path.read_bytes() if path != root else None)
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-crossref-replay-") as tmp:
        tmp = Path(tmp)
        output = tmp / "compiled tools"
        subprocess.run([PKG / "build-crossref.sh", output], check=True)
        inputs, cases, runtime, scratch = (tmp / name for name in
                                            ("frozen inputs", "alternatives", "runtime", "scratch"))
        for directory in (inputs, cases, runtime, scratch):
            directory.mkdir()
        request, search, work = (inputs / name for name in
                                  ("request copy.csv", "search copy.json", "work copy.json"))
        request_bytes, search_bytes, work_bytes = (
            (FIX / name).read_bytes() for name in ("request.csv", "search.json", "work.json"))
        expected = inputs / "expected evidence.json"
        originals = (request, search, work, expected)
        for path, content in zip(originals, (request_bytes, search_bytes, work_bytes, GOLDEN_BYTES)):
            path.write_bytes(content)
        before = snapshot(inputs, originals)

        env = {**os.environ, "DRAGNET_CROSSREF_BIN": str(output), "HOME": str(runtime),
               "FINPRED_HOME": str(runtime / "store"), "TMPDIR": str(scratch)}

        def run(mode, query=QUERY, req=request, hits=search, item=work, match=expected, ok=True):
            args = [PKG / "crossref", mode, query, req, hits, item]
            if mode == "verify":
                args.append(match)
            proc = subprocess.run(args, cwd=runtime, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=10)
            if ok:
                assert proc.returncode == 0 and not proc.stderr, proc
            else:
                assert proc.returncode > 0 and proc.stdout == b"", proc
            assert not list(runtime.iterdir()), "launcher wrote to its working directory or store"
            assert not list(scratch.iterdir()), "launcher left staged files behind"
            assert snapshot(inputs, originals) == before, "frozen inputs or evidence were modified"
            return proc.stdout

        def variant(name, content):
            path = cases / name
            path.write_bytes(content)
            return path

        assert run("import") == GOLDEN_BYTES
        assert run("verify") == VERIFY_OK
        assert run("import") == GOLDEN_BYTES

        query = "hotel ?rows=1&sort=recent #notes"
        changed = json.loads(run("import", query=query))
        assert changed["request_url"] == request_url(query)
        assert changed["fields"] == GOLDEN["fields"]
        run("verify", query=query, ok=False)

        selected = variant("fields.csv", request_bytes.replace(b"title|publisher", b"type"))
        changed = json.loads(run("import", req=selected))
        assert changed["fields"] == {"type": "journal-article"}
        run("verify", req=selected, ok=False)
        invalid = variant("unknown-field.csv", request_bytes.replace(b"title|publisher", b"price"))
        run("import", req=invalid, ok=False)
        run("verify", req=invalid, ok=False)

        for role, key, data in (("hits", "search", search_bytes), ("item", "work", work_bytes)):
            # Whitespace leaves the decoded values alone but changes frozen bytes.
            edited = variant(f"changed-{role}.json", data + b" ")
            changed = json.loads(run("import", **{role: edited}))
            digest = changed.pop("evidence")
            assert {k for k in GOLDEN["evidence"] if digest[k] != GOLDEN["evidence"][k]} == {
                key, f"{key}_decode"}
            assert changed == {k: v for k, v in GOLDEN.items() if k != "evidence"}
            run("verify", ok=False, **{role: edited})

        spaced = variant("changed-expected.json", GOLDEN_BYTES + b"\n")
        run("verify", match=spaced, ok=False)

        for role, data, limit in (("req", request_bytes, 1024), ("hits", search_bytes, 262144),
                                  ("item", work_bytes, 262144), ("match", GOLDEN_BYTES, 16384)):
            oversized = variant(f"oversized-{role}", data.ljust(limit + 1, b" "))
            empty = variant(f"empty-{role}", b"")
            for path in (oversized, empty):
                if role != "match":
                    run("import", ok=False, **{role: path})
                run("verify", ok=False, **{role: path})

        fifo = cases / "not a file"
        os.mkfifo(fifo)
        for role in ("req", "hits", "item", "match"):
            for path in (cases, fifo):
                if role != "match":
                    run("import", ok=False, **{role: path})
                run("verify", ok=False, **{role: path})

        assert run("verify") == VERIFY_OK
    print("dragnet_crossref_launcher_ok=true golden_bytes_verified=true")


if __name__ == "__main__":
    main()
