#!/usr/bin/env python3
"""Exercise the project layout with the native On1x scanner and formatter."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FORMAT = [sys.executable, str(ROOT / "bin/format-on1x.py")]


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-format-") as work:
        root = Path(work)
        shutil.copyfile(ROOT / ".on1xfmt", root / ".on1xfmt")
        source = root / "format.on1x"
        exactly = '  f("' + "x" * (80 - len('  f("", 0);')) + '", 0);'
        too_long = exactly.replace('",', 'x",')
        literal = "'''first line\n99:1  , not a token row (still literal)\nlast line'''"
        source.write_text(
            "record Foo { x: i64, longer: i64 }\n"
            "fn main(){\n"
            '  let value = record<Foo>{x: f(1,2), longer: 3};\n'
            "  f(0, f(1, 2));\n"
            f"{exactly}\n{too_long}\n"
            '  f(mark(source, "effect", 2), f(mark(source, "header", 1), nil()));\n'
            '  var spans = sx_cons(mark(source, "effect", 2), sx_cons(mark(source, "header", 1), sx_nil()));\n'
            f'  f("café", {literal});\n'
            "}\n"
        )
        assert subprocess.run([*FORMAT, "--check", source], check=False).returncode == 1
        subprocess.run([*FORMAT, source], check=True)
        formatted = source.read_text()
        assert "record Foo\n{ x     : i64\n, longer: i64\n}" in formatted
        assert "record<Foo>\n  { x     : f(1, 2)\n  , longer: 3\n  };" in formatted
        assert "\n  f(0, f(1, 2));\n" in formatted
        assert f"\n{exactly}\n" in formatted
        assert '  f(\n    "' + "x" * (81 - len('  f("", 0);')) + '",\n    0\n  );' in formatted
        assert 'f(mark(source, "effect", 2), f(mark(source, "header", 1), nil()));' in formatted
        assert (
            '  var spans = sx_cons(\n'
            '    mark(source, "effect", 2),\n'
            '    sx_cons(mark(source, "header", 1), sx_nil())\n'
            '  );'
        ) in formatted
        assert literal in formatted
        subprocess.run([*FORMAT, "--check", source], check=True)
        assert source.read_text() == formatted

        interface = root / "api.on1xi"
        interface.write_text("on1xi 1;\nfn pair(x:i64,y:i64)->i64;\n")
        subprocess.run([*FORMAT, interface], check=True)
        assert interface.read_text() == "on1xi 1;\nfn pair(x: i64, y: i64) -> i64;\n"

        protected = root / "protected.on1x"
        region = "# on1xfmt: off\nfn untouched(){   f(1,2); }\n# on1xfmt: on\n"
        protected.write_text(region + "fn formatted(){ f(1,2); }\n")
        subprocess.run([*FORMAT, protected], check=True)
        assert protected.read_text() == region + "fn formatted()\n{\n  f(1, 2);\n}\n"
    print("on1x_format_ok=true")


if __name__ == "__main__":
    main()
