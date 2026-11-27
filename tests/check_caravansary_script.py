#!/usr/bin/env python3
"""Offline lexer, script schema, and synthetic credential resolution checks."""

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "caravansary"))
from caravansary_core.credentials import resolve
from caravansary_core.script import parse


EXAMPLE = (ROOT / "docs/caravansary/examples/riviera.crs").read_text(encoding="utf-8")
MARKER = "SYNTHETIC-ONLY-NOT-A-SECRET"


def invalid(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except ValueError as error:
        assert MARKER not in str(error)
    else:
        raise AssertionError("invalid input accepted")


def with_credentials(body):
    return EXAMPLE + "\ncredentials {" + body + "}\n"


config = parse(EXAMPLE)
assert config["name"] == "Riviera Hotel" and "version" not in config
unnamed = EXAMPLE.replace('name = "Riviera Hotel";', "")
assert "name" not in parse(unnamed)
assert parse(unnamed + '\nname = "Riviera Hotel";') == config
assert config["property"]["latitude"] == "43.000000"
assert parse(EXAMPLE.replace("Riviera Hotel", r"\uD83D\uDE00 #"))["name"] == "😀 #"
assert parse("# comment\r" + EXAMPLE + "# end") == config
assert parse(EXAMPLE.replace('start = "today"', 'start = "2024-02-29"'))
assert parse(EXAMPLE.replace("365", "1").replace("43.000000", "-90.000000"))
assert parse(EXAMPLE.replace('"booking", "agoda"', '"booking"'))
for tag in ("zh-cmn-Hans-CN", "de-CH-1901", "en-u-ca-gregory-x-Acme", "es-419", "i-klingon"):
    assert parse(EXAMPLE.replace("fr-FR", tag))["search"]["locale"] == tag

for old, new in [
    ("Riviera Hotel", r"\uD800"),
    ("Riviera Hotel", r"\x00"),
    ("Riviera Hotel", "literal\nnewline"),
    ('name = "Riviera Hotel";', 'name = 1;'),
    ('name = "Riviera Hotel";', 'name = ["Riviera Hotel"];'),
    ('name = "Riviera Hotel";', 'name = "one"; name = "two";'),
    ("property {", "property = 1; property {"),
    ("property {", "property { property {}"),
    ("search {", "search { _not_identifier = 1;"),
    ('type = "hotel";', 'type = "hotel"; type = "hotel";'),
    ('type = "hotel";', 'unknown = "hotel";'),
    ('type = "hotel";', ""),
    ('["standard", "suite"]', "[]"),
    ('["standard", "suite"]', '["standard", "standard"]'),
    ('["standard", "suite"]', '["standard", ["suite"]]'),
    ('["standard", "suite"]', '["standard", "suite",]'),
    ('"booking", "agoda"', '"booking", "booking"'),
    ('"booking", "agoda"', '"booking", "unknown"'),
    ('"43.000000"', "43"),
    ("43.000000", "9e1"),
    ("43.000000", "90.0000000000000000000001"),
    ("43.000000", "NaN"),
    ("7.000000", "-180.01"),
    ("Europe/Paris", "Unknown/Timezone"),
    ("Europe/Paris", "../Europe/Paris"),
    ("Europe/Paris", "right/Europe/Paris"),
    ("EUR", "ZZZ"),
    ("EUR", "eur"),
    ("horizon_days = 365", "horizon_days = 366"),
    ('"today"', '"2026-02-29"'),
    ('"today"', '"20240229"'),
    ('"today"', '"2024-02-29T00:00:00Z"'),
    ('"today"', '"0000-01-01"'),
    ('"FR"', '"ZZ"'),
    ('"FR"', '"fr"'),
    ("fr-FR", "fr_FR"),
    ("fr-FR", "fr--FR"),
    ("fr-FR", "de-1901-1901"),
    ("fr-FR", "en-u-ca-gregory-u-nu-latn"),
    ("fr-FR", "en-x"),
    ("[1, 2, 3]", "[0]"),
    ("[1, 2, 3]", "[+1]"),
    ("[1, 2, 3]", "[1 2 3]"),
    ("[1, 2, 3]", '["1"]'),
    ("agoda_concurrency = 1;", ""),
    ("agoda_concurrency = 1;", "agoda_concurrency = 0;"),
    ("coverage.json", "./observations.jsonl"),
    ("coverage.json", "."),
    ("coverage.json", "file:///tmp/out"),
    ("coverage.json", r"out\u0000.tmp"),
]:
    assert old in EXAMPLE
    invalid(parse, EXAMPLE.replace(old, new, 1))
invalid(parse, EXAMPLE + "trailing")
invalid(parse, EXAMPLE + "}")
invalid(parse, "{" + EXAMPLE + "}")
invalid(parse, "version = 1;\n" + EXAMPLE)
invalid(parse, 'caravan "Riviera Hotel" version 1 {\n' + unnamed + "}")
invalid(parse, 'caravan "Riviera Hotel" version 2 {\n' + unnamed + "}")
invalid(parse, EXAMPLE + "# unpaired \ud800")
invalid(parse, EXAMPLE.encode())
assert resolve(config, "booking") is None

for body in (
    "",
    "bogus {}",
    "booking {}",
    'booking { cookies = "c.json"; cookies = "c.json"; }',
    'booking { cookies = "c.json"; } booking { cookies = "c.json"; }',
    'booking { cookies = "c.json"; environment = ["KEY"]; }',
    'booking { explicit = ["api_key"]; dotenv = ".env"; }',
    'booking { explicit = "plaintext"; }',
    'booking { explicit = ["api_key", "api_key"]; }',
    'booking { environment = ["A=B"]; }',
):
    invalid(parse, with_credentials(body))
invalid(parse, with_credentials('agoda { cookies = "c.json"; }')
        .replace('"booking", "agoda"', '"booking"'))

explicit_config = parse(with_credentials('booking { explicit = ["site_id", "api_key"]; }'))
result = resolve(explicit_config, "booking", explicit={"site_id": "synthetic", "api_key": MARKER})
assert result.mode == "explicit" and result.values["api_key"] == MARKER
assert MARKER not in repr(result) and MARKER not in repr(result.values)
assert resolve(explicit_config, "agoda") is None
invalid(resolve, explicit_config, "booking", environ={"site_id": "synthetic", "api_key": MARKER})
invalid(resolve, explicit_config, "booking", explicit={"site_id": "synthetic", "api_key": '\0'})

env_config = parse(with_credentials(
    'agoda { environment = ["SITE_ID", "API_KEY", "_NO_EXPANSION"]; dotenv = ".env"; }'
))
env_data = (
    f'export SITE_ID = unused\r\nAPI_KEY = "{MARKER}" # fixture\r\n'
    "_NO_EXPANSION = '${SITE_ID}'\r\nUNUSED=not-read\r\n"
).encode()
env_approval = {("agoda", "dotenv", ".env"): env_data}
result = resolve(env_config, "agoda", environ={"SITE_ID": "synthetic"}, approved_files=env_approval)
assert dict(result.values) == {"SITE_ID": "synthetic", "API_KEY": MARKER, "_NO_EXPANSION": "${SITE_ID}"}
invalid(resolve, env_config, "agoda", environ={"SITE_ID": "synthetic"})
invalid(resolve, env_config, "agoda", environ={"SITE_ID": ""}, approved_files=env_approval)
for bad in (b"API_KEY='bad\n", b"API_KEY=1\nAPI_KEY=2", b"API_KEY=\xff"):
    invalid(resolve, env_config, "agoda", approved_files={("agoda", "dotenv", ".env"): bad})

cookie_config = parse(with_credentials('agoda { cookies = "cookie.json"; }'))
approval = ("agoda", "cookies", "cookie.json")
cookie = {
    "name": "fictional", "value": MARKER, "domain": ".Agoda.COM", "path": "/cup",
    "secure": True, "sameSite": "Lax", "hostOnly": False, "expires": 253402300799,
}


def cookie_bytes(*cookies):
    return json.dumps(cookies).encode()


result = resolve(cookie_config, "agoda", approved_files={approval: cookie_bytes(cookie)})
assert result.mode == "cookies" and result.cookies[0].value == MARKER
assert result.cookies[0].domain == "agoda.com" and not result.cookies[0].host_only
assert MARKER not in repr(result) and MARKER not in repr(result.cookies)
assert not resolve(cookie_config, "agoda", approved_files={approval: b"[]"}).cookies
invalid(resolve, cookie_config, "agoda", approved_files={("booking", *approval[1:]): cookie_bytes(cookie)})
for changes in (
    {"domain": "elsewhere.com"}, {"domain": "www.agoda.com.example"}, {"domain": ".com"},
    {"domain": "agoda.com", "hostOnly": True}, {"domain": ".www.agoda.com", "hostOnly": True},
    {"name": "__Host-session"}, {"name": "__Secure-session", "secure": False},
    {"sameSite": "None", "secure": False}, {"sameSite": "strict"}, {"secure": 1}, {"hostOnly": 1},
    {"path": "/cup?name=x"}, {"value": "bad;value"}, {"value": "bäd"}, {"expires": 1.0},
    {"expires": 253402300800}, {"unknown": None},
):
    invalid(resolve, cookie_config, "agoda", approved_files={approval: cookie_bytes(cookie | changes)})
for bad_bytes in (
    b"", b"x" * (64 * 1024 + 1), b"[[]" + b"]", b'[{"value": 1, "value": 2}]',
    cookie_bytes(cookie, cookie | {"domain": "AGODA.COM", "value": "another"}),
):
    invalid(resolve, cookie_config, "agoda", approved_files={approval: bad_bytes})

booking_fixture = (Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib"))
                   / "tests/fixtures/elvi-script/booking-cookies.json")
booking_config = parse(with_credentials('booking { cookies = "booking-fixture.json"; }'))
booking_secrets = resolve(booking_config, "booking", approved_files={
    ("booking", "cookies", "booking-fixture.json"): booking_fixture.read_bytes(),
})
assert len(booking_secrets.cookies) == 1
assert booking_secrets.cookies[0].domain == "booking.com"

print("caravansary script and credential resolver: OK")
