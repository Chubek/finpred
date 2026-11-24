#!/usr/bin/env python3
"""Select the trusted build-host GrammarEmbed processor for Ottomat."""
import os
from pathlib import Path
import subprocess
import sys


def processor_directory(compiler):
    directory = Path(os.environ.get(
        "FINPRED_STDPPX_DIR", Path(compiler).resolve().parent / "stdppx")).resolve()
    processor = directory / "on1x-ppx-GrammarEmbed"
    if (not processor.is_file() or not os.access(processor, os.X_OK)
            or not (directory / "category.schema.json").is_file()):
        raise SystemExit(
            f"Missing GrammarEmbed at {processor}; build the matching "
            "on1x_ppx_GrammarEmbed target ('make mulib' for the default "
            "toolchain) or set FINPRED_STDPPX_DIR"
        )
    return directory


def relative_spans(node, stage_prefix, atom):
    """Use project-relative locations without altering On1x string literals."""
    if not isinstance(node, list):
        return
    if (len(node) == 5 and isinstance(node[0], atom) and node[0] == "Loc"
            and type(node[1]) is str and node[1].startswith(stage_prefix)):
        node[1] = node[1][len(stage_prefix):]
        return
    for child in node:
        relative_spans(child, stage_prefix, atom)


def rewrite(processor, stdppx, stage):
    # Native GrammarEmbed's name collision scan is quadratic over the whole
    # merged unit. Only pass the trusted empty grammar markers to it; retain
    # every other declaration verbatim in the AST and check merge collisions.
    sys.path.insert(0, str(stdppx))
    from _support.sexpr import Atom, MAX_BYTES, dumps, loads

    tree = loads(sys.stdin.buffer.read(MAX_BYTES + 1))
    if len(tree) != 3 or tree[:2] != ["Unit", "1"]:
        raise ValueError("expected an On1x PPX v1 unit")
    # The loader canonicalizes even relative inputs. Its stage path repeats
    # in thousands of locations; the expanded unit must still fit in 4 MiB.
    relative_spans(tree, os.fsencode(stage).decode("latin1") + "/", Atom)
    marked, preserved = [], []
    for decl in tree[2]:
        if decl[0] == "Function" and any(a[1] == "GrammarEmbed" for a in decl[5]):
            marked.append(decl)
        else:
            preserved.append(decl)
    if not marked:
        raise ValueError("Ottomat grammar markers are missing")
    environment = {**os.environ, "ON1X_PPX_SCHEMA": str(processor.parent / "category.schema.json")}
    # The compiler's diagnostics pipe belongs to this PPX process. Its child
    # reports normally on stderr instead of inheriting a stale descriptor.
    environment.pop("ON1X_PPX_DIAGNOSTICS_FD", None)
    expansion = subprocess.run(
        [processor], input=dumps([*tree[:2], marked]), stdout=subprocess.PIPE,
        env=environment, check=True, timeout=25,
    )
    result = loads(expansion.stdout)
    if len(result) != 3 or result[:2] != tree[:2] or not result[2]:
        raise ValueError("GrammarEmbed did not return declarations")
    names = {d[1] for d in preserved if d[0] in ("Function", "Extern")}
    for declaration in result[2]:
        if declaration[0] != "Function" or declaration[1] in names:
            raise ValueError("unexpected or colliding GrammarEmbed declaration")
        names.add(declaration[1])
    sys.stdout.buffer.write(dumps([*tree[:2], preserved + result[2]]))


def flags(compiler, sdk, work):
    directory = processor_directory(compiler)
    adapter = Path(work) / "grammar-ppx"
    adapter.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "from on1x_grammar import rewrite\n"
        f"rewrite(Path({str(directory / 'on1x-ppx-GrammarEmbed')!r}),"
        f" Path({str(sdk.resolve() / 'on1x/stdppx')!r}), Path(__file__).resolve().parent)\n",
        encoding="utf-8",
    )
    adapter.chmod(0o700)
    return ["--ppx", "GrammarEmbed", str(adapter.resolve()), "--ppx-timeout-ms", "30000"]


def main():
    # on1x-project.py does not expose ordinary PPX flags. Keep its regular
    # scanner/dependency checks untouched and select exactly this one processor
    # for the C emission step. Paths are fixed before project staging.
    destination, compiler, sdk = map(Path, sys.argv[1:])
    compiler = str(compiler.resolve())
    args = flags(compiler, sdk, destination.parent)
    destination.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        f"compiler = {compiler!r}\n"
        f"extra = {args!r} if '--emit-c' in sys.argv[1:] else []\n"
        "os.execv(compiler, [compiler, *sys.argv[1:], *extra])\n",
        encoding="utf-8",
    )
    destination.chmod(0o700)


if __name__ == "__main__":
    main()
