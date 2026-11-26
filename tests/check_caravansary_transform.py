#!/usr/bin/env python3
"""End-to-end CaravanScript transformation checks using synthetic offline inputs."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CLI = Path(__file__).resolve().parents[1] / "plugins/caravansary/caravansary.py"
CLOCK = "2026-11-26T12:00:00Z"
COLLECTION = """property {
  type = "hotel"; latitude = "43"; longitude = "7"; timezone = "Europe/Paris";
  currency = "EUR"; room_types = ["standard"];
}
credentials {
  booking { cookies = "not-approved.json"; }
  agoda { environment = ["CARAVANSARY_TEST_KEY"]; dotenv = ".not-approved"; }
}
competitors = "competitors.json";
sources = ["booking", "agoda"];
search {
  horizon_days = 2; start = "today"; guest_configurations = ["one"];
  stay_lengths = [1]; booker_country = "FR"; locale = "fr-FR";
}
refresh {
  tick_seconds = 3600; weights = "weights.json"; max_age_seconds = 600;
  booking_requests_per_hour = 100; agoda_requests_per_hour = 100;
  booking_concurrency = 1; agoda_concurrency = 1;
}
output { observations = "observations.jsonl"; coverage = "coverage.json"; }
"""
TRANSFORM = r"""
    emit actionable = remaining(status_count("pending"), status_count("failed"));
    fn remaining(pending: int, failed: int) -> int { return add(pending, failed); }
    emit confirms = matches("café", "caf\u00e9") and total_cells() == 2 * source_count("booking");
    fn matches(left: text, right: text) -> bool { return left == right; }
    emit label = "café";
    emit booking_failed = source_status_count("booking", "failed");
    emit agoda_failed = source_status_count("agoda", "failed");
    emit fresh = freshness_count("fresh");
    emit stale = freshness_count("stale");
    emit none = freshness_count("none");
    fn add(left: int, right: int) -> int { return left + right; }
