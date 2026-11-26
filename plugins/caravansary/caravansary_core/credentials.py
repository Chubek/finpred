"""Host-only resolution of credential references. No I/O or ambient authority."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


PROVIDER_HOSTS = MappingProxyType({"booking": "booking.com", "agoda": "www.agoda.com"})
_MODES = frozenset({"cookies", "environment", "explicit"})
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOTENV_LINE = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)")
_DOTENV_COMMENT = re.compile(r"(?:^|[ \t]+)#")
_SINGLE_QUOTE = re.compile(r"'([^']*)'")
_INVALID_TEXT = re.compile(r"[\0\ud800-\udfff]")
_COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "sameSite"}
_COOKIE_OPTIONAL = {"hostOnly", "expires"}
_COOKIE_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+\-.^_`|~]{1,128}")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]{0,2048}")
_COOKIE_PATH = re.compile(r"/[\x21-\x22\x24-\x3a\x3c-\x3e\x40-\x5b\x5d-\x7e]{0,1023}")
_MAX_FILE_BYTES = 64 * 1024
_DECODER = json.JSONDecoder()


class _SecretValues(Mapping):
    def __init__(self, values=()):
        self._values = dict(values)

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return "<redacted credential values>"


@dataclass(frozen=True, slots=True)
class Cookie:
    """Validated Cookie JSON v1 entry, not a request header."""

    name: str = field(repr=False)
    value: str = field(repr=False)
    domain: str = field(repr=False)
    path: str = field(repr=False)
    secure: bool = field(repr=False)
    same_site: str = field(repr=False)
    host_only: bool = field(repr=False)
    expires: int | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """Host-owned secret material; repr never displays values or cookies."""

    mode: str
    values: Mapping = field(default_factory=_SecretValues, repr=False)
    cookies: tuple[Cookie, ...] = field(default=(), repr=False)


def validate_declarations(declarations, sources):
    """Validate credential declarations without inspecting secret material."""
    if not isinstance(declarations, dict) or not declarations:
        raise ValueError("credentials must contain at least one source block")
    for source, declaration in declarations.items():
        if source not in PROVIDER_HOSTS or source not in sources:
            raise ValueError("credentials can be declared only for a selected source")
        if not isinstance(declaration, dict):
            raise ValueError(f"credentials.{source} must be a source block")
        modes = _MODES & declaration.keys()
        if len(modes) != 1:
            raise ValueError(f"credentials.{source} must select exactly one credential mode")
        mode, = modes
        optional = {"dotenv"} if mode == "environment" else set()
        if declaration.keys() - {mode} - optional:
            raise ValueError(f"credentials.{source} has fields not allowed for this mode")
        if mode != "cookies":
            names = declaration[mode]
            if (
                not isinstance(names, list) or not names
                or not all(isinstance(name, str) and _KEY.fullmatch(name) for name in names)
                or len(set(names)) != len(names)
            ):
                raise ValueError(f"credentials.{source}.{mode} must list unique reference names")
        for kind in declaration.keys() & {"cookies", "dotenv"}:
            path = declaration[kind]
            if not isinstance(path, str) or not path.strip() or _INVALID_TEXT.search(path):
                raise ValueError(f"credentials.{source}.{kind} must be a file reference")


def _approved_bytes(approved_files, source, kind, declared_path):
    if isinstance(approved_files, Mapping):
        data = approved_files.get((source, kind, declared_path))
        if isinstance(data, bytes) and len(data) <= _MAX_FILE_BYTES:
            return data
    raise ValueError(f"{source} {kind} requires host-approved bytes (max 64 KiB)")


def _strict_object(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError
    return fields


def _noninteger(_):
    raise ValueError


def _expiry_integer(literal):
    if len(literal.lstrip("-")) > 12:
        raise ValueError
    return int(literal)


def _cookie_document(data):
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_noninteger,
            parse_float=_noninteger,
            parse_int=_expiry_integer,
        )
    except (ValueError, RecursionError):
        # Raise outside the handler so the new exception does not retain a
        # JSONDecodeError with the confidential document as its source.
        pass
    raise ValueError("invalid Cookie JSON v1 document")


def _domain(value, host, host_only):
    if not isinstance(value, str) or not value.isascii() or len(value) > 253:
        return None
    value = value.lower()
    if host_only:
        return value if value == host else None
    if value.startswith("."):
        value = value[1:]
    # Every exact or parent match against these fixed DNS hosts also satisfies
    # the label syntax. Never accept a bare top-level suffix or subdomain.
    if value == host or ("." in value and host.endswith("." + value)):
        return value
    return None


def _cookies(data, source):
    document = _cookie_document(data)
    if not isinstance(document, list) or len(document) > 64:
        raise ValueError("Cookie JSON v1 must be an array of at most 64 cookies")
    host = PROVIDER_HOSTS[source]
    cookies, identities = [], set()
    for index, row in enumerate(document, 1):
        error = ValueError(f"invalid Cookie JSON v1 entry {index}")
        if (
            not isinstance(row, dict) or _COOKIE_FIELDS - row.keys()
            or row.keys() - _COOKIE_FIELDS - _COOKIE_OPTIONAL
        ):
            raise error
        name, value, path = row["name"], row["value"], row["path"]
        secure, same_site = row["secure"], row["sameSite"]
        host_only, expires = row.get("hostOnly", True), row.get("expires")
        if (
            not isinstance(name, str) or not _COOKIE_NAME.fullmatch(name)
            or not isinstance(value, str) or not _COOKIE_VALUE.fullmatch(value)
            or not isinstance(path, str) or not _COOKIE_PATH.fullmatch(path)
            or type(secure) is not bool or type(host_only) is not bool
            or same_site not in ("Strict", "Lax", "None")
            or (expires is not None and (type(expires) is not int or abs(expires) > 253402300799))
        ):
            raise error
        if (same_site == "None" or name.lower().startswith("__secure-")) and not secure:
            raise error
        if name.lower().startswith("__host-") and not (secure and host_only and path == "/"):
            raise error
        domain = _domain(row["domain"], host, host_only)
        if domain is None:
            raise ValueError(f"Cookie JSON v1 entry {index} does not match its provider host")
        identity = (name, domain, path)
        if identity in identities:
            raise ValueError(f"Cookie JSON v1 entry {index} duplicates a cookie identity")
        identities.add(identity)
        cookies.append(Cookie(name, value, domain, path, secure, same_site, host_only, expires))
    return tuple(cookies)


def _dotenv_value(raw):
    if raw.startswith("'"):
        match = _SINGLE_QUOTE.match(raw)
        if match is None:
            return None
        value, end = match[1], match.end()
    elif raw.startswith('"'):
        try:
            value, end = _DECODER.raw_decode(raw)
        except ValueError:
            return None
    else:
        comment = _DOTENV_COMMENT.search(raw)
        return raw[:comment.start()].rstrip(" \t") if comment else raw.rstrip(" \t")
    trailing = raw[end:].lstrip(" \t")
    return value if not trailing or trailing.startswith("#") else None


def _dotenv(data, names):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None:
        raise ValueError("dotenv must be UTF-8 text")
    names = set(names)
    values, seen = {}, set()
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        line = line.lstrip(" \t")
        if any(ord(c) < 32 and c != "\t" for c in line):
            raise ValueError(f"invalid dotenv assignment on line {number}")
        if not line or line.startswith("#"):
            continue
        match = _DOTENV_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid dotenv assignment on line {number}")
        name, raw = match.groups()
        value = _dotenv_value(raw)
        if value is None or _INVALID_TEXT.search(value) or name in seen:
            raise ValueError(f"invalid or duplicate dotenv assignment on line {number}")
        seen.add(name)
        if name in names:
            values[name] = value
    return values


def resolve(config, source, *, environ=None, explicit=None, approved_files=None):
    """Resolve a selected source's declaration, or return None if undeclared.

    Only host-supplied mappings are consulted. `environ` and `explicit` map
    reference names to values. `approved_files` maps `(source, kind, exact
    declared path)` to already authorized bytes; `kind` is cookies or dotenv.
    Nothing is read from the filesystem or process environment by this module.
    """
    sources = config.get("sources") if isinstance(config, dict) else None
    if (
        not isinstance(source, str) or source not in PROVIDER_HOSTS
        or not isinstance(sources, list) or source not in sources
    ):
        raise ValueError("credentials require a known selected source")
    if "credentials" not in config:
        return None
    declarations = config["credentials"]
    validate_declarations(declarations, sources)
    if source not in declarations:
        return None
    declaration = declarations[source]
    if "cookies" in declaration:
        data = _approved_bytes(approved_files, source, "cookies", declaration["cookies"])
        return ResolvedCredentials("cookies", cookies=_cookies(data, source))

    mode = "explicit" if "explicit" in declaration else "environment"
    host_values = explicit if mode == "explicit" else environ
    if host_values is None:
        host_values = {}
    elif not isinstance(host_values, Mapping):
        raise ValueError(f"{source} {mode} host values must be a mapping")

    names = declaration[mode]
    fallback = {}
    if "dotenv" in declaration:
        data = _approved_bytes(approved_files, source, "dotenv", declaration["dotenv"])
        fallback = _dotenv(data, names)
    values = {}
    for name in names:
        value = host_values[name] if name in host_values else fallback.get(name)
        if not isinstance(value, str) or not value or _INVALID_TEXT.search(value):
            raise ValueError(f"{source} has a missing or invalid {mode} credential")
        values[name] = value
    return ResolvedCredentials(mode, values=_SecretValues(values))
