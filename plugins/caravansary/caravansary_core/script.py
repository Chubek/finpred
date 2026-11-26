"""Lexer, parser, and validation for the CaravanScript v1 collection profile."""

import json
import os
import re
from datetime import date
from decimal import Decimal
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .credentials import PROVIDER_HOSTS, validate_declarations


_SOURCES = frozenset(PROVIDER_HOSTS)
_REQUEST_FIELDS = frozenset(
    f"{source}_{field}"
    for source in _SOURCES
    for field in ("requests_per_hour", "concurrency")
)
_REQUIRED = {
    "property": {"type", "latitude", "longitude", "timezone", "currency", "room_types"},
    "search": {
        "horizon_days", "start", "guest_configurations", "stay_lengths", "booker_country",
        "locale",
    },
    "refresh": {"tick_seconds", "weights", "max_age_seconds"},
    "output": {"observations", "coverage"},
}
_FIELDS = {"competitors", "sources"}
_BLOCKS = _REQUIRED.keys() | {"credentials"}
_TRIVIA = re.compile(r"(?:[ \t\n\r\f\v]+|#[^\r\n]*)*")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[0-9]+|[{}=\[\],;]")
_STRING = json.JSONDecoder()
_LINE_BREAK = re.compile(r"\r\n?|\n")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ZONE = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")

# ISO 3166-1 assigned alpha-2 and ISO 4217 active alpha-3 codes, from
# iso-codes 4.20.1. Only the machine identifiers, not the translated names.
_COUNTRIES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN
BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL
GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM
JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME
MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP
NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD
SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO
TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())
_CURRENCIES = frozenset("""
AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BOV BRL BSD BTN
BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD
EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR
IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD
MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD
OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE
SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI
UYU UYW UZS VED VES VND VUV WST XAD XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD
XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG
""".split())

# RFC 5646's fixed grandfathered list and current language extension
# singleton registrations. Subtags are checked structurally, not against a
# bundled edition of the IANA Language Subtag Registry.
_GRANDFATHERED = frozenset("""
art-lojban cel-gaulish en-gb-oed i-ami i-bnn i-default i-enochian i-hak
i-klingon i-lux i-mingo i-navajo i-pwn i-tao i-tay i-tsu no-bok no-nyn
sgn-be-fr sgn-be-nl sgn-ch-de zh-guoyu zh-hakka zh-min zh-min-nan zh-xiang
""".split())
_BCP47_PART = re.compile(r"[a-z0-9]{1,8}", re.ASCII)


def _language_tag(value):
    if not value.isascii():
        return False
    value = value.lower()
    if value in _GRANDFATHERED:
        return True
    parts = value.split("-")
    if not all(_BCP47_PART.fullmatch(part) for part in parts):
        return False
    if parts[0] == "x":
        return len(parts) > 1
    primary = parts[0]
    if not primary.isalpha() or len(primary) < 2:
        return False

    i, end = 1, len(parts)
    if len(primary) <= 3:
        for _ in range(3):
            if i == end or len(parts[i]) != 3 or not parts[i].isalpha():
                break
            i += 1
    if i < end and len(parts[i]) == 4 and parts[i].isalpha():
        i += 1
    if i < end and (
        (len(parts[i]) == 2 and parts[i].isalpha())
        or (len(parts[i]) == 3 and parts[i].isdigit())
    ):
        i += 1

    variants = set()
    while i < end and (len(parts[i]) >= 5 or (len(parts[i]) == 4 and parts[i][0].isdigit())):
        if parts[i] in variants:
            return False
        variants.add(parts[i])
        i += 1

    extensions = set()
    while i < end and parts[i] in ("t", "u"):
        if parts[i] in extensions:
            return False
        extensions.add(parts[i])
        i += 1
        start = i
        while i < end and len(parts[i]) >= 2:
            i += 1
        if i == start:
            return False
    return i == end or (parts[i] == "x" and i + 1 < end)


