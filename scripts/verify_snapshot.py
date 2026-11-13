"""Snapshot for the Check-and-Route tools (PM 11-14 super-gap strategy, supplement 2): `verify_agent` and
`best_for_role` answer from this file, never from the database on the request path (response-time policy).

Per agent: grade, the latest v2 version's score items per role, verified / final pearl, last test time, data time,
tool-definition fingerprint, signed report address (once versions are signed), better alternatives in the same role,
and the necklaces that use the role. Per role: final pearl, verified pearls, ranking, necklaces.

Written to exports/pearls/verify-snapshot.json after the daily funnel (scripts/pearl_daily.py).
    .venv/bin/python -m scripts.verify_snapshot
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import report_v2 as V  # noqa: E402

OUT = V.OUT / 'verify-snapshot.json'
DEFINITIONS = ROOT / 'agent_market/necklaces/definitions'


def necklaces_by_role(folder=DEFINITIONS):
    """role id -> [{slug, status, members}] from the workflow team's necklace definitions."""
    out = defaultdict(list)
    for path in sorted(Path(folder).glob('*.json')):
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for slot in d.get('slots') or []:
            if slot.get('contract'):
                out[slot['contract']].append({'necklace': d.get('slug'), 'status': d.get('status'), 'slot': slot.get('slot'),
                                              'members': [m.get('resource_id') for m in slot.get('chain') or [] if m.get('resource_id')]})
    return out


def catalog_facts(ids):
    """Name, kind, grade and tool-definition fingerprint for IDS (production read only, one connection)."""
    if not ids:
        return {}
    import psycopg
    dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
    with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=20000') as c:
        return {r[0]: {'name': r[1], 'kind': r[2], 'grade': r[3], 'tool_fingerprint': r[4]}
                for r in c.execute('SELECT id, name, kind, eval_grade, usage_tools_hash FROM public.resources WHERE id = ANY(%s)',
                                   (list(ids),))}


def is_verified(v, now):
    acc = ((v.get('data_quality') or {}).get('accuracy') or {}).get('points')
    return bool(acc) and v['quality']['score'] >= V.PASS_MARK and \
        V.success_days(v['resource_id'], v['role'], v['tool'], now) >= V.CONFIRM_DAYS


def build(versions=None, facts=None, necklaces=None, now=None):
    now = time.time() if now is None else now
    versions = V.latest_versions() if versions is None else versions
    ranked = V.rank(versions)
    necklaces = necklaces_by_role() if necklaces is None else necklaces
    facts = catalog_facts({v['resource_id'] for v in versions}) if facts is None else facts
    verified = {(v['resource_id'], v['role']) for v in versions if is_verified(v, now)}
    roles = {}
    for role, entry in ranked.items():
        order = [m for m in entry['members'] if m['rank']]
        roles[role] = {'field': entry['domain'], 'final_pearl': entry['final_pearl'],
                       'verified': [m['resource_id'] for m in order if (m['resource_id'], role) in verified],
                       'ranking': [{'id': m['resource_id'], 'tool': m['tool'], 'score': m['score'],
                                    'verified': (m['resource_id'], role) in verified} for m in order],
                       'necklaces': necklaces.get(role, [])}
    agents = defaultdict(lambda: {'roles': []})
    for v in versions:
        rid, role = v['resource_id'], v['role']
        dq = v.get('data_quality') or {}
        better = [m for m in roles.get(role, {}).get('ranking', []) if m['id'] != rid and m['verified']][:3]
        agent = agents[str(rid)]
        agent.update({'id': rid, **(facts.get(rid) or {})})
        agent['roles'].append({
            'role': role, 'tool': v['tool'], 'outcome': v['outcome'], 'score': v['quality']['score'],
            'score_items': {'data_quality': v['quality'].get('data'), 'evidence': v['quality'].get('evidence'),
                            'report_text': v['quality'].get('writing')},
            'accuracy_source': (dq.get('accuracy') or {}).get('source'),
            'verified_pearl': (rid, role) in verified, 'final_pearl': roles.get(role, {}).get('final_pearl') == rid,
            'tested_at': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(v['tested'])),
            'data_time': (dq.get('freshness') or {}).get('newest'), 'response_sha256': v.get('response_hash'),
            'version': v.get('version'), 'signed_report': v.get('signed_report'),
            'better_alternatives': better, 'necklaces': roles.get(role, {}).get('necklaces', []),
        })
    import data_quality as DQ
    return {'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now)), 'methodology': 'v1',
            'verified_rule': {'min_score': V.PASS_MARK, 'successes_on_different_days': V.CONFIRM_DAYS,
                              'accuracy_required': True, 'weights': DQ.WEIGHTS},
            'roles': roles, 'agents': dict(agents)}


def main():
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(OUT)                      # readers never see a half-written file
    print(f"{OUT.relative_to(ROOT)}: {len(data['agents'])} agents, {len(data['roles'])} roles")


if __name__ == '__main__':
    main()
