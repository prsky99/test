"""Verified pearls on the public screens (PM 11-18, growth: agent page badge, Explore card badge).

The data is the public pearl list of the search and RAG team: gateway-data/pearls/public-pearls.json under
AGENTCON_PROJECT_ROOT (an absolute path in production, never a working-tree relative one), schema
agentcon-public-pearls-v1, replaced atomically after each pearl test round:
  {"schema": ..., "generated": ..., "methodology": "v1.3",
   "pearls": [{"resource_id": 46160, "role": "fx.rate.v1", "label": "Exchange rates", "level": "final"|"verified"|"provisional",
               "passed": 3, "of": 3, "days": 2, "last_checked": "2026-11-16", "score": 90.0, "terms": "silent"}, ...]}
Only the measured numbers of that file are shown. A pearl badge is shown for level final and verified only (the same
rule as the Explore filter); provisional (one day) stays off the public screens. A member whose terms verdict is prohibits
is shown too (the test result is a fact, PM 11-18) with DIRECT_NOTE: we do not relay it, the caller connects directly. A missing or broken
file shows nothing and never fails a page. No request reads the database: the file is read by modification time.
"""
import json
import os
import re
from pathlib import Path

SCHEMA = 'agentcon-public-pearls-v1'
SHOWN = ('final', 'verified')
METHOD_URL = '/methodology'
DIRECT_NOTE = "Connect directly — we don't relay this agent (provider terms)"  # fixed wording (PM 11-18)
MAX_BYTES = 8 * 1024 * 1024
MAX_ROLES = 3
_cache = {'key': None, 'value': {}}


def path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'gateway-data/pearls/public-pearls.json' if root else None


def _row(value):
    """One public row, or None when it is not a measured pearl row of a shown level."""
    if not isinstance(value, dict) or value.get('level') not in SHOWN:
        return None
    role = value.get('role')
    passed, of, days = value.get('passed'), value.get('of'), value.get('days')
    if not isinstance(role, str) or not role or len(role) > 80:
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (passed, of, days)) or of < 1 or passed > of:
        return None
    checked = value.get('last_checked')
    if not isinstance(checked, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', checked):
        return None
    label = value.get('label')
    return {'role': role, 'label': label[:60] if isinstance(label, str) and label.strip() else None,
            'level': value['level'], 'passed': passed, 'of': of, 'days': days, 'last_checked': checked,
            'direct': value.get('terms') == 'prohibits'}


def load():
    """{agent id (int): [rows of shown levels, final first]}, read by modification time; {} when absent or broken."""
    file = path()
    try:
        stat = file.stat()
    except (OSError, AttributeError):
        return {}
    key = (str(file), stat.st_mtime_ns, stat.st_size)
    if _cache['key'] == key:
        return _cache['value']
    value = {}
    if stat.st_size <= MAX_BYTES:
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = None
        pearls = data.get('pearls') if isinstance(data, dict) and data.get('schema') == SCHEMA else None
        for raw in (pearls if isinstance(pearls, list) else ()):
            agent_id = raw.get('resource_id') if isinstance(raw, dict) else None
            row = _row(raw)
            if row and isinstance(agent_id, int) and not isinstance(agent_id, bool) and agent_id > 0:
                value.setdefault(agent_id, []).append(row)
        for agent_id, found in list(value.items()):
            found.sort(key=lambda r: (r['level'] != 'final', r['role']))
            value[agent_id] = found[:MAX_ROLES]
    _cache.update(key=key, value=value)
    return value


def rows(agent_id):
    return load().get(agent_id) or []


def role_name(row):
    """The label of the role, or its id without the version when the list has none."""
    return row['label'] or re.sub(r'\.v\d+$', '', row['role']).replace('.', ' ').replace('_', ' ')


def badge_text(row):
    """'Final pearl, #1 for <role>' or 'Verified pearl'."""
    return 'Final pearl, #1 for ' + role_name(row) if row['level'] == 'final' else 'Verified pearl'


def public_levels():
    """{agent id (str): 'final' | 'verified'} for the Explore cards: the highest shown level of every pearl agent."""
    return {str(agent_id): ('final' if any(r['level'] == 'final' for r in found) else 'verified')
            for agent_id, found in load().items()}


def direct_ids():
    """Agent ids (str) whose terms prohibit our relay: the Explore card says to connect directly."""
    return sorted(str(agent_id) for agent_id, found in load().items() if any(r['direct'] for r in found))


def measured_line(row):
    """The one measured sentence, nothing else: tasks passed, days confirmed, last check."""
    date = row['last_checked']
    return ('Passed ' + str(row['passed']) + ' of ' + str(row['of']) + ' role tasks · confirmed on '
            + str(row['days']) + ' different days · last checked ' + date)
