"""Compute the v1 forecast source subject with stable historical module names."""

from hashlib import sha256
from pathlib import Path
import sys


GUEST_NIGHTS = "plugins/dragnet/guest_nights.on1x"
FEED_SNAPSHOT = "core/feed_snapshot.on1x"
V1_MODULES = ("evaluation.on1x", "holdout.on1x", "model.on1x", "score.on1x")


def v1_source(name: str, raw: bytes) -> tuple[str, bytes]:
    # v1 archives pin the hash of the linked implementation. Normalize only the
    # names of the relocated module and its import, and a changed comment, so
    # the source move does not invalidate issued forecasts. Other edits re-pin.
    if name == GUEST_NIGHTS:
        name = "core/guest_nights.on1x"
    elif name == FEED_SNAPSHOT:
        raw = raw.replace(
            b"# Shared primitives for reading fixed canonical snapshot profiles, not general JSON.\n",
            b"# Readers for the fixed canonical Dragnet JSON profile, not general JSON.\n",
            1,
        )
    elif name.startswith("forecast_baselines/"):
        raw = raw.replace(
            b"import plugins.dragnet.guest_nights as Guest;\n",
            b"import core.guest_nights as Guest;\n",
            1,
        )
    return name, raw


def v1_subject(source: Path, compiler: Path) -> str:
    # This is the closure of the v1 forecast host, not every library file
    # shipped under forecast_baselines. New, unlinked APIs must not re-pin it.
    module_paths = [source / "forecast_baselines" / name for name in V1_MODULES]
    module_paths.extend(source / name for name in (
        "core/date.on1x", FEED_SNAPSHOT, "core/format.on1x", GUEST_NIGHTS, "sdk/callable.on1x",
    ))
    entries = [f"{sha256(compiler.read_bytes()).hexdigest()}  -\n"]
    for module in module_paths:
        name, raw = v1_source(module.relative_to(source).as_posix(), module.read_bytes())
        entries.append(f"{sha256(raw).hexdigest()}  {name}\n")
    return sha256("".join(entries).encode("ascii")).hexdigest()


if __name__ == "__main__":
    print(v1_subject(Path(sys.argv[1]), Path(sys.argv[2])))
