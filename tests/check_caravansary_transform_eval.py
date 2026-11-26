#!/usr/bin/env python3
"""Focused tests of CaravanScript transformation evaluation, independent of parsing."""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "caravansary"))
from caravansary_core.transform_eval import evaluate


def _program(*metrics, functions=()):
    return SimpleNamespace(
        functions={fn["name"]: fn for fn in functions},
        metrics=[{"name": name, "expression": expr} for name, _, expr in metrics],
        metric_types={name: kind for name, kind, _ in metrics},
    )


def _function(name, expr, parameters=(), kind="int"):
    return {"name": name, "parameters": parameters, "return_type": kind, "expression": expr}


def _literal(value):
    return ["literal", value]


def _call(name, *args):
    return ["call", name, args]


def _binary(op, left, right):
    return ["binary", op, left, right]


_EMPTY = {"kind": "caravansary.coverage@1", "cells": []}
_MAX = (1 << 63) - 1


class TransformEvalTest(unittest.TestCase):
    def test_coverage_counters_ignore_other_fields_and_saved_counts(self):
        report = {
            "kind": "caravansary.coverage@1",
            "counts_by_status": {"pending": 999},
            "cells": [
                {"source": "booking", "status": "pending", "freshness": "none", "weight": 7},
                {"source": "booking", "status": "priced", "freshness": "stale", "weight": 0},
                {"source": "agoda", "status": "pending", "freshness": "none", "weight": 10},
            ],
        }
        program = _program(
            ("total", "int", _call("total_cells")),
            ("pending", "int", _call("status_count", _literal("pending"))),
            ("fresh", "int", _call("freshness_count", _literal("fresh"))),
            ("booking", "int", _call("source_count", _literal("booking"))),
            ("agoda_pending", "int", _call("source_status_count", _literal("agoda"), _literal("pending"))),
            ("agoda_priced", "int", _call("source_status_count", _literal("agoda"), _literal("priced"))),
        )
        before_report, before_program = deepcopy(report), deepcopy(program)
        result = evaluate(program, report)
        self.assertEqual(list(result.items()), [
            ("total", 3), ("pending", 2), ("fresh", 0), ("booking", 2),
            ("agoda_pending", 1), ("agoda_priced", 0),
        ])
        self.assertEqual(report, before_report)
        self.assertEqual(program, before_program)

    def test_exact_types_and_nested_calls(self):
        subtract = _function("subtract", _binary("-", ["name", "a"], ["name", "b"]),
                             parameters=(("a", "int"), ("b", "int")))
        identity = _function("identity", ["name", "a"], parameters=(("a", "text"),), kind="text")
        label = _call("identity", _literal("café"))
        program = _program(
            ("count", "int", _call("subtract", _literal(1), _call("total_cells"))),
            ("same", "bool", _binary("==", label, _literal("cafe\u0301"))),
            ("label", "text", label),
            functions=(subtract, identity),
        )
        result = evaluate(program, _EMPTY)
        self.assertEqual(result, {"count": 1, "same": False, "label": "café"})
        self.assertEqual(tuple(map(type, result.values())), (int, bool, str))

    def test_labels_and_boolean_short_circuit(self):
        call = _call("source_status_count", _literal("booking"), _literal("PENDING"))
        unsafe = _binary(">", call, _literal(0))
        self.assertEqual(evaluate(_program(
            ("and_short", "bool", _binary("and", _literal(False), unsafe)),
            ("or_short", "bool", _binary("or", _literal(True), unsafe)),
            ("negated", "bool", ["unary", "not", _literal(False)]),
        ), _EMPTY), {"and_short": False, "or_short": True, "negated": True})
        with self.assertRaisesRegex(ValueError, "unknown status label"):
            evaluate(_program(("needed", "bool", _binary("and", _literal(True), unsafe))), _EMPTY)
        with self.assertRaisesRegex(ValueError, "unknown freshness label"):
            evaluate(_program(("invalid", "int", _call("freshness_count", _literal("old")))), _EMPTY)

    def test_checks_intermediate_int64_and_return_values(self):
        minimum = _binary("-", ["unary", "-", _literal(_MAX)], _literal(1))
        self.assertEqual(evaluate(_program(("minimum", "int", minimum)), _EMPTY)["minimum"], -(1 << 63))
        for expr in (
            _binary("-", minimum, _literal(1)),
            ["unary", "-", minimum],
            _binary("+", _literal(_MAX), _literal(1)),
            _binary("*", _literal(_MAX), _literal(2)),
        ):
            with self.subTest(expr=expr), self.assertRaisesRegex(ValueError, "integer overflow"):
                evaluate(_program(("overflow", "int", expr)), _EMPTY)
        with self.assertRaisesRegex(ValueError, "expected int, got bool"):
            evaluate(_program(("bad", "int", _literal(True))), _EMPTY)
        with self.assertRaisesRegex(ValueError, "expected int, got bool"):
            evaluate(_program(("bad", "bool", _call("bad")),
                              functions=(_function("bad", _literal(True)),)), _EMPTY)

    def test_nested_function_expressions_do_not_use_python_recursion(self):
        functions = []
        for index in range(64):
            expr = _call(f"f{index + 1}") if index < 63 else _literal(1)
            for _ in range(50):
                expr = ["unary", "-", expr]
            functions.append(_function(f"f{index}", expr))
        program = _program(("deep", "int", _call("f0")), functions=functions)
        self.assertEqual(evaluate(program, _EMPTY), {"deep": 1})

    def test_budget_is_shared_across_metrics_and_counts_only_reached_expressions(self):
        functions = [_function("f0", _literal(1))]
        for index in range(1, 13):
            call = _call(f"f{index - 1}")
            functions.append(_function(f"f{index}", _binary("+", call, call)))
        large = ("large", "int", _call("f11"))
        skipped = ("skipped", "bool", _binary("or", _literal(True),
                                              _binary(">", _call("f12"), _literal(0))))
        self.assertEqual(evaluate(_program(large, skipped, functions=functions), _EMPTY),
                         {"large": 2048, "skipped": True})
        with self.assertRaisesRegex(ValueError, "step budget"):
            evaluate(_program(large, ("another", "int", _call("f11")), functions=functions), _EMPTY)


if __name__ == "__main__":
    unittest.main()
