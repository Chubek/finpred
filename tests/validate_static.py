#!/usr/bin/env python3
"""Packaging/source hygiene checks (NOT an On1x compiler)."""
import csv
import json
import re
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sources = sorted((root/'source').rglob('*.on1x'))
assert len(sources) >= 12, len(sources)
for module in sources:
    text = module.read_text()
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    stripped = re.sub(r'#.*', '', stripped)
    pairs = {')':'(',']':'[','}':'{'}
    stack = []
    for c in stripped:
        if c in '([{': stack.append(c)
        elif c in ')]}':
            assert stack and stack.pop() == pairs[c], module
    assert not stack, module
    manifest = module.parent / 'On1xfile.m'
    assert manifest.exists() and f'"{module.name}"' in manifest.read_text(), module
    assert not re.search(r'"[^"\n]*"\s*\+\s*[A-Za-z_]', stripped), module
for path in (root/'contracts').glob('*.json'):
    doc = json.loads(path.read_text())
    assert doc['$schema'].endswith('2020-12/schema'), path
    assert doc['properties']['kind']['const'] in path.name, path
assert len(list((root/'contracts').glob('*.json'))) == 4
for name in ('scenario.csv','valuation.csv','offers.csv','scenario_multiroom.csv','offers_multiroom.csv'):
    with (root/'fixtures'/name).open(newline='') as f:
        rows = list(csv.reader(f))
    assert len(rows)>1 and all(len(row)==len(rows[0]) for row in rows), name
assert (root/'On1xfile').read_text().startswith('on1xfile 1\n')
print(f'static_ok=true on1x_modules={len(sources)} schemas=4')