class _Token(NamedTuple):
    kind: str
    value: object
    offset: int


class _Parser:
    def __init__(self, text):
        self.text = text
        self.position = 0
        self.token = self._next()

    def _error(self, message, offset):
        line, last = 1, 0
        for match in _LINE_BREAK.finditer(self.text, 0, offset):
            line += 1
            last = match.end()
        return ValueError(f"line {line}, column {offset - last + 1}: {message}")

    def _next(self):
        text = self.text
        offset = _TRIVIA.match(text, self.position).end()
        if offset == len(text):
            return _Token("end of input", None, offset)
        if text[offset] == '"':
            try:
                value, self.position = _STRING.raw_decode(text, offset)
            except ValueError:
                raise self._error("invalid JSON string", offset) from None
            if _SURROGATE.search(value):
                raise self._error("unpaired Unicode surrogate", offset)
            return _Token("string", value, offset)

        match = _TOKEN.match(text, offset)
        if match is None:
            raise self._error("unexpected character", offset)
        value = match[0]
        self.position = match.end()
        if value[0].isdigit():
            if len(value) > 1 and value[0] == "0":
                raise self._error("integer cannot have leading zeros", offset)
            try:
                number = int(value, 10)
            except ValueError:
                raise self._error("integer is too large", offset) from None
            return _Token("integer", number, offset)
        return _Token("identifier" if value[0].isalpha() else value, value, offset)

    def _take(self, kind, expected=None):
        token = self.token
        if token.kind != kind or (expected is not None and token.value != expected):
            raise self._error(f"expected {expected or kind}", token.offset)
        if kind != "end of input":
            self.token = self._next()
        return token.value

    def _scalar(self):
        if self.token.kind not in ("integer", "string"):
            raise self._error("expected a string or integer", self.token.offset)
        return self._take(self.token.kind)

    def _value(self):
        if self.token.kind != "[":
            return self._scalar()
        self._take("[")
        items = []
        if self.token.kind != "]":
            items.append(self._scalar())
            while self.token.kind == ",":
                self._take(",")
                items.append(self._scalar())
        self._take("]")
        return items

    def _field(self):
        self._take("=")
        value = self._value()
        self._take(";")
        return value

    def _statements(self, fields, blocks, *, context):
        self._take("{")
        values = {}
        while self.token.kind != "}":
            offset = self.token.offset
            key = self._take("identifier")
            if key in values:
                raise self._error(f"duplicate field or block in {context}", offset)
            if key in fields:
                values[key] = self._field()
            elif key in blocks:
                if key == "credentials":
                    values[key] = self._statements((), _SOURCES, context=key)
                elif context == "credentials":
                    values[key] = self._statements(
                        {"cookies", "environment", "dotenv", "explicit"}, (),
                        context=f"credentials.{key}",
                    )
                else:
                    optional = _REQUEST_FIELDS if key == "refresh" else set()
                    values[key] = self._statements(_REQUIRED[key] | optional, (), context=key)
            else:
                raise self._error(f"unknown field or block in {context}", offset)
        self._take("}")
        return values

    def script(self):
        self._take("identifier", "caravan")
        name = self._take("string")
        self._take("identifier", "version")
        if self._take("integer") != 1:
            raise ValueError("unsupported CaravanScript version; expected 1")
        config = self._statements(_FIELDS, _BLOCKS, context="script")
        self._take("end of input")
        return {"name": name, "version": 1, **config}


def _require_fields(values, required, where):
    missing = required - values.keys()
    if missing:
        raise ValueError(f"{where} is missing fields: {', '.join(sorted(missing))}")


def _nonempty_text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a nonempty string")


def _file_path(value, where):
    _nonempty_text(value, where)
    if (
        any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        or re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", value)
        or os.path.basename(value) in ("", ".", "..")
    ):
        raise ValueError(f"{where} must be a local file path")


def _positive(value, where):
    if type(value) is not int or value < 1:
        raise ValueError(f"{where} must be a positive integer")


