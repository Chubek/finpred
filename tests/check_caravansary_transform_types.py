#!/usr/bin/env python3
"""Offline checks for the CaravanScript transform compiler, using ASTs directly."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "caravansary"))
from caravansary_core.transform_check import BUILTINS, compile_transform


def literal(value):
    return ["literal", value]


def name(value):
    return ["name", value]


def call(callee, *args):
    return ["call", callee, list(args)]


def binary(op, left, right):
    return ["binary", op, left, right]


def function(identifier, expression, parameters=(), return_type="int"):
    return {
        "name": identifier, "parameters": parameters, "return_type": return_type,
        "expression": expression,
    }


def ast(*functions, metrics=None):
    if metrics is None:
        metrics = {"metric": literal(0)}
    return {
        "functions": functions,
        "metrics": [{"name": key, "expression": expression} for key, expression in metrics.items()],
    }


def invalid(tree, message):
    try:
        compile_transform(tree)
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError(f"accepted invalid transform: expected {message}")


assert dict(BUILTINS) == {
    "total_cells": ((), "int"), "status_count": (("text",), "int"),
    "freshness_count": (("text",), "int"), "source_count": (("text",), "int"),
    "source_status_count": (("text", "text"), "int"),
}
tree = ast(
    function("first", binary("+", call("second", name("label")), call("total_cells")),
             [("label", "text")]),
    function("second", call("status_count", name("label")), [("label", "text")]),
    metrics={
        "second": call("first", literal("pending")),
        "label": literal("text output"),
        "is_equal": binary("==", literal(True), literal(False)),
    },
)
program = compile_transform(json.loads(json.dumps(tree)))
assert program.metric_types == {"second": "int", "label": "text", "is_equal": "bool"}
assert list(program.functions) == ["first", "second"]
assert [emit["name"] for emit in program.metrics] == ["second", "label", "is_equal"]
assert program.functions["first"]["parameters"] == (("label", "text"),)
program = compile_transform(tree)
tree["metrics"][0]["expression"][2][0][1] = "changed"
assert program.metrics[0]["expression"] == ("call", "first", (("literal", "pending"),))

for tree, message in (
    (ast(function("f", literal(0)), function("f", literal(1))), "duplicate transform function"),
    (ast(function("f", literal(0), [("x", "int"), ("x", "int")])), "duplicate parameter"),
    (ast(function("source_count", literal(0))), "shadows a builtin"),
    (ast(function("return", literal(0))), "reserved transform identifier"),
    (ast(function("f", literal(0), return_type="float")), "invalid transform type"),
    (ast(function("f", literal(0), [("x", [])])), "invalid transform type"),
    (ast(function("f", literal(False))), "return type must be int"),
    (ast(function("f", name("unknown"))), "unbound parameter"),
    (ast(metrics={"first": literal(1), "second": name("first")}), "unbound parameter"),
    (ast(metrics={"x": call("x")}), "unknown function"),
    (ast(metrics={"x": call("total_cells", literal(0))}), "expects 0 arguments"),
    (ast(metrics={"x": call("status_count", literal(1))}), "expects text, got int"),
    (ast(metrics={"x": binary("+", literal(True), literal(1))}), "+ requires int"),
    (ast(metrics={"x": binary("<", literal("a"), literal("b"))}), "< requires int"),
    (ast(metrics={"x": binary("==", literal(False), literal(0))}), "same type"),
    (ast(metrics={"x": ["unary", "not", literal(0)]}), "requires operand type bool"),
    (ast(metrics={"x": binary("and", literal(False), literal(0))}), "requires bool"),
    (ast(metrics={"x": binary("or", literal(True), call("unknown"))}), "unknown function"),
    (ast(function("f", call("f"))), "recursive transform function"),
    (ast(function("f", call("g")), function("g", call("f"))), "recursive transform function"),
    (ast(function("f", binary("or", literal(True), call("f")), return_type="bool")),
     "recursive transform function"),
    (ast(metrics={"x": literal(-1)}), "integer literal"),
    (ast(metrics={"x": literal(2**63)}), "integer literal"),
    (ast(metrics={"x": literal(0.0)}), "invalid transform literal"),
    (ast(metrics={"x": literal("\ud800")}), "valid UTF-8"),
    (ast(metrics={"x": [[], 0]}), "invalid transform expression"),
    (ast(metrics={}), "1 to 64 metrics"),
):
    invalid(tree, message)
tree = ast()
tree["metrics"] *= 2
invalid(tree, "duplicate transform metric")

# Inclusive limits, and the first value past each limit.
functions = [function(f"f{i}", literal(i)) for i in range(64)]
compile_transform(ast(*functions))
invalid(ast(*functions, function("overflow", literal(0))), "64 functions")

parameters = [(f"p{i}", "int") for i in range(16)]
compile_transform(ast(function("f", name("p15"), parameters),
                      metrics={"m": call("f", *[literal(i) for i in range(16)])}))
invalid(ast(function("f", literal(0), parameters + [("p16", "int")])), "16 parameters")
invalid(ast(metrics={"m": call("total_cells", *[literal(0)] * 17)}), "16 arguments")

text = "😀" * 1024
compile_transform(ast(metrics={"m": literal(text), "i": literal(2**63 - 1)}))
invalid(ast(metrics={"m": literal(text + "a")}), "4096 UTF-8 bytes")

chain = literal(1)
for _ in range(63):
    chain = binary("+", chain, literal(1))
compile_transform(ast(metrics={"m": chain}))
invalid(ast(metrics={"m": binary("+", chain, literal(1))}), "depth 64")

# 4096 nodes across 64 metrics. Shared subtrees in hand-built ASTs count per visit.
wide = literal(1)
for _ in range(6):
    wide = binary("+", wide, wide)
metrics = {f"m{i}": wide if i < 32 else literal(0) for i in range(64)}
compile_transform(ast(metrics=metrics))
invalid(ast(metrics=metrics | {"m64": literal(0)}), "64 metrics")
invalid(ast(metrics=metrics | {"m63": ["unary", "-", literal(1)]}), "4096 expression nodes")

print("caravansary transformation types: OK")