"""


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def call(name, *args):
    return ["call", name, list(args)]


def literals(*values):
    return [["literal", value] for value in values]


def program_ast():
    """Spell out the contract AST rather than deriving it from the implementation."""
    functions = [
        {
            "name": "remaining", "parameters": [["pending", "int"], ["failed", "int"]],
            "return_type": "int", "expression": call("add", ["name", "pending"], ["name", "failed"]),
        },
        {
            "name": "matches", "parameters": [["left", "text"], ["right", "text"]],
            "return_type": "bool", "expression": ["binary", "==", ["name", "left"], ["name", "right"]],
        },
        {
            "name": "add", "parameters": [["left", "int"], ["right", "int"]],
            "return_type": "int", "expression": ["binary", "+", ["name", "left"], ["name", "right"]],
        },
    ]
    metrics = [
        ("actionable", call("remaining", call("status_count", *literals("pending")),
                            call("status_count", *literals("failed")))),
        ("confirms", ["binary", "and", call("matches", *literals("café", "café")),
                      ["binary", "==", call("total_cells"),
                       ["binary", "*", ["literal", 2], call("source_count", *literals("booking"))]]]),
        ("label", ["literal", "café"]),
        ("booking_failed", call("source_status_count", *literals("booking", "failed"))),
        ("agoda_failed", call("source_status_count", *literals("agoda", "failed"))),
        *((name, call("freshness_count", *literals(name))) for name in ("fresh", "stale", "none")),
    ]
    return {"functions": functions, "metrics": [
        {"name": name, "expression": expression} for name, expression in metrics
    ]}


class CaravanScriptV2Test(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.inputs = self.work / "inputs"
        self.inputs.mkdir()
        self.base = self.write_script("base.crs")
        self.write_json(self.inputs / "competitors.json", {
            "kind": "caravansary.competitors@1",
            "guest_configurations": [{"id": "one", "rooms": 1, "adults": 1, "child_ages": []}],
            "properties": [
                {
                    "id": source, "name": f"Synthetic {source}",
                    "providers": {
                        source: {"mapping_status": "verified", "provider_property_id": f"fixture-{source}"},
                    },
                }
                for source in ("booking", "agoda")
            ],
        })
        self.write_json(self.inputs / "weights.json", {
            "kind": "caravansary.weights@1", "mode": "joint", "source": "synthetic",
            "weights": [{"guest_configuration": "one", "stay_length": 1, "weight": 1}],
        })
        # Not an authorized observation log: ignore even though the script names it.
        (self.inputs / "observations.jsonl").write_bytes(b"unrelated existing file\n")

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def write_script(self, name, body=None):
        script = COLLECTION if body is None else COLLECTION + f"\ntransform {{{body}\n}}\n"
        path = self.inputs / name
        path.write_text(script, encoding="utf-8")
        return path

    def snapshot(self):
        return {
            path.relative_to(self.work): None if path.is_dir() else (
                path.read_bytes(), path.stat().st_mtime_ns,
            )
            for path in self.work.rglob("*")
        }

    def cli(self, command, script, *args, status=0, seed="1"):
        before = self.snapshot()
        proc = subprocess.run(
            [sys.executable, "-B", str(CLI), command, str(script), "--as-of", CLOCK, *map(str, args)],
            cwd=self.work, env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True, check=False, timeout=15,
        )
        self.assertEqual(self.snapshot(), before, "CLI wrote files instead of only using stdout/stderr")
        self.assertEqual(proc.returncode, status, proc.stderr.decode("utf-8", errors="replace"))
        if status:
            self.assertEqual(proc.stdout, b"", "failed command emitted partial output")
            self.assertTrue(proc.stderr)
            self.assertNotIn(b"Traceback", proc.stderr)
        else:
            self.assertEqual(proc.stderr, b"")
        return proc

    def observations(self, rows):
        def record(source, observation_id, received_at):
            row = next(row for row in rows if row["source"] == source and row["status"] == "pending")
            return {
                "kind": "caravansary.observation@1",
                "observation_id": observation_id,
                "cell_key": row["cell_key"], "provider_property_id": row["provider_property_id"],
                "request_context": row["request_context"], "received_at": received_at,
                "ingested_at": received_at, "adapter_version": "fixture", "extractor_version": "fixture",
                "complete": True, "authoritative": True, "outcome": "unavailable", "offers": [],
            }

        booking = record("booking", "older-booking", "2026-11-26T11:00:00Z")
        failure = record("booking", "failed-booking", "2026-11-26T11:55:00Z")
        failure.update(complete=False, authoritative=False, outcome="failed", reason="transport_error")
        agoda = record("agoda", "fresh-agoda", "2026-11-26T11:58:00Z")
        return [failure, agoda, booking]

    def write_log(self, name, records):
        path = self.work / name
        path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
        return path

    def test_matrix_replay_and_canonical_provenance(self):
        with_metrics = self.write_script("with-metrics.crs", TRANSFORM)
        base_plan = self.cli("plan", self.base).stdout
        self.assertEqual(self.cli("plan", with_metrics).stdout, base_plan)
        rows = [json.loads(line) for line in base_plan.splitlines()]
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["cell_key"] for row in rows}), 8)

        # Replay observations made without a transform in both reports.
        records = self.observations(rows)
        log = self.write_log("selected.jsonl", records)
        base = json.loads(self.cli("report", self.base, "--observations", log).stdout)
        self.assertEqual(base["kind"], "caravansary.coverage@1")
        self.assertNotIn("transformation", base)
        self.assertEqual(base["counts_by_status"], {
            "pending": 2, "failed": 1, "priced": 0, "unavailable": 1, "unsupported": 4,
        })
        self.assertEqual(base["counts_by_freshness"], {"none": 6, "stale": 1, "fresh": 1})
        result = self.cli("report", with_metrics, "--observations", log).stdout
        report = json.loads(result)
        transform = report.pop("transformation")
        self.assertEqual(report, base)
        self.assertEqual(transform, {
            "kind": "caravansary.transformation@1",
            "program_digest": digest(program_ast()),
            "base_report_digest": digest(base),
            "metrics": {
                "actionable": 3, "confirms": True, "label": "café", "booking_failed": 1,
                "agoda_failed": 0, "fresh": 1, "stale": 1, "none": 6,
            },
        })
        self.assertIs(type(transform["metrics"]["confirms"]), bool)
        self.assertIs(type(transform["metrics"]["agoda_failed"]), int)

        # Changes to trivia, string escape spelling, script path, hash seed, and
        # input replay order must not affect the emitted bytes.
        equivalent = self.write_script(
            "spaced.crs", "\n# comment outside the AST\n" + TRANSFORM.replace("café", r"caf\u00e9")
            .replace("2 * source_count", "2*source_count"),
        )
        reversed_log = self.write_log("reversed.jsonl", reversed(records))
        self.assertEqual(self.cli("report", with_metrics, "--observations", log, seed="2").stdout, result)
        self.assertEqual(
            self.cli("report", equivalent, "--observations", reversed_log, seed="3").stdout,
            result,
        )

        changed = self.write_script("changed.crs", TRANSFORM.replace('emit label = "café"', 'emit label = "other"'))
        self.assertEqual(self.cli("plan", changed).stdout, base_plan)
        changed_report = json.loads(self.cli("report", changed, "--observations", log).stdout)
        changed_transform = changed_report.pop("transformation")
        self.assertEqual(changed_report, base)
        self.assertEqual(changed_transform["base_report_digest"], transform["base_report_digest"])
        self.assertNotEqual(changed_transform["program_digest"], transform["program_digest"])
        self.assertEqual(changed_transform["metrics"], {**transform["metrics"], "label": "other"})

    def test_short_circuit_checked_integers_and_existing_outputs(self):
        (self.inputs / "coverage.json").write_bytes(b"preserve existing coverage file\n")
        script = self.write_script("short-circuit.crs", r"""
            emit skip_and = false and status_count("not_a_status") == 0;
            emit skip_or = true or 9223372036854775807 + 1 == 0;
            emit lower_bound = -9223372036854775807 - 1;
            emit upper_bound = 9223372036854775807;
            emit associative = 15 - 4 - 2 * 3;
            emit exact_text = "é" != "e\u0301";
        """)
        report = json.loads(self.cli("report", script).stdout)
        self.assertEqual(report["transformation"]["metrics"], {
            "skip_and": False, "skip_or": True, "lower_bound": -(2**63),
            "upper_bound": 2**63 - 1, "associative": 5, "exact_text": True,
        })
        self.assertIs(report["transformation"]["metrics"]["skip_and"], False)

    def test_invalid_header_and_transform_syntax(self):
        script = self.inputs / "legacy.crs"
        for version in (1, 2):
            script.write_text(
                f'caravan "Legacy" version {version} {{\n{COLLECTION}}}\n', encoding="utf-8",
            )
            self.cli("report", script, status=1)
        for body in ("", "fn unused() -> int { return 0; }", 'emit n = status_count("pending",);'):
            with self.subTest(body=body):
                script = self.write_script("invalid.crs", body)
                self.cli("report", script, status=1)

    def test_static_errors_are_rejected_before_plan_rows(self):
        invalid_programs = {
            "bool is not int": "emit n = true + 1;",
            "mixed type comparison": 'emit n = 1 == "1";',
            "unreachable branches still type checked": "emit n = true or 1;",
            "bad return in unused function": "fn wrong(x: int) -> bool { return x; } emit n = 1;",
            "wrong arity": 'emit n = source_status_count("booking");',
            "wrong argument type": "emit n = status_count(7);",
            "metric cannot be referenced": "emit first = 0; emit second = first;",
            "cannot inspect raw report": "emit n = offers();",
            "duplicate metric": "emit n = 0; emit n = 1;",
            "builtin shadowing": "fn total_cells() -> int { return 0; } emit n = 1;",
            "direct recursion": "fn loop(x: int) -> int { return loop(x); } emit n = loop(1);",
            "unused indirect recursion": (
                "fn first() -> int { return second(); } emit n = 1;"
                "fn second() -> int { return first(); }"
            ),
            "oversize literal": "emit n = 9223372036854775808;",
        }
        for label, body in invalid_programs.items():
            with self.subTest(label=label):
                self.cli("plan", self.write_script("invalid.crs", body), status=1)

    def test_runtime_errors_do_not_emit_a_partial_report(self):
        base_plan = self.cli("plan", self.base).stdout
        for expression in (
            'status_count("Pending")',
            'freshness_count("expired")',
            'source_count("other")',
            'source_status_count("booking", "bogus")',
            "9223372036854775807 + 1",
            "-9223372036854775807 - 2",
            "-(-9223372036854775807 - 1)",
            "4611686018427387904 * 2",
        ):
            with self.subTest(expression=expression):
                script = self.write_script("runtime-error.crs", f"emit first = 1; emit bad = {expression};")
                self.assertEqual(self.cli("plan", script).stdout, base_plan)
                self.cli("report", script, status=1)

    def test_expensive_acyclic_program_hits_runtime_limit(self):
        # Every leaf has a distinct x; the complete sum fits in int64.
        declarations = ["fn f0(x: int) -> int { return x; }"]
        for index in range(1, 22):
            prev = f"f{index - 1}"
            declarations.append(
                f"fn f{index}(x: int) -> int {{ return {prev}(x * 2) + {prev}(x * 2 + 1); }}"
            )
        script = self.write_script("budget.crs", "emit n = f21(0);\n" + "\n".join(declarations))
        self.cli("plan", script)
        self.cli("report", script, status=1)


if __name__ == "__main__":
    unittest.main()