def _unique_array(values, where, validate):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{where} must be a nonempty array")
    seen = set()
    for item in values:
        validate(item, where)
        if item in seen:
            raise ValueError(f"{where} must not contain duplicates")
        seen.add(item)


def _source(value, where):
    if value not in _SOURCES:
        raise ValueError(f"{where} must contain only booking and/or agoda")


def _validate(config):
    _require_fields(config, _FIELDS | _REQUIRED.keys(), "script")
    for block, required in _REQUIRED.items():
        _require_fields(config[block], required, block)

    _file_path(config["competitors"], "competitors")
    _unique_array(config["sources"], "sources", _source)
    prop = config["property"]
    _nonempty_text(prop["type"], "property.type")
    _unique_array(prop["room_types"], "property.room_types", _nonempty_text)
    for field, bound in (("latitude", 90), ("longitude", 180)):
        value = prop[field]
        if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
            raise ValueError(f"property.{field} must be a decimal string")
        if not -bound <= Decimal(value) <= bound:
            raise ValueError(f"property.{field} must be between {-bound} and {bound}")

    zone = prop["timezone"]
    if (
        not isinstance(zone, str) or not _ZONE.fullmatch(zone)
        or zone in {"localtime", "posixrules"} or zone.partition("/")[0] in {"posix", "right"}
    ):
        raise ValueError("property.timezone must be an IANA zone name")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, OSError, ValueError):
        raise ValueError("property.timezone is not available in the host IANA timezone database") from None
    currency = prop["currency"]
    if not isinstance(currency, str) or currency not in _CURRENCIES:
        raise ValueError("property.currency must be an ISO 4217 alpha-3 code")

    search = config["search"]
    horizon = search["horizon_days"]
    _positive(horizon, "search.horizon_days")
    if horizon > 365:
        raise ValueError("search.horizon_days must be between 1 and 365")
    start = search["start"]
    if start != "today":
        if not isinstance(start, str) or not _DATE.fullmatch(start):
            raise ValueError("search.start must be today or a YYYY-MM-DD date")
        try:
            date.fromisoformat(start)
        except ValueError:
            raise ValueError("search.start must be a valid Gregorian date") from None
    _unique_array(search["guest_configurations"], "search.guest_configurations", _nonempty_text)
    _unique_array(search["stay_lengths"], "search.stay_lengths", _positive)
    country = search["booker_country"]
    if not isinstance(country, str) or country not in _COUNTRIES:
        raise ValueError("search.booker_country must be an ISO 3166-1 alpha-2 code")
    locale = search["locale"]
    if not isinstance(locale, str) or not _language_tag(locale):
        raise ValueError("search.locale must be a BCP 47 language tag")

    refresh = config["refresh"]
    needed = {
        field for field in _REQUEST_FIELDS
        if field.partition("_")[0] in config["sources"]
    }
    _require_fields(refresh, needed, "refresh")
    _file_path(refresh["weights"], "refresh.weights")
    for field, value in refresh.items():
        if field != "weights":
            _positive(value, f"refresh.{field}")

    output = config["output"]
    for field, value in output.items():
        _file_path(value, f"output.{field}")
    paths = {os.path.normcase(os.path.normpath(path)) for path in output.values()}
    if len(paths) != len(output):
        raise ValueError("output.observations and output.coverage must be distinct paths")

    if "credentials" in config:
        validate_declarations(config["credentials"], config["sources"])
        for source, declaration in config["credentials"].items():
            for field in declaration.keys() & {"cookies", "dotenv"}:
                _file_path(declaration[field], f"credentials.{source}.{field}")


def parse(text):
    """Parse and validate v1 text without loading referenced files or secrets."""
    if not isinstance(text, str) or _SURROGATE.search(text):
        raise ValueError("CaravanScript source must be UTF-8 text")
    config = _Parser(text).script()
    _validate(config)
    return config
