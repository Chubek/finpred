#!/usr/bin/env python3
"""Check an installed, relocated FinPRED SDK from Python and C."""

import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def check_binding(prefix):
    sys.path.insert(0, str(prefix / "lib/finpred/python"))
    from finpred_sdk import Host, Limits, Port, SDK, SDKError, Status, Use, ValueState

    lib = prefix / "lib/libfinpred_sdk.so"
    sdk = SDK(lib)
    producer = Port("out", "test.value", 1, "minor", "EUR",
                    ValueState.AVAILABLE | ValueState.PARTIAL, 32)
    consumer = replace(producer, name="in", max_bytes=64, states=31)
    assert sdk.connect_ports(producer, consumer) == Status.OK
    assert sdk.connect_ports(consumer, producer) == Status.INCOMPATIBLE
    for change in ({"major": 2}, {"kind": "other"}, {"unit": "other"},
                   {"currency": "none"}, {"states": ValueState.AVAILABLE}, {"max_bytes": 31}):
        assert sdk.connect_ports(producer, replace(consumer, **change)) == Status.INCOMPATIBLE
    for change in ({"name": "é" * 32}, {"states": 32}, {"max_bytes": 2000001}):
        assert sdk.connect_ports(producer, replace(consumer, **change)) == Status.INVALID
    for package in ("dragnet", "poindexter", "yieldcraft"):
        manifest = json.loads((ROOT / "plugins" / package / "plugin.json").read_bytes())
        name = manifest["name"]
        kind = manifest["kind"]
        contracts = manifest["contracts"]
        if kind == "Source":
            inputs = (contracts[0], manifest["input_format"])
            output = manifest["output"]
        elif kind == "View":
            inputs, output = tuple(contracts), manifest["output"]
        else:
            inputs, output = tuple(contracts[:-1]), contracts[-1]
        effect, = manifest["effects"]
        use = Use(manifest["sdk"], manifest["version"], kind, output,
                  manifest["mode"], effect, inputs)
        host = Host(Limits(**manifest["resource_limits"]), tuple(manifest.get("dependencies", ())))
        d = sdk.describe(name)
        assert (d.name, d.sdk_version, d.package_version, d.kind, d.output, d.mode,
                d.effect, d.inputs, d.dependencies, d.capabilities, d.limits) == (
                    name, use.sdk_version, use.package_version, kind, output, use.mode,
                    effect, inputs, host.dependencies, tuple(manifest["host_capabilities"]), host.ceilings)
        assert sdk.check(name, use, host) == Status.OK
        assert sdk.check(name, replace(use, mode="execution"), host) == Status.DENIED
        assert sdk.check(name, replace(use, inputs=inputs[::-1]), host) == Status.INCOMPATIBLE
        assert sdk.check(name, replace(use, requested=("network",)),
                         replace(host, grants=("network",))) == Status.DENIED
        assert sdk.check(name, use, replace(host, grants=("duplicate", "duplicate"))) == Status.INVALID
        assert sdk.check(name, use, replace(host, grants=("x" * 128,))) == Status.INVALID
        for key, cap in manifest["resource_limits"].items():
            narrow = replace(host, ceilings=replace(host.ceilings, **{key: cap - 1}))
            assert sdk.check(name, use, narrow) == Status.INCOMPATIBLE
        if host.dependencies:
            assert sdk.check(name, use, replace(host, dependencies=())) == Status.INCOMPATIBLE

    assert sdk.check("not-in-sdk", use, host) == Status.NOT_FOUND
    try:
        sdk.describe("not-in-sdk")
    except SDKError as exc:
        assert exc.status == Status.NOT_FOUND
    else:
        raise AssertionError("unknown package lookup succeeded")

    for call in (
        lambda: SDK("libfinpred_sdk.so"),
        lambda: sdk.describe(name + "\0ignored"),
        lambda: sdk.check(name, replace(use, sdk_version=2**32 + 1), host),
        lambda: sdk.check(name, use, replace(host, ceilings=Limits(csv_rows=-1))),
        lambda: sdk.check(name, use, replace(host, grants=("x",) * 17)),
        lambda: sdk.connect_ports(producer, replace(consumer, kind="test\0other")),
        lambda: sdk.connect_ports(producer, replace(consumer, major=-1)),
    ):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("unsafe ABI representation accepted")
    del sdk
    assert d.name == name and d.inputs == inputs  # Python owns copied metadata.


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-python-sdk-") as tmp:
        work = Path(tmp)
        prefix = work / "original"
        build = work / "build"
        relocated = work / "relocated"

        def run(*args):
            subprocess.run(args, cwd=work, check=True)

        run("cmake", "-S", ROOT / "source/sdk", "-B", build,
            "-DBUILD_SHARED_LIBS=ON", "-DFINPRED_INSTALL_PYTHON_SDK=ON",
            f"-DCMAKE_INSTALL_PREFIX={prefix}", "-DCMAKE_INSTALL_LIBDIR=lib")
        run("cmake", "--build", build)
        run("cmake", "--install", build)
        prefix.rename(relocated)

        consumer = work / "consumer"
        consumer.mkdir()
        (consumer / "main.c").write_bytes((ROOT / "tests/sdk_consumer.c").read_bytes())
        (consumer / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(consumer LANGUAGES C)\n"
            "find_package(FinPREDSDK 1.1 CONFIG REQUIRED)\n"
            "add_executable(consumer main.c)\n"
            "target_compile_options(consumer PRIVATE -UNDEBUG)\n"
            "target_link_libraries(consumer PRIVATE FinPRED::sdk)\n",
            encoding="ascii",
        )
        out = work / "consumer-build"
        run("cmake", "-S", consumer, "-B", out, f"-DCMAKE_PREFIX_PATH={relocated}")
        run("cmake", "--build", out)
        result = subprocess.check_output([out / "consumer"], cwd=work)
        assert b"\nyieldcraft.percentile\n" in result
        check_binding(relocated)
    print("python_sdk_ok=true packages=3 relocated_cmake=passed")


if __name__ == "__main__":
    main()
