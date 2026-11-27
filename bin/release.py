#!/usr/bin/env python3
"""Build and verify the versioned FinPRED analysis-only CLI bundle."""

import argparse
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "finpred-cli-release@1"
TARGET = "linux-x86_64"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
HEX = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
SAFE_PATH = re.compile(r"[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*")
MANIFEST = "release.json"
EXECUTABLES = {
    "bin/finpred",
    "build/dev/finpred",
    "build/dev/finpred-cube",
    "build/dev-forecast/finpred-forecast",
}
DOCUMENTS = {
    "bin/paths.sh", "LICENSE", "licenses/MuLIB.txt", "licenses/LibStone.txt",
    "docs/CLI_RELEASE.md", "fixtures/offers.csv", "fixtures/scenario.csv",
    "fixtures/valuation.csv", "strategies/yieldcraft.ottomat",
}
LIMIT = 64 * 1024 * 1024
# RFC 1952 header emitted by GzipFile: deflate, no optional fields, zero
# mtime, maximum compression hint, unknown OS.
GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def output(*args, cwd=ROOT, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env).decode().strip()


def git(root, *args):
    return output("git", "-C", root, *args)


def gitlink(root, revision, name):
    entries = git(root, "ls-tree", revision, "--", name).split()
    require(len(entries) == 4 and entries[:2] == ["160000", "commit"] and entries[3] == name,
            f"missing gitlink {name} in {revision}")
    return entries[2]


