"""Metadata-only Python binding for the FinPRED C SDK ABI v2."""

import ctypes as ct
from dataclasses import dataclass, fields
from enum import IntEnum, IntFlag
from pathlib import Path

__all__ = ["Descriptor", "Host", "Limits", "Port", "SDK", "SDKError", "Status", "Use", "ValueState"]


class Status(IntEnum):
    OK = 0
    INVALID = 1
    INCOMPATIBLE = 2
    NOT_FOUND = 3
    DENIED = 4


class ValueState(IntFlag):
    AVAILABLE = 1
    PARTIAL = 2
    UNKNOWN = 4
    STALE = 8
    REDACTED = 16


@dataclass(frozen=True)
class Port:
    name: str
    kind: str
    major: int
    unit: str
    currency: str
    states: int | ValueState
    max_bytes: int


class SDKError(RuntimeError):
    def __init__(self, status: Status, name: str):
        self.status = status
        super().__init__(f"{name}: {status.name}")


@dataclass(frozen=True)
class Limits:
    csv_rows: int = 0
    bytes_per_input: int = 0
    rooms_per_property: int = 0
    maximum_rooms: int = 0
    adults: int = 0
    children: int = 0
    search_budget_max: int = 0
    runs_per_call: int = 0
    data_rows: int = 0
    columns: int = 0
    output_bytes_max: int = 0


@dataclass(frozen=True)
class Use:
    sdk_version: int
    package_version: str
    kind: str
    output: str
    mode: str
    effect: str
    inputs: tuple[str, ...]
    requested: tuple[str, ...] = ()


@dataclass(frozen=True)
class Host:
    ceilings: Limits
    dependencies: tuple[str, ...] = ()
    grants: tuple[str, ...] = ()


@dataclass(frozen=True)
class Descriptor:
    name: str
    sdk_version: int
    package_version: str
    kind: str
    output: str
    mode: str
    effect: str
    inputs: tuple[str, ...]
    dependencies: tuple[str, ...]
    capabilities: tuple[str, ...]
    limits: Limits


class _Names(ct.Structure):
    _fields_ = [("count", ct.c_uint32), ("items", ct.POINTER(ct.c_char_p))]


_LIMIT_KEYS = tuple(f.name for f in fields(Limits))
_USE_TEXT = ("package_version", "kind", "output", "mode", "effect")


class _Limits(ct.Structure):
    _fields_ = [(key, ct.c_uint32) for key in _LIMIT_KEYS]


class _Descriptor(ct.Structure):
    _fields_ = [
        ("sdk_version", ct.c_uint32), ("name", ct.c_char_p),
        *((key, ct.c_char_p) for key in _USE_TEXT),
        ("inputs", _Names), ("dependencies", _Names), ("capabilities", _Names),
        ("limits", _Limits),
    ]


class _Use(ct.Structure):
    _fields_ = [
        ("sdk_version", ct.c_uint32), *((key, ct.c_char_p) for key in _USE_TEXT),
        ("inputs", _Names), ("requested", _Names),
    ]


class _Host(ct.Structure):
    _fields_ = [("dependencies", _Names), ("grants", _Names), ("ceilings", _Limits)]


class _Port(ct.Structure):
    _fields_ = [(key, ct.c_char_p) for key in ("name", "kind", "unit", "currency")] + [
        (key, ct.c_uint32) for key in ("major", "states", "max_bytes")
    ]


