#!/usr/bin/env python3
"""Offline CaravanScript transformation grammar and parser-bound checks."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "caravansary"))
from caravansary_core.script import parse


BASE = (ROOT / "docs/caravansary/examples/riviera.crs").read_text(encoding="utf-8")


def with_transform(body, base=BASE):
    return "transform {\n" + body + "\n}\n" + base


def invalid(source, message="", *, syntax=True):
    try:
        parse(source)
    except ValueError as error:
        assert message in str(error), str(error)
        if syntax:
            assert str(error).startswith("line ") and ", column " in str(error), str(error)
    else:
        raise AssertionError("invalid transform accepted")


config = parse(with_transform(r'''
    emit first = not false and later(4, 2 - 1 - 1) * 2 >= 5 or false;
    fn later(a: int, b: int) -> int { return a + b; }
    emit second = (true == false) != false;
    fn textValue() -> text { return "\ud83d\ude00 #"; }
    emit third = textValue();
'''))
assert "version" not in config
assert {key: value for key, value in config.items() if key != "transform"} == parse(BASE)
credentials = 'credentials { booking { cookies = "approved.json"; } }\n'
with_credentials = BASE + "\n" + credentials
assert parse(with_transform("emit cells = total_cells();", with_credentials))["credentials"] == {
    "booking": {"cookies": "approved.json"},
}
transform = config["transform"]
assert json.loads(json.dumps(transform)) == transform
assert transform["functions"] == [
    {
        "name": "later", "parameters": [["a", "int"], ["b", "int"]], "return_type": "int",
        "expression": ["binary", "+", ["name", "a"], ["name", "b"]],
    },
    {
        "name": "textValue", "parameters": [], "return_type": "text",
        "expression": ["literal", "😀 #"],
    },
]
assert transform["metrics"] == [
    {
        "name": "first", "expression": [
            "binary", "or",
            [
                "binary", "and", ["unary", "not", ["literal", False]],
                [
                    "binary", ">=",
                    [
                        "binary", "*",
                        ["call", "later", [
                            ["literal", 4],
                            ["binary", "-", ["binary", "-", ["literal", 2], ["literal", 1]], ["literal", 1]],
                        ]],
                        ["literal", 2],
                    ],
                    ["literal", 5],
                ],
            ],
            ["literal", False],
        ],
    },
    {"name": "second", "expression": [
        "binary", "!=", ["binary", "==", ["literal", True], ["literal", False]], ["literal", False],
    ]},
    {"name": "third", "expression": ["call", "textValue", []]},
]

valid_body = "emit output_count = total_cells();"
invalid("version = 2;\n" + with_transform(valid_body), "unknown field or block")
invalid('caravan "Former script" version 2 {\n' + with_transform(valid_body) + "}", "unknown field or block")
invalid(with_transform(valid_body, with_transform(valid_body)), "duplicate field or block")
invalid(with_transform(valid_body).replace("output {", "output { transform {}"), "unknown field or block")
invalid(with_transform(""), "requires at least one emit")
invalid(with_transform("fn empty() -> int { return 0; }"), "requires at least one emit")
invalid(with_transform("emit output_count = no_such_builtin();"), syntax=False)
invalid(with_transform("emit output_count = 1 \"and\" 2;"), "expected ;")
invalid(with_transform("emit output_count = true == false != true;"), "comparison chaining")
invalid(with_transform("emit output_count = 0 < 1 > 2;"), "comparison chaining")
invalid(with_transform("emit output_count = status_count(\"fresh\",);"))
invalid(with_transform(valid_body + "fn f(a: int,) -> int { return a; }"))
invalid(with_transform(valid_body + "fn f(a: number) -> int { return a; }"), "expected int, bool, or text")
invalid(with_transform(valid_body + "fn f(a: int) -> int { emit a = 0; }"), "expected return")
for name in "fn emit return int bool text true false not and or".split():
    invalid(with_transform(f"emit {name} = 0;"), "reserved")
for expression in ("+1", "01", "-1.5", "_variable", "[]", r'"\uD800"'):
    invalid(with_transform(f"emit value = {expression};"))


def metric(expression):
    return with_transform(f"emit value = {expression};")


assert parse(metric("-9223372036854775807 - 1"))
invalid(metric("-9223372036854775808"), "signed 64-bit")
invalid(metric("1" * 5000), "signed 64-bit")
assert parse(metric(json.dumps("é" * 2048)))
invalid(metric(json.dumps("é" * 2049)), "4096 bytes")
assert parse(metric(" + ".join("1" for _ in range(64))))
invalid(metric(" + ".join("1" for _ in range(65))), "depth 64")
assert parse(metric("(" * 64 + "1" + ")" * 64))
invalid(metric("(" * 2000 + "1" + ")" * 2000), "nesting")
invalid(metric("status_count(" * 2000 + '""' + ")" * 2000), "nesting")

decls = "".join(f"fn f{i}() -> int {{ return 0; }}\n" for i in range(64))
assert parse(with_transform(decls + valid_body))
invalid(with_transform(decls + "fn overflow() -> int { return 0; }\n" + valid_body), "64 functions")
decls = "".join(f"emit m{i} = 0;\n" for i in range(64))
assert parse(with_transform(decls))
invalid(with_transform(decls + valid_body), "64 metrics")
params = ", ".join(f"p{i}: int" for i in range(16))
args = ", ".join("1" for _ in range(16))
decl = f"fn bound({params}) -> int {{ return p0; }}\n"
assert parse(with_transform(decl + f"emit value = bound({args});"))
invalid(with_transform(decl + f"emit value = bound({args}, 1);"), "16 items")
invalid(with_transform(decl.replace(params, params + ", extra: int") + valid_body), "16 items")

# A balanced expression with an extra unary node has exactly 64 AST nodes.
expression = "1"
for _ in range(5):
    expression = f"({expression} + {expression})"
decls = "".join(f"emit m{i} = -{expression};\n" for i in range(63))
assert parse(with_transform(decls + f"emit value = -{expression};"))
invalid(with_transform(decls + f"emit value = --{expression};"), "4096 expression nodes")

print("caravansary transformation syntax: OK")
