#!/usr/bin/env python3
"""Compiled CLI coverage for strict CSV, typed contracts, eligibility and bounds."""
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {t: (ROOT / "fixtures" / f"{t}.csv").read_bytes()
            for t in ("scenario", "offers", "valuation")}


def edit(table, **fields):
    """Replace fields in data row one without cleaning up malformed byte values."""
    header, row, *rest = FIXTURES[table].splitlines()
    columns, values = header.decode().split(","), row.split(b",")
    for field, value in fields.items():
        values[columns.index(field)] = value if isinstance(value, bytes) else value.encode()
    return b"\n".join([header, b",".join(values), *rest]) + b"\n"


def main():
    valid = FIXTURES["scenario"]
    header, row = valid.splitlines()
    cases = []

    def add(name, table, data, error=None):
        cases.append((name, table, data, error))

    add("crlf", "scenario", valid.replace(b"\n", b"\r\n"))
    add("no-final-lf", "scenario", valid.rstrip(b"\n"))
    add("bare-cr", "scenario", valid.rstrip(b"\n") + b"\r", "expected CRLF")
    add("second scenario row", "scenario", valid + row + b"\n", "exactly one data row")
    add("header only", "scenario", header + b"\n", "exactly one data row")
    # A reader that silently stops at NUL would accept the valid prefix.
    add("nul suffix", "scenario", valid + b"\x00ignored", ("NUL", "read was incomplete", "unquoted ASCII"))
    add("oversize source", "scenario", valid.ljust(2**21+1), "file size")
    for name, value, error in [
        ("max i64 ID", b"9223372036854775807", None),
        ("overflow", b"9223372036854775808", "overflowing integer"),
        ("whitespace", b" 1", "unsigned decimal"),
        ("signed", b"+1", "unsigned decimal"),
        ("trailing junk", b"1x", "invalid or overflowing integer"),
        ("missing", b"", "missing integer"),
        ("quoted", b'"1"', "unquoted ASCII"),
        ("non-ascii", b"1\xff", "unquoted ASCII"),
        ("tab", b"\t1", "unquoted ASCII"),
    ]:
        add(name, "scenario", edit("scenario", scenario_id=value), error)
    for table, data in FIXTURES.items():
        header, first, *others = data.splitlines()
        add(table + " unknown header", table, b"x" + data, "unexpected header")
        for name, malformed in [(" extra field", first + b",99"), (" truncated", first.rsplit(b",", 1)[0])]:
            add(table + name, table, b"\n".join([header, malformed, *others]), "column count")

    for name, table, fields, error in [
        ("non-leap century", "scenario", {"departure": "2100-02-29", "arrival": "2100-02-28"}, "civil stay dates"),
        ("invalid month day", "scenario", {"arrival": "2026-11-31"}, "civil stay dates"),
        ("zero nights", "scenario", {"departure": "2026-12-16"}, "civil stay dates"),
        ("arrival before decision", "scenario", {"arrival": "2026-11-19"}, "civil stay dates"),
        ("offset", "scenario", {"decision_at": "2026-11-20T10:00:00+00:00"}, "UTC timestamps"),
        ("fractional second", "scenario", {"decision_at": "2026-11-20T10:00:00.0Z"}, "UTC timestamps"),
        ("hour 24", "scenario", {"decision_at": "2026-11-20T24:00:00Z"}, "UTC timestamps"),
        ("minute 60", "scenario", {"decision_at": "2026-11-20T10:60:00Z"}, "UTC timestamps"),
        ("second 60", "scenario", {"decision_at": "2026-11-20T10:00:60Z"}, "UTC timestamps"),
        ("late scenario", "scenario", {"ingested_at": "2026-11-20T10:00:01Z"}, "UTC timestamps"),
        ("scenario currency", "scenario", {"currency": "USD"}, "only supports exact EUR"),
        ("evidence below floor", "scenario", {"min_properties": "2"}, "statistical or execution bound"),
        ("excess search budget", "scenario", {"search_budget": "1000001"}, "statistical or execution bound"),
        ("excess children", "scenario", {"children": "9"}, "party or room limit"),
        ("excess rooms", "scenario", {"adults": "5", "max_rooms": "5"}, "party or room limit"),
        ("valuation currency", "valuation", {"currency": "JPY"}, "incompatible currency"),
        ("valuation ceiling", "valuation", {"cap_cents": "1000000000001"}, "invalid money limits"),
        ("fractional cents", "valuation", {"current_cents": "17500.50"}, "invalid or overflowing integer"),
        ("late valuation", "valuation", {"ingested_at": "2026-11-20T10:00:01Z"}, "future-dated provenance"),
        ("valuation order", "valuation", {"observed_at": "2026-11-20T09:00:00Z"}, "provenance"),
        ("negative fee", "offers", {"fees_cents": "-1"}, "unsigned decimal"),
        ("missing tax", "offers", {"taxes_cents": ""}, "missing integer"),
        ("offer currency", "offers", {"currency": "USD"}, "unsupported currency"),
        ("offer date", "offers", {"departure": "2026-13-18"}, "invalid room, dates"),
        ("bookable flag", "offers", {"bookable": "true"}, "expected flag"),
        ("invalid validity window", "offers", {"valid_from": "2027-01-02"}, "economic validity times"),
        ("invalid validity date", "offers", {"valid_to": "2026-12-32"}, "economic validity times"),
        ("observed after ingestion", "offers", {"observed_at": "2026-11-20T09:00:00Z"}, "economic validity times"),
    ]:
        add(name, table, edit(table, **fields), error)

    # The fixture requires all five eligible properties. Each edit below
    # changes just one good offer: valid-but-ineligible rows must reduce the
    # sample, while equality at the declared boundaries must preserve it.
    for name, fields, allowed in [
        ("late offer ingestion", {"ingested_at": "2026-11-20T10:00:01Z"}, False),
        ("future observation", {"observed_at": "2026-11-20T10:00:01Z", "ingested_at": "2026-11-20T10:00:01Z"}, False),
        ("as-of equality", {"observed_at": "2026-11-20T10:00:00Z", "ingested_at": "2026-11-20T10:00:00Z"}, True),
        ("calendar freshness boundary", {"observed_at": "2026-11-13T00:00:00Z"}, True),
        ("stale by calendar day", {"observed_at": "2026-11-12T23:59:59Z"}, False),
        ("exact stay validity", {"valid_from": "2026-12-16", "valid_to": "2026-12-18"}, True),
        ("first night not covered", {"valid_from": "2026-12-17"}, False),
        ("ends before departure", {"valid_to": "2026-12-17"}, False),
        ("partial stay", {"departure": "2026-12-17"}, False),
        ("nonbookable", {"bookable": "0"}, False),
    ]:
        add(name, "offers", edit("offers", **fields), None if allowed else "insufficient_evidence")
    # Count *all* rows before filtering for bookability/staleness. Reuse
    # only the unbookable row's template; each source identity is unique.
    data = FIXTURES["offers"].splitlines()
    bounded = data + [str(i).encode() + b"," + data[-1].split(b",", 1)[1] for i in range(1000, 1505)]
    assert len(bounded) == 513
    add("512 offers", "offers", b"\n".join(bounded) + b"\n")
    add("513 offers", "offers", b"\n".join([*bounded, data[-1]]) + b"\n", "1..512 rows")

    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FINPRED_") or k == "FINPRED_EXE"}
    with tempfile.TemporaryDirectory(prefix="finpred-ingestion-") as tmp:
        for name, table, data, error in cases:
            path = Path(tmp) / f"{table}.csv"
            path.write_bytes(data)
            home = Path(tmp) / name
            proc = subprocess.run(
                [ROOT / "bin/finpred", "run"], cwd=ROOT,
                env={**env, f"FINPRED_{table.upper()}": str(path), "FINPRED_HOME": str(home)},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
            )
            output = proc.stdout.decode(errors="replace")
            if error is None:
                ok = (proc.returncode == 0 and
                      {"recommendation_minor=17100", "published=false"}.issubset(output.splitlines()))
            else:
                messages = (error,) if isinstance(error, str) else error
                ok = (proc.returncode > 0 and any(msg in output for msg in messages) and
                      "recommendation_minor=" not in output and not home.exists())
            if not ok:
                raise RuntimeError(f"{name}: exit={proc.returncode}, home_exists={home.exists()}\n{output}")
    print(f"ingestion_cli_ok=true cases={len(cases)}")


if __name__ == "__main__":
    main()