def check_checkout(path, expected, allowed_untracked=()):
    require(git(path, "rev-parse", "--show-toplevel") == str(path)
            and git(path, "rev-parse", "HEAD") == expected,
            f"pin mismatch at {path}: expected {expected}")
    require(not git(path, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all"),
            f"dirty toolchain source checkout: {path}")
    require(not git(path, "ls-files", "--others", "--exclude-standard", "--", ".",
                    *(f":(exclude){entry}/**" for entry in allowed_untracked)),
            f"unexpected untracked toolchain source: {path}")


def check_libstone(path, expected):
    # Cephyr's separately provisioned JSON headers are checked by their own
    # source identity. Valijson's nested test data is not in its include path.
    check_checkout(path, expected, ("third_party/nlohmann-json", "third_party/valijson/thirdparty"))
    json_sources = path / "third_party/nlohmann-json"
    if json_sources.exists() or json_sources.is_symlink():
        subprocess.run(["sh", ROOT / "bin/cephyr-headers.sh", "check", path],
                       stdout=subprocess.DEVNULL, check=True)


def artifact_name(version):
    return f"finpred-cli-{version}-{TARGET}"


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def mode(path):
    return 0o755 if path in EXECUTABLES else 0o644


def inventory(files):
    return {
        path: {"mode": f"{mode(path):04o}", "bytes": len(data), "sha256": sha256(data).hexdigest()}
        for path, data in files.items()
    }


def allowed(path):
    return (SAFE_PATH.fullmatch(path) and not {".", ".."}.intersection(path.split("/"))
            and (path in EXECUTABLES | DOCUMENTS | {MANIFEST}
                 or path.startswith(("contracts/", "plugins/forecast_baselines/contracts/", "fixtures/"))
                 or re.fullmatch(r"strategies/[^/]+\.ottomat", path)))


def tar_bytes(name, files, epoch):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path, data in sorted(files.items()):
            require(allowed(path), f"unsupported release path: {path}")
            info = tarfile.TarInfo(f"{name}/{path}")
            info.size, info.mode, info.mtime = len(data), mode(path), epoch
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def release(args):
    require(platform.system() == "Linux" and platform.machine() == "x86_64",
            f"release builder requires {TARGET}")
    require(VERSION.fullmatch(args.version), "version must be canonical MAJOR.MINOR.PATCH")
    commit = git(ROOT, "rev-parse", "HEAD")
    epoch = int(git(ROOT, "show", "-s", "--format=%ct", commit))
    mulib_id = gitlink(ROOT, commit, "third_party/mulib")
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    check_checkout(mulib, mulib_id)
    libstone_id = gitlink(mulib, mulib_id, "on1x/third_party/libstone")
    libstone = mulib / "on1x/third_party/libstone"
    check_libstone(libstone, libstone_id)
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    ppx = Path(os.environ.get("FINPRED_STDPPX_DIR", compiler.parent / "stdppx")).resolve()
    cc = shutil.which(os.environ.get("CC", "cc"))
    require(cc, "C compiler missing (set CC to a driver executable)")
    cc = str(Path(cc).absolute())  # Preserve the driver basename (e.g. a Clang symlink).
    stage = Path(os.environ.get("FINPRED_STAGE_PARENT", ROOT / "build")).resolve()
    env = dict(os.environ, MULIB_ROOT=str(mulib), ON1XC=str(compiler),
               FINPRED_STDPPX_DIR=str(ppx), CC=cc, LC_ALL="C", TZ="UTC", PYTHONHASHSEED="0",
               FINPRED_STAGE_PARENT=str(stage), ON1X_STDLIB=str(mulib / "on1x/stdlib"),
               SOURCE_DATE_EPOCH=str(epoch), PYTHONDONTWRITEBYTECODE="1")
    for key in ("FINPRED_BUILD_DIR", "ON1X_PATH", "ON1X_PROJECT_COMPILER",
                "ON1X_MULIB_ROOT", "ON1X_PPX_SCHEMA", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    tool_paths = {"on1xc": compiler, "GrammarEmbed": ppx / "on1x-ppx-GrammarEmbed",
                  "category_schema": ppx / "category.schema.json", "cc": Path(cc)}

    def tool_hashes():
        return {name: sha256(path.read_bytes()).hexdigest() for name, path in tool_paths.items()}

    tools = tool_hashes()
    scratch = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finpred-release-", dir=scratch) as work:
        source = Path(work) / "checkout"
        source.mkdir()
        # Git emits the trusted local commit, not the caller's edited worktree.
        snapshot = subprocess.check_output(["git", "-C", ROOT, "archive", commit])
        subprocess.run(["tar", "-xf", "-", "-C", source], input=snapshot, check=True)
        env["TMPDIR"] = str(Path(work) / "scratch")
        subprocess.run(["sh", source / "bin/build.sh"], cwd=source, env=env, check=True)
        paths = {path: source / path for path in EXECUTABLES | DOCUMENTS}
        for folder in ("contracts", "plugins/forecast_baselines/contracts", "fixtures"):
            paths.update((p.relative_to(source).as_posix(), p) for p in (source / folder).rglob("*")
                         if p.is_file())
        paths.update((p.relative_to(source).as_posix(), p) for p in (source / "strategies").glob("*.ottomat"))
        paths.update({"licenses/MuLIB.txt": mulib / "LICENSE", "licenses/LibStone.txt": libstone / "LICENSE"})
        files = {name: path.read_bytes() for name, path in paths.items()}
    require(tools == tool_hashes(), "toolchain executable or schema changed during build")
    check_checkout(mulib, mulib_id)
    check_libstone(libstone, libstone_id)
    manifest = {
        "format": FORMAT, "version": args.version, "target": TARGET, "source_date_epoch": epoch,
        "source": {"finpred": commit, "mulib": mulib_id, "libstone": libstone_id},
        "toolchain": {
            "sha256": tools, "cc_version": output(cc, "--version", env=env),
            "python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION,
        },
        "files": inventory(files),
    }
    files[MANIFEST] = json_bytes(manifest)
    name = artifact_name(args.version)
    raw = tar_bytes(name, files, epoch)
    require(len(raw) <= LIMIT, "uncompressed release exceeds limit")
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0, compresslevel=9) as compressed:
        compressed.write(raw)
    blob = stream.getvalue()
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = args.output / (name + ".tar.gz")
    checksum = bundle.with_name(bundle.name + ".sha256")
    require(not bundle.exists() and not checksum.exists(), "refusing to overwrite a release output")
    digest = sha256(blob).hexdigest()
    with bundle.open("xb") as stream:
        stream.write(blob)
    with checksum.open("x", encoding="ascii") as stream:
        stream.write(f"{digest}  {bundle.name}\n")
    print(f"{digest}  {bundle}")


def verify(args):
    with args.archive.open("rb") as stream:
        blob = stream.read(LIMIT + 1)
    require(len(blob) <= LIMIT, "compressed release exceeds limit")
    digest = sha256(blob).hexdigest()
    if args.sha256 is not None:
        require(HEX.fullmatch(args.sha256) and args.sha256 == digest, "archive SHA-256 mismatch")
    require(blob.startswith(GZIP_HEADER), "noncanonical release gzip header")
    decompress = zlib.decompressobj(wbits=31)
    raw = decompress.decompress(blob, LIMIT + 1)
    require(len(raw) <= LIMIT, "uncompressed release exceeds limit")
    require(decompress.eof and not decompress.unused_data, "invalid release gzip stream")
    files, metadata = {}, []
    name = None
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive:
            root, sep, path = entry.name.partition("/")
            require(sep and (name is None or root == name) and allowed(path)
                    and entry.type == tarfile.REGTYPE and path not in files and not entry.pax_headers,
                    f"invalid archive entry: {entry.name!r}")
            name = root
            require(entry.mode == mode(path) and entry.uid == entry.gid == 0
                    and not (entry.uname or entry.gname or entry.linkname),
                    f"invalid archive metadata: {entry.name!r}")
            files[path] = archive.extractfile(entry).read()  # No filesystem extraction.
            metadata.append((path, entry.mtime))
    require(EXECUTABLES | DOCUMENTS | {MANIFEST} <= files.keys(), "missing required release files")
    encoded = files.pop(MANIFEST)
    manifest = json.loads(encoded)
    require(isinstance(manifest, dict) and encoded == json_bytes(manifest)
            and set(manifest) == {"format", "version", "target", "source_date_epoch", "source",
                                  "toolchain", "files"}, "invalid release manifest")
    version, epoch = manifest["version"], manifest["source_date_epoch"]
    require(manifest["format"] == FORMAT and manifest["target"] == TARGET
            and isinstance(version, str) and VERSION.fullmatch(version) and name == artifact_name(version)
            and type(epoch) is int and epoch >= 0, "invalid release identity")
    source, toolchain = manifest["source"], manifest["toolchain"]
    require(isinstance(source, dict) and set(source) == {"finpred", "mulib", "libstone"}
            and all(isinstance(v, str) and COMMIT.fullmatch(v) for v in source.values()),
            "invalid release source identity")
    require(isinstance(toolchain, dict) and set(toolchain) == {"sha256", "cc_version", "python", "zlib"}
            and all(isinstance(toolchain[k], str) and toolchain[k] for k in ("cc_version", "python", "zlib"))
            and isinstance(toolchain["sha256"], dict)
            and set(toolchain["sha256"]) == {"on1xc", "GrammarEmbed", "category_schema", "cc"}
            and all(isinstance(v, str) and HEX.fullmatch(v) for v in toolchain["sha256"].values()),
            "invalid release toolchain identity")
    require(metadata == [(path, epoch) for path in sorted([*files, MANIFEST])],
            "invalid archive timestamps or order")
    require(json_bytes(manifest["files"]) == json_bytes(inventory(files)), "release file inventory mismatch")
    # Compare raw USTAR bytes, not zlib output (verification can use another zlib).
    files[MANIFEST] = encoded
    require(raw == tar_bytes(name, files, epoch), "noncanonical release tar")
    print(f"release_verified=true format={FORMAT} version={version} sha256={digest}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build an archive from the current committed FinPRED tree")
    build.add_argument("version")
    build.add_argument("--output", type=Path, default=ROOT / "build/releases")
    build.set_defaults(action=release)
    check = commands.add_parser("verify", help="verify an archive without extracting it")
    check.add_argument("archive", type=Path)
    check.add_argument("--sha256", help="expected archive digest from an independently trusted source")
    check.set_defaults(action=verify)
    args = parser.parse_args()
    try:
        args.action(args)
    except (EOFError, OSError, ValueError, RecursionError, tarfile.TarError,
            subprocess.CalledProcessError, zlib.error) as exc:
        parser.exit(2, f"release: {exc}\n")


if __name__ == "__main__":
    main()
