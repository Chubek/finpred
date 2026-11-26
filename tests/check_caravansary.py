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
# Pinned before removal of the header: moving its name to a normal field
# must not invalidate existing observations.
assert rows[0]['config_id'] == '78af9a0abf954beb1ff7dfd9b5864b9ceddbfc3dc373eb262a451a06534eb472'
assert rows[0]['cell_key'] == 'fe49003f4a74bc828c447d079755398d91a745429cb4755d2249fc122116d531'
for source in ('name = "x"; name = "y";', 'name = "x"; trailing'):
    try:
        module.parse(source)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid script accepted')
print('caravansary offline coverage: OK')
