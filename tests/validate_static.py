#!/usr/bin/env python3
"""Packaging/source hygiene checks (NOT an On1x compiler)."""
import csv
import json
import re
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sources = sorted((root/'source').rglob('*.on1x'))
packages = sorted(path for path in (root/'plugins').iterdir() if path.is_dir())
strategies = sorted(path for path in (root/'strategies').iterdir() if path.is_dir())
for package in packages:
    assert not (root/'source'/package.name).exists(), package.name
assert not (root/'source/plugins').exists()
assert len(sources) >= 12, len(sources)
engine_namespaces = {'algorithms', 'automat', 'core', 'ottomat', 'sdk', 'store'}
external_namespaces = {'cli', 'plugins', 'strategies',
                       *(path.name for path in packages + strategies)}
package_catalog = {'sdk.packages', 'sdk.registry', 'sdk.sdk', 'sdk.static_host'}
for module in sources:
    text = module.read_text()
    namespace = module.relative_to(root/'source').parts[0]
    if namespace in engine_namespaces:
        imports = set(re.findall(r'^\s*import\s+([\w.]+)\b', text, re.MULTILINE))
        external = {name for name in imports if name.partition('.')[0] in external_namespaces}
        if namespace != 'sdk':
            external |= imports & package_catalog
        assert not external, (module, external)
    # The smoke check ignores text, character literals and line comments.
    # `#\` starts an On1x character literal, not a comment.
    stripped = re.sub(r'"(?:\\.|[^"\\])*"|#\\(?:[a-zA-Z][\w+]*|[^\n])|#[^\n]*',
                      '', text)
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
schemas = sorted((root/'contracts').glob('*.json'))
historical = {
    'hospitality.offer@1.schema.json', 'hospitality.scenario@1.schema.json',
    'pricing.recommendation@1.schema.json', 'pricing.valuation@1.schema.json',
}
assert historical <= {path.name for path in schemas}
for path in schemas:
    doc = json.loads(path.read_text())
    assert doc['$schema'].endswith('2020-12/schema'), path
    assert doc['properties']['kind']['const'] in path.name, path
for name in ('scenario.csv','valuation.csv','offers.csv','scenario_multiroom.csv','offers_multiroom.csv'):
    with (root/'fixtures'/name).open(newline='') as f:
        rows = list(csv.reader(f))
    assert len(rows)>1 and all(len(row)==len(rows[0]) for row in rows), name
assert (root/'On1xfile').read_text().startswith('on1xfile 1\n')
print(f'static_ok=true on1x_modules={len(sources)} schemas={len(schemas)}')
