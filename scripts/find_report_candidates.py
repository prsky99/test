#!/usr/bin/env python3
"""List registered agents that have current successful execution evidence but no report yet (read-only)."""
from pathlib import Path
import json, sqlite3, sys, collections
sys.path.insert(0, '.')
from agent_market.gateway.store import Store
from agent_market.concierge.report_evidence import current_version_id
from agent_market.report_creation import subject, find_existing

DB = 'gateway-data/collector.sqlite3'
store = Store(DB)
ro = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
ro.row_factory = sqlite3.Row
rows = ro.execute("""SELECT v.resource_id rid, e.version_id vid, e.started, e.finished, e.cases, e.successes, e.operation_ref, e.expires
    FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
    JOIN resources r ON r.id=v.resource_id
    WHERE e.scope='execution' AND e.outcome='succeeded' AND r.eval_grade IN ('A','B')
    ORDER BY e.finished DESC""").fetchall()
out, seen, skipped = [], set(), collections.Counter()
for row in rows:
    rid = row['rid']
    if rid in seen: continue
    seen.add(rid)
    res = store.resource(rid)
    if not res: skipped['no_resource'] += 1; continue
    if current_version_id(res) != row['vid']: skipped['stale_version'] += 1; continue
    try:
        if find_existing(store, subject(store, rid)) is not None: skipped['already_reported'] += 1; continue
    except ValueError: skipped['bad_subject'] += 1; continue
    out.append(dict(rid=rid, kind=res['kind'], name=res['name'], url=res['url'], vid=row['vid'],
                    started=row['started'], finished=row['finished'], cases=row['cases'], succ=row['successes'], op=row['operation_ref']))
print('candidates', len(out), dict(skipped), collections.Counter(o['kind'] for o in out))
json.dump(out, open(str(Path.home() / '.gemini/antigravity/brain/c483b1b9-b552-4e83-b78d-d6f36bf0128d/scratch/candidates.json'), 'w'), indent=1)
for o in out[:10]: print(o)
