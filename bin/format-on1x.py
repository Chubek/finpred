#!/usr/bin/env python3
"""Apply FinPRED's record and argument layout after on1xc fmt."""

import argparse
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
LOCATION = re.compile(rb"(?m)^(\d+):(\d+)  ")
RECORD_HEAD = re.compile(rb"record(?:\s*<\s*[\w.]+\s*>\s*|\s+\w+\s*)\{")
DELIMITERS = {b")": b"(", b"]": b"[", b"}": b"{"}


def token_spans(source, listing):
    """Read scanner locations (byte columns); token text can contain newlines."""
    lines = [0, *(m.end() for m in re.finditer(rb"\n", source))]
    rows = iter(LOCATION.finditer(listing))
    row = next(rows)
    while True:
        line, column = map(int, row.groups())
        start = lines[line - 1] + column - 1
        following = next(rows, None)
        # A location-looking line inside a multiline token is also present
        # verbatim at that offset in the source.
        while following and source.startswith(
            following[0], start + following.start() - row.end()
        ):
            following = next(rows, None)
        end = following.start() - 1 if following else len(listing) - 1
        text = listing[row.end():end]
        if following is None and text == b"<eof>":
            return
        if not text or not source.startswith(text, start):
            raise ValueError("could not match On1x scanner output to the source")
        yield start, start + len(text), text
        if following is None:
            raise ValueError("missing end of On1x scanner output")
        row = following


def groups(tokens):
    """Find matching delimiters and commas at each group's own depth."""
    stack = []
    result = {}
    for i, token in enumerate(tokens):
        if token in DELIMITERS.values():
            stack.append((i, []))
        elif token in DELIMITERS:
            start, commas = stack.pop()
            if tokens[start] != DELIMITERS[token]:
                raise ValueError("unbalanced On1x delimiters")
            result[start] = i, commas
        elif token == b"," and stack:
            stack[-1][1].append(i)
    return result


def record_layout(source, spans, tokens, gaps, pairs):
    indices = {start: i for i, (start, _, _) in enumerate(spans)}
    for i, token in enumerate(tokens):
        if token != b"record":
            continue
        header = RECORD_HEAD.match(source, spans[i][0])
        if not header:
            continue
        opening = indices[header.end() - 1]
        closing, commas = pairs[opening]
        if closing == opening + 1:
            continue
        # Use the brace's canonical indentation, including for nested records.
        brace = spans[opening][0]
        prefix = source[source.rfind(b"\n", 0, brace) + 1:brace]
        indent = prefix[:len(prefix) - len(prefix.lstrip(b" "))]
        newline = b"\n" + indent
        if tokens[i + 1] == b"<":
            for j in (i + 1, i + 2, opening - 1):
                gaps[j] = b""
        if not gaps[opening + 1].strip():
            gaps[opening + 1] = b" "
        fields = [opening + 1]
        for comma in commas:
            # Don't relocate comments or turn a trailing comma into a field.
            if comma + 1 < closing:
                fields.append(comma + 1)
                if not gaps[comma].strip() and not gaps[comma + 1].strip():
                    gaps[comma], gaps[comma + 1] = newline, b" "
        if not gaps[closing].strip():
            gaps[closing] = newline
        if all(j + 1 < closing and tokens[j + 1] == b":" for j in fields):
            longest = max(columns(tokens[j]) for j in fields)
            for j in fields:
                if not gaps[j + 1].strip():
                    gaps[j + 1] = b" " * (longest - columns(tokens[j]))


def columns(text):
    if text.isascii():
        return len(text.expandtabs(8))
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in text.decode().expandtabs(8))


