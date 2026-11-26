#!/usr/bin/env python3
import datetime
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('caravansary', root / 'plugins/caravansary/caravansary.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rows = list(module.plan(root / 'docs/caravansary/examples/riviera.crs', datetime.date(2026, 11, 26)))
assert len(rows) == 8760
assert all(r['status'] == 'unsupported' and r['reason'] == 'mapping_missing' for r in rows)
assert rows[0]['checkin'] == '2026-11-26' and rows[0]['checkout'] == '2026-11-27'
assert max(r['checkin'] for r in rows) == '2027-11-25'
assert max(r['checkout'] for r in rows) == '2027-11-28'
for source in ('caravan "x" version 1 { a = 1; a = 2; }', 'caravan "x" version 1 {} trailing'):
    try:
        module.parse(source)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid script accepted')
print('caravansary offline coverage: OK')
