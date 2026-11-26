"""Evaluate checked CaravanScript metrics against coverage counters only."""

from __future__ import annotations

from collections import Counter
import operator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transform_check import Program


_STEP_BUDGET = 10_000
_INT_MIN = -(1 << 63)
_INT_MAX = (1 << 63) - 1
_TYPES = {int: "int", bool: "bool", str: "text"}
_LABELS = {
    "source": frozenset(("booking", "agoda")),
    "status": frozenset(("pending", "priced", "unavailable", "unsupported", "failed")),
    "freshness": frozenset(("fresh", "stale", "none")),
}
_COUNT_FIELDS = {
    "status_count": "status",
    "freshness_count": "freshness",
    "source_count": "source",
}
_INT_OPERATIONS = {
    "*": operator.mul, "+": operator.add, "-": operator.sub,
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}


def _checked(value, expected=None):
    actual = _TYPES.get(type(value))
    if actual is None or (expected is not None and actual != expected):
        raise ValueError(f"transform expected {expected or 'a scalar'}, got {actual or type(value).__name__}")
    if actual == "int" and not _INT_MIN <= value <= _INT_MAX:
        raise ValueError("transform integer overflow: outside signed 64-bit range")
    return value


def _label(value, field):
    if type(value) is not str:
        raise ValueError(f"transform {field} label must be text")
    if value not in _LABELS[field]:
        raise ValueError(f"transform unknown {field} label: {value!r}")
    return value


def _unary(op, value):
    if op == "-":
        return _checked(-_checked(value, "int"))
    if op == "not":
        return not _checked(value, "bool")
    raise ValueError(f"transform unknown unary operator: {op!r}")


def _binary(op, left, right):
    if op in ("==", "!="):
        _checked(right, _TYPES[type(left)])
        return left == right if op == "==" else left != right
    operation = _INT_OPERATIONS.get(op)
    if operation is None:
        raise ValueError(f"transform unknown binary operator: {op!r}")
    return _checked(operation(_checked(left, "int"), _checked(right, "int")))


class _Evaluation:
    def __init__(self, program, report):
        cells = report.get("cells") if isinstance(report, dict) else None
        if not isinstance(cells, list):
            raise ValueError("transform requires a coverage report with a cells list")
        self.functions = program.functions
        self.remaining = _STEP_BUDGET
        self.counts = {field: Counter() for field in _LABELS}
        self.source_status = Counter()
        self.total = _checked(len(cells), "int")
        for cell in cells:
            if not isinstance(cell, dict):
                raise ValueError("transform coverage cell must be an object")
            source = _label(cell.get("source"), "source")
            status = _label(cell.get("status"), "status")
            freshness = _label(cell.get("freshness"), "freshness")
            self.counts["source"][source] += 1
            self.counts["status"][status] += 1
            self.counts["freshness"][freshness] += 1
            self.source_status[source, status] += 1

    def builtin(self, name, args):
        if name == "total_cells" and not args:
            return self.total
        if name == "source_status_count" and len(args) == 2:
            return self.source_status[_label(args[0], "source"), _label(args[1], "status")]
        field = _COUNT_FIELDS.get(name)
        if field is not None and len(args) == 1:
            return self.counts[field][_label(args[0], field)]
        raise ValueError(f"transform invalid builtin call: {name!r}")

    def expression(self, expression):
        # LIFO continuation and operand stacks avoid Python recursion, including
        # when a chain of function calls nests otherwise shallow expressions.
        tasks = [("expr", expression, {})]
        values = []
        while tasks:
            task = tasks.pop()
            action = task[0]
            if action == "expr":
                if self.remaining == 0:
                    raise ValueError(f"transform expression step budget exceeded ({_STEP_BUDGET})")
                self.remaining -= 1
                _, node, env = task
                tag = node[0]
                if tag == "literal":
                    values.append(_checked(node[1]))
                elif tag == "name":
                    if node[1] not in env:
                        raise ValueError(f"transform unbound name: {node[1]!r}")
                    values.append(env[node[1]])
                elif tag == "unary":
                    _, op, operand = node
                    tasks.append(("unary", op))
                    tasks.append(("expr", operand, env))
                elif tag == "binary":
                    _, op, left, right = node
                    if op in ("and", "or"):
                        tasks.append(("logical", op, right, env))
                    else:
                        tasks.append(("binary", op))
                        tasks.append(("expr", right, env))
                    tasks.append(("expr", left, env))
                elif tag == "call":
                    _, name, arguments = node
                    tasks.append(("invoke", name, len(arguments)))
                    tasks.extend(("expr", arg, env) for arg in reversed(arguments))
                else:
                    raise ValueError(f"transform unknown expression: {tag!r}")
            elif action == "unary":
                values.append(_unary(task[1], values.pop()))
            elif action == "binary":
                right = values.pop()
                values.append(_binary(task[1], values.pop(), right))
            elif action == "logical":
                _, op, right, env = task
                left = _checked(values.pop(), "bool")
                if (op == "and" and not left) or (op == "or" and left):
                    values.append(left)
                else:
                    tasks.append(("check", "bool"))
                    tasks.append(("expr", right, env))
            elif action == "check":
                _checked(values[-1], task[1])
            elif action == "invoke":
                _, name, arity = task
                args = values[-arity:] if arity else []
                if arity:
                    del values[-arity:]
                function = self.functions.get(name)
                if function is None:
                    values.append(_checked(self.builtin(name, args), "int"))
                else:
                    parameters = function["parameters"]
                    if arity != len(parameters):
                        raise ValueError(f"transform wrong argument count for {name!r}")
                    env = {arg: _checked(value, kind) for (arg, kind), value in zip(parameters, args)}
                    tasks.append(("check", function["return_type"]))
                    tasks.append(("expr", function["expression"], env))
        return values[0]


def evaluate(program: Program, report: dict) -> dict[str, int | bool | str]:
    """Return exact scalar metrics in declaration order without mutating inputs.

    Only reached expressions use the shared step budget. Coverage preparation
    takes one pass over the host's cells and keeps only bounded enum counters.
    """
    runtime = _Evaluation(program, report)
    return {
        metric["name"]: _checked(
            runtime.expression(metric["expression"]), program.metric_types[metric["name"]],
        )
        for metric in program.metrics
    }
