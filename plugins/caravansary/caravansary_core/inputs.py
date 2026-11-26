"""Offline validation for the Caravansary v1 competitor and joint-weight files."""

import json
import math
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


_SOURCES = {"booking", "agoda"}
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


def _unique_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON field {key!r}")
        obj[key] = value
    return obj


def _finite_float(literal):
    number = float(literal)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds floating-point range")
    if number == 0 and any(c in "123456789" for c in literal.lower().partition("e")[0]):
        raise ValueError("nonzero JSON number underflows to zero")
    return number


def _invalid_constant(literal):
    raise ValueError(f"{literal} is not a JSON number")


def parse_json(text):
    """Decode strict JSON, rejecting duplicate keys and invalid Unicode scalars."""
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_fields,
            parse_float=_finite_float,
            parse_constant=_invalid_constant,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc

    pending = [value]
    while pending:
        part = pending.pop()
        if isinstance(part, dict):
            pending.extend(part.keys())
            pending.extend(part.values())
        elif isinstance(part, list):
            pending.extend(part)
        elif isinstance(part, str) and _SURROGATE.search(part):
            raise ValueError("JSON string contains an unpaired Unicode surrogate")
    return value


def _load(path, validator, *args):
    path = Path(path)
    try:
        return validator(parse_json(path.read_text(encoding="utf-8")), *args)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _object(value, required, where, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    missing = set(required) - value.keys()
    if missing:
        raise ValueError(f"{where} is missing fields: {', '.join(sorted(missing))}")
    unknown = value.keys() - set(required) - set(optional)
    if unknown:
        raise ValueError(f"{where} has unknown fields: {', '.join(sorted(unknown))}")
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a nonempty string")
    return value


def _positive_integer(value, where):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{where} must be a positive integer")
    return value


def _child_ages(value, where):
    ages = _array(value, where)
    if any(type(age) is not int or not 0 <= age <= 17 for age in ages):
        raise ValueError(f"{where} must contain only integer ages from 0 to 17")
    return ages


def _guest(value, where):
    guest = _object(value, ("id", "rooms", "adults", "child_ages"), where, ("allocation",))
    _text(guest["id"], f"{where}.id")
    rooms = _positive_integer(guest["rooms"], f"{where}.rooms")
    adults = _positive_integer(guest["adults"], f"{where}.adults")
    ages = _child_ages(guest["child_ages"], f"{where}.child_ages")

    if "allocation" not in guest:
        if rooms != 1:
            raise ValueError(f"{where}.allocation is required for more than one room")
        return {**guest, "allocation": [{"adults": adults, "child_ages": list(ages)}]}

    allocation = _array(guest["allocation"], f"{where}.allocation")
    if len(allocation) != rooms:
        raise ValueError(f"{where}.allocation must have exactly one entry per room")
    allocated_adults = 0
    allocated_ages = Counter()
    for index, room in enumerate(allocation):
        room_at = f"{where}.allocation[{index}]"
        room = _object(room, ("adults", "child_ages"), room_at)
        allocated_adults += _positive_integer(room["adults"], f"{room_at}.adults")
        allocated_ages.update(_child_ages(room["child_ages"], f"{room_at}.child_ages"))
    if allocated_adults != adults or allocated_ages != Counter(ages):
        raise ValueError(f"{where}.allocation does not match the stated party")
    return guest


def _coordinate(value, bound, where):
    if isinstance(value, str) and _DECIMAL.fullmatch(value):
        value = Decimal(value)
    elif type(value) not in (int, float):
        raise ValueError(f"{where} must be a decimal coordinate")
    if not -bound <= value <= bound:
        raise ValueError(f"{where} must be between {-bound} and {bound}")


def _provider_url(value, where):
    url = _text(value, where)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "\\" for c in url):
        raise ValueError(f"{where} must be an absolute HTTP(S) URL without credentials")
    try:
        parsed = urlsplit(url)
        # Reading port also validates its numeric syntax and range.
        port = parsed.port
        valid = (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and parsed.username is None
            and port != 0
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{where} must be an absolute HTTP(S) URL without credentials")


def _property(value, where, verified):
    prop = _object(
        value, ("id", "name", "providers"), where, ("type", "latitude", "longitude"),
    )
    _text(prop["id"], f"{where}.id")
    _text(prop["name"], f"{where}.name")
    if "type" in prop:
        _text(prop["type"], f"{where}.type")
    for field, bound in (("latitude", 90), ("longitude", 180)):
        if field in prop:
            _coordinate(prop[field], bound, f"{where}.{field}")

    providers = _object(prop["providers"], (), f"{where}.providers", _SOURCES)
    locators = ("provider_property_id", "url")
    for source, value in providers.items():
        at = f"{where}.providers.{source}"
        mapping = _object(value, ("mapping_status",), at, locators)
        status = mapping["mapping_status"]
        if status not in ("verified", "unverified", "missing"):
            raise ValueError(f"{at}.mapping_status must be verified, unverified, or missing")
        present = [field for field in locators if field in mapping]
        if status == "missing":
            if present:
                raise ValueError(f"{at}: a missing mapping cannot have a provider identity")
            continue
        if not present:
            raise ValueError(f"{at} requires a provider_property_id and/or url")
        if "provider_property_id" in mapping:
            _text(mapping["provider_property_id"], f"{at}.provider_property_id")
        if "url" in mapping:
            _provider_url(mapping["url"], f"{at}.url")
        if status == "verified":
            for field in present:
                # IDs and URLs are separate, opaque identity namespaces.
                identity = (source, field, mapping[field])
                if identity in verified:
                    raise ValueError(f"{at} duplicates a verified {source} {field}")
                verified.add(identity)
    return prop


def _competitors(value):
    obj = _object(value, ("kind", "guest_configurations", "properties"), "competitor document")
    if obj["kind"] != "caravansary.competitors@1":
        raise ValueError("competitor document kind must be caravansary.competitors@1")
    guests = {}
    for index, value in enumerate(_array(obj["guest_configurations"], "guest_configurations")):
        at = f"guest_configurations[{index}]"
        guest = _guest(value, at)
        if guest["id"] in guests:
            raise ValueError(f"{at}.id duplicates a guest configuration ID")
        guests[guest["id"]] = guest

    properties, ids, verified = [], set(), set()
    for index, value in enumerate(_array(obj["properties"], "properties")):
        at = f"properties[{index}]"
        prop = _property(value, at, verified)
        if prop["id"] in ids:
            raise ValueError(f"{at}.id duplicates a property ID")
        ids.add(prop["id"])
        properties.append(prop)
    return guests, properties


def load_competitors(path):
    """Load a v1 file as (guests keyed by ID, properties in input order)."""
    return _load(path, _competitors)


def _weights(value, guest_ids, stay_lengths):
    obj = _object(value, ("kind", "mode", "source", "weights"), "weight document")
    if obj["kind"] != "caravansary.weights@1":
        raise ValueError("weight document kind must be caravansary.weights@1")
    if obj["mode"] != "joint":
        raise ValueError("weight mode must be joint")
    _text(obj["source"], "weight source")

    guests, stays = set(guest_ids), set(stay_lengths)
    weights = {}
    for index, value in enumerate(_array(obj["weights"], "weights")):
        at = f"weights[{index}]"
        entry = _object(value, ("guest_configuration", "stay_length", "weight"), at)
        guest = _text(entry["guest_configuration"], f"{at}.guest_configuration")
        stay = _positive_integer(entry["stay_length"], f"{at}.stay_length")
        if guest not in guests or stay not in stays:
            raise ValueError(f"{at} is for an unconfigured guest/stay pair")
        key = (guest, stay)
        if key in weights:
            raise ValueError(f"{at} duplicates a guest/stay pair")
        weight = entry["weight"]
        if type(weight) not in (int, float) or weight < 0:
            raise ValueError(f"{at}.weight must be a nonnegative finite number")
        weights[key] = weight
    # With membership and uniqueness checked above, the cardinality proves
    # completeness without allocating the Cartesian product.
    if len(weights) != len(guests) * len(stays):
        raise ValueError("weights are required for every configured guest/stay pair")
    if not any(weight > 0 for weight in weights.values()):
        raise ValueError("at least one weight must be positive")
    return weights


def load_weights(path, guest_ids, stay_lengths):
    """Load a complete joint matrix for the script-selected guests and stays."""
    return _load(path, _weights, guest_ids, stay_lengths)