def _text(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError("SDK text requires str")
    if "\0" in value:
        raise ValueError("SDK text must not contain a NUL")
    return value.encode("utf-8")


def _u32(value: int) -> int:
    if type(value) is not int:
        raise TypeError("SDK uint32 requires int")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("SDK uint32 outside range")
    return value


def _names(value: tuple[str, ...]) -> _Names:
    if not isinstance(value, tuple):
        raise TypeError("SDK name lists require tuple")
    if not value:
        return _Names(0, None)
    if len(value) > 16:
        raise ValueError("SDK name lists accept at most 16 names")
    items = (ct.c_char_p * len(value))(*(_text(name) for name in value))
    # ctypes retains the array and encoded strings through the synchronous call.
    return _Names(len(value), items)


def _read_names(value: _Names) -> tuple[str, ...]:
    if value.count > 16 or (value.count and not value.items):
        raise RuntimeError("malformed SDK name list")
    return tuple(value.items[i].decode("utf-8") for i in range(value.count))


def _port(p: Port) -> _Port:
    states = p.states
    if isinstance(states, ValueState):
        states = int(states)
    return _Port(_text(p.name), _text(p.kind), _text(p.unit), _text(p.currency),
                 _u32(p.major), _u32(states), _u32(p.max_bytes))


class SDK:
    """Open an explicitly selected, trusted ABI v2 shared library.

    This checks static metadata only. It cannot invoke a plugin or grant
    capabilities. A shared library itself executes native code on load.
    """

    def __init__(self, library: str | Path):
        path = Path(library)
        if not path.is_absolute():
            raise ValueError("select a trusted SDK shared library by absolute path")
        self._library = ct.CDLL(str(path))
        self._lookup = self._library.finpred_sdk_lookup_v2
        self._lookup.argtypes = (ct.c_uint32, ct.c_char_p, ct.POINTER(ct.c_void_p))
        self._lookup.restype = ct.c_int32
        self._describe = self._library.finpred_sdk_describe_v2
        self._describe.argtypes = (ct.c_void_p,)
        self._describe.restype = ct.POINTER(_Descriptor)
        self._check = self._library.finpred_sdk_check_v2
        self._check.argtypes = (ct.c_void_p, ct.POINTER(_Use), ct.POINTER(_Host))
        self._check.restype = ct.c_int32
        self._connect_ports = getattr(self._library, "finpred_sdk_connect_ports_v2", None)
        if self._connect_ports is not None:
            self._connect_ports.argtypes = (ct.POINTER(_Port), ct.POINTER(_Port))
            self._connect_ports.restype = ct.c_int32

    def _handle(self, name: str) -> tuple[Status, ct.c_void_p]:
        handle = ct.c_void_p()
        status = self._lookup(2, _text(name), ct.byref(handle))
        return Status(status), handle

    def describe(self, name: str) -> Descriptor:
        """Copy read-only metadata into Python values; raises SDKError on lookup failure."""
        status, handle = self._handle(name)
        if status != Status.OK:
            raise SDKError(status, name)
        descriptor = self._describe(handle)
        if not descriptor:
            raise SDKError(Status.INVALID, name)
        d = descriptor.contents
        return Descriptor(
            name=d.name.decode("utf-8"), sdk_version=d.sdk_version,
            **{key: getattr(d, key).decode("utf-8") for key in _USE_TEXT},
            inputs=_read_names(d.inputs), dependencies=_read_names(d.dependencies),
            capabilities=_read_names(d.capabilities),
            limits=Limits(**{key: getattr(d.limits, key) for key in _LIMIT_KEYS}),
        )

    def check(self, name: str, use: Use, host: Host) -> Status:
        """Check the requested use with independent host inventory and budgets."""
        status, handle = self._handle(name)
        if status != Status.OK:
            return status
        request = _Use(
            _u32(use.sdk_version), *(_text(getattr(use, key)) for key in _USE_TEXT),
            _names(use.inputs), _names(use.requested),
        )
        limits = _Limits(*(_u32(getattr(host.ceilings, key)) for key in _LIMIT_KEYS))
        inventory = _Host(_names(host.dependencies), _names(host.grants), limits)
        return Status(self._check(handle, ct.byref(request), ct.byref(inventory)))

    def connect_ports(self, output: Port, input: Port) -> Status:
        """Check a typed edge's metadata, without resolving or invoking handlers."""
        if self._connect_ports is None:
            return Status.INCOMPATIBLE
        return Status(self._connect_ports(ct.byref(_port(output)), ct.byref(_port(input))))
