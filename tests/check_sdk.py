#!/usr/bin/env python3
"""Build and install the C11 SDK; link a consumer using only its public ABI."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode:
        raise RuntimeError(f"{args}: exit {proc.returncode}\n{proc.stdout}")
    return proc.stdout


def main():
    manifest = json.loads((ROOT / "plugins/yieldcraft/plugin.json").read_text())
    with tempfile.TemporaryDirectory(prefix="finpred-c-sdk-") as tmp:
        build, install = Path(tmp) / "build", Path(tmp) / "install"
        run(["cmake", "-S", ROOT / "source/sdk", "-B", build, "-DBUILD_SHARED_LIBS=ON",
             f"-DCMAKE_INSTALL_PREFIX={install}", "-DCMAKE_INSTALL_LIBDIR=lib"])
        run(["cmake", "--build", build])
        run(["cmake", "--install", build])
        consumer = Path(tmp) / "consumer"
        run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-pedantic", "-UNDEBUG", f"-I{install}/include", ROOT / "tests/sdk_consumer.c",
             f"-L{install}/lib", f"-Wl,-rpath,{install}/lib", "-lfinpred_sdk", "-o", consumer])
        lines = run([consumer]).splitlines()
    limits = manifest["resource_limits"]
    expected = [str(manifest["sdk"]), manifest["name"], manifest["version"], manifest["kind"],
                *manifest["effects"], *manifest["contracts"],
                " ".join(str(limits[k]) for k in ("csv_rows", "rooms_per_property", "maximum_rooms",
                                                  "adults", "children", "search_budget_max"))]
    if lines != expected or manifest["host_capabilities"] != []:
        raise ValueError(f"C ABI descriptor differs from {manifest['name']} manifest: {lines!r}")
    print("c_sdk_ok=true abi=1 manifest=yieldcraft.percentile")


if __name__ == "__main__":
    main()
