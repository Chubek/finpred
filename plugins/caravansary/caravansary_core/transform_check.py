"""Static validation and type checking for CaravanScript transformations."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


BUILTINS = MappingProxyType({
    "total_cells": ((), "int"),
    "status_count": (("text",), "int"),
    "freshness_count": (("text",), "int"),
    "source_count": (("text",), "int"),
    "source_status_count": (("text", "text"), "int"),
})

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_RESERVED = frozenset("fn emit return int bool text true false not and or".split())
_TYPES = frozenset({"int", "bool", "text"})
_ARITIES = {"literal": 2, "name": 2, "call": 3, "unary": 3, "binary": 4}
_MAX_FUNCTIONS = 64
_MAX_METRICS = 64
_MAX_ARGUMENTS = 16
_MAX_EXPRESSION_NODES = 4096
_MAX_EXPRESSION_DEPTH = 64
_MAX_TEXT_BYTES = 4096
_MAX_INTEGER = 2**63 - 1


@dataclass(frozen=True, slots=True)
class Program:
    """Checked program with detached AST records; consumers treat them as read-only."""

    functions: Mapping[str, dict]
    metrics: tuple[dict, ...]
    metric_types: Mapping[str, str]


def _record(value, fields, what):
    if not isinstance(value, dict) or value.keys() != fields:
        raise ValueError(f"invalid transform {what}")


def _sequence(value, maximum, what, minimum=0):
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise ValueError(f"transform requires {minimum} to {maximum} {what}")
    return value


def _identifier(value):
    if type(value) is not str or not _IDENTIFIER.fullmatch(value) or value in _RESERVED:
        raise ValueError("invalid or reserved transform identifier")
    return value


def _type_name(value):
    if type(value) is not str or value not in _TYPES:
        raise ValueError("invalid transform type; expected int, bool, or text")
    return value


def _literal_type(value):
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        if not 0 <= value <= _MAX_INTEGER:
            raise ValueError("integer literal must be between 0 and 2**63 - 1")
        return "int"
    if type(value) is str:
        if len(value) <= _MAX_TEXT_BYTES:
            try:
                if len(value.encode("utf-8")) <= _MAX_TEXT_BYTES:
                    return "text"
            except UnicodeEncodeError:
                raise ValueError("text literal must be valid UTF-8") from None
        raise ValueError(f"text literal exceeds {_MAX_TEXT_BYTES} UTF-8 bytes")
    raise ValueError("invalid transform literal")


def _binary_type(op, left, right):
    if op in ("==", "!="):
        if left != right:
            raise ValueError(f"{op} requires operands of the same type")
        return "bool"
    if op in ("+", "-", "*"):
        operand, result = "int", "int"
    elif op in ("<", "<=", ">", ">="):
        operand, result = "int", "bool"
    elif op in ("and", "or"):
        operand, result = "bool", "bool"
    else:
        raise ValueError("unknown transform binary operator")
    if left != operand or right != operand:
        raise ValueError(f"{op} requires {operand} operands")
    return result


class _Checker:
    def __init__(self, signatures):
        self.signatures = signatures
        self.nodes = 0

    def expression(self, expr, scope, calls, depth=1):
        self.nodes += 1
        if self.nodes > _MAX_EXPRESSION_NODES:
            raise ValueError(f"transform exceeds {_MAX_EXPRESSION_NODES} expression nodes")
        if depth > _MAX_EXPRESSION_DEPTH:
            raise ValueError(f"expression exceeds depth {_MAX_EXPRESSION_DEPTH}")
        if (
            not isinstance(expr, (list, tuple)) or not expr or type(expr[0]) is not str
            or len(expr) != _ARITIES.get(expr[0])
        ):
            raise ValueError("invalid transform expression")

        tag = expr[0]
        if tag == "literal":
            return tuple(expr), _literal_type(expr[1])
        if tag == "name":
            name = _identifier(expr[1])
            if name not in scope:
                raise ValueError(f"unbound parameter {name}")
            return (tag, name), scope[name]
        if tag == "call":
            name = _identifier(expr[1])
            if name not in self.signatures:
                raise ValueError(f"unknown function {name}")
            args = _sequence(expr[2], _MAX_ARGUMENTS, "arguments")
            parameters, result = self.signatures[name]
            if len(args) != len(parameters):
                raise ValueError(f"{name} expects {len(parameters)} arguments, got {len(args)}")
            checked = []
            for index, (argument, expected) in enumerate(zip(args, parameters), 1):
                arg, actual = self.expression(argument, scope, calls, depth + 1)
                if actual != expected:
                    raise ValueError(f"argument {index} of {name} expects {expected}, got {actual}")
                checked.append(arg)
            if name not in BUILTINS:
                calls.add(name)
            return (tag, name, tuple(checked)), result

        op = expr[1]
        if type(op) is not str:
            raise ValueError("invalid transform operator")
        left, left_type = self.expression(expr[2], scope, calls, depth + 1)
        if tag == "unary":
            if op == "-":
                expected = "int"
            elif op == "not":
                expected = "bool"
            else:
                raise ValueError("unknown transform unary operator")
            if left_type != expected:
                raise ValueError(f"{op} requires operand type {expected}")
            return (tag, op, left), expected
        right, right_type = self.expression(expr[3], scope, calls, depth + 1)
        return (tag, op, left, right), _binary_type(op, left_type, right_type)


def _reject_recursion(graph):
    visiting = set()
    complete = set()

    def visit(name):
        if name in visiting:
            raise ValueError(f"recursive transform function {name}")
        if name not in complete:
            visiting.add(name)
            for callee in sorted(graph[name]):
                visit(callee)
            visiting.remove(name)
            complete.add(name)

    for name in graph:
        visit(name)


def compile_transform(ast) -> Program:
    """Check the entire transform AST, including declarations not reached by emits."""
    _record(ast, {"functions", "metrics"}, "block")
    declarations = _sequence(ast["functions"], _MAX_FUNCTIONS, "functions")
    emits = _sequence(ast["metrics"], _MAX_METRICS, "metrics", minimum=1)
    functions = {}
    signatures = dict(BUILTINS)
    for declaration in declarations:
        _record(declaration, {"name", "parameters", "return_type", "expression"}, "function")
        name = _identifier(declaration["name"])
        if name in BUILTINS:
            raise ValueError(f"transform function {name} shadows a builtin")
        if name in functions:
            raise ValueError(f"duplicate transform function {name}")
        parameters = {}
        for pair in _sequence(declaration["parameters"], _MAX_ARGUMENTS, "parameters"):
            parameter, type_name = _sequence(pair, 2, "parameter fields", minimum=2)
            parameter = _identifier(parameter)
            if parameter in parameters:
                raise ValueError(f"duplicate parameter {parameter} in transform function {name}")
            parameters[parameter] = _type_name(type_name)
        result = _type_name(declaration["return_type"])
        signatures[name] = (tuple(parameters.values()), result)
        functions[name] = {
            "name": name, "parameters": tuple(parameters.items()),
            "return_type": result, "expression": declaration["expression"],
        }

    checker = _Checker(signatures)
    graph = {name: set() for name in functions}
    for name, function in functions.items():
        try:
            expression, actual = checker.expression(
                function["expression"], dict(function["parameters"]), graph[name],
            )
            if actual != function["return_type"]:
                raise ValueError(f"return type must be {function['return_type']}, got {actual}")
        except ValueError as error:
            raise ValueError(f"transform function {name}: {error}") from None
        function["expression"] = expression
    _reject_recursion(graph)

    metrics = []
    metric_types = {}
    for emit in emits:
        _record(emit, {"name", "expression"}, "metric")
        name = _identifier(emit["name"])
        if name in metric_types:
            raise ValueError(f"duplicate transform metric {name}")
        try:
            expression, actual = checker.expression(emit["expression"], {}, set())
        except ValueError as error:
            raise ValueError(f"transform metric {name}: {error}") from None
        metric_types[name] = actual
        metrics.append({"name": name, "expression": expression})
    return Program(MappingProxyType(functions), tuple(metrics), MappingProxyType(metric_types))