def argument_layout(tokens, gaps, pairs, width, tabstop):
    # Flatten the native comma breaks first. Hard lines (e.g. comments or
    # record braces) stay put, but their nested calls can still be formatted.
    eligible = {}
    # Children appear before their parents because groups are added at close.
    for opening, (closing, commas) in pairs.items():
        if tokens[opening] != b"(":
            continue
        for comma in commas:
            if comma + 1 < closing and not gaps[comma + 1].strip():
                gaps[comma + 1] = b" "
        if commas and not any(
            b"\n" in gaps[j] or b"\n" in tokens[j] or gaps[j].strip()
            for j in range(opening + 1, closing + 1)
        ):
            eligible[opening] = closing, commas

    sizes = [columns(token) for token in tokens]
    col = indent = 0
    for i, token in enumerate(tokens):
        gap = gaps[i]
        if b"\n" in gap:
            last = gap.rsplit(b"\n", 1)[1]
            col = columns(last)
            indent = len(last) - len(last.lstrip(b" "))
        else:
            col += columns(gap)
        if i in eligible:
            closing, commas = eligible[i]
            flat = sum(sizes[j] + columns(gaps[j]) for j in range(i + 1, closing + 1))
            # Include punctuation and return types after the call, stopping
            # at a hard line or another independently wrappable group. Read
            # the current gaps because a parent can introduce a line break.
            suffix = 0
            for j in range(closing + 1, len(tokens)):
                if j in eligible or b"\n" in gaps[j] or b"\n" in tokens[j]:
                    break
                suffix += columns(gaps[j]) + sizes[j]
                if col + sizes[i] + flat + suffix > width:
                    break
            if col + sizes[i] + flat + suffix > width:
                continuation = b"\n" + b" " * (indent + tabstop)
                gaps[i + 1] = continuation
                for comma in commas:
                    if comma + 1 < closing:
                        gaps[comma + 1] = continuation
                gaps[closing] = b"\n" + b" " * indent
        col = columns(token.rsplit(b"\n", 1)[1]) if b"\n" in token else col + sizes[i]


def layout(source, listing, width, tabstop):
    spans = list(token_spans(source, listing))
    tokens = [text for _, _, text in spans]
    gaps = [source[prev:span[0]] for prev, span in zip(
        [0, *(end for _, end, _ in spans)], spans
    )]
    gaps.append(source[spans[-1][1]:] if spans else source)
    # Native preservation directives and extension carriers take priority.
    if any(re.search(rb"(?m)^[ \t]*# on1xfmt:\s*off\b", gap) for gap in gaps) or any(
        a == b"@" and b == b"extension" for a, b in zip(tokens, tokens[1:])
    ):
        return source
    pairs = groups(tokens)
    record_layout(source, spans, tokens, gaps, pairs)
    argument_layout(tokens, gaps, pairs, width, tabstop)
    return b"".join(gap + token for gap, token in zip(gaps, tokens)) + gaps[-1]


def settings(path):
    for parent in path.absolute().parents:
        config = parent / ".on1xfmt"
        if config.is_file():
            break
    else:
        return 80, 2
    values = dict(line.split("=", 1) for raw in config.read_text().splitlines()
                  if (line := raw.partition("#")[0].strip()))
    values = {key.strip(): value.strip() for key, value in values.items()}
    return int(values.get("width", 80)), int(values.get("tabstop", 2))


def format_file(path, compiler, check):
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected a regular, non-symlink source file")
    if path.suffix not in {".on1x", ".on1xi"}:
        raise ValueError("expected an .on1x or .on1xi file")
    canonical = subprocess.check_output([compiler, "fmt", path, "--target", "plain"])
    # Scanning needs only the canonical bytes, not the project environment.
    with tempfile.NamedTemporaryFile(suffix=path.suffix) as scratch:
        staged = Path(scratch.name)
        staged.write_bytes(canonical)
        listing = subprocess.check_output([compiler, "--tokens", staged])
    formatted = layout(canonical, listing, *settings(path))
    if formatted == path.read_bytes():
        return True
    if formatted != canonical:
        # Reparse beside the source so config and relative operator imports
        # resolve exactly as they do for the original file.
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=path.suffix) as scratch:
            staged = Path(scratch.name)
            staged.write_bytes(formatted)
            if subprocess.check_output([compiler, "fmt", staged, "--target", "plain"]) != canonical:
                raise ValueError("project layout changed the native formatter's canonical source")
    if not check:
        # Publish only after the native formatter reparses the result.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            try:
                output.write(formatted)
                output.close()
                os.chmod(output.name, stat.S_IMODE(path.stat().st_mode))
                os.replace(output.name, path)
            finally:
                Path(output.name).unlink(missing_ok=True)
    return not check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report files that need formatting")
    parser.add_argument("--on1xc", default=os.environ.get("ON1XC") or str(
        ROOT / os.environ.get("FINPRED_MULIB_BUILD_DIR", "build/mulib/on1x") / "on1xc"
    ))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    ok = True
    for path in args.files:
        try:
            if not format_file(path, args.on1xc, args.check):
                print(f"{path}: needs formatting")
                ok = False
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            parser.exit(2, f"{path}: {error}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
