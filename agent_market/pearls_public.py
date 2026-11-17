"""Public pearl list: which listings passed our role tests, read by the pages, Explore and recommendation cards.

PM 11-18: pearls were invisible on every public surface. scripts/report_v2 writes the official results under
exports/pearls/final (outside git, relative to the working tree); services must not read the working tree by relative
path, so this module turns those results into one public file at an absolute data path, and the services read only
that file through load().

  path    AGENTCON_PROJECT_ROOT (else the repository root) / gateway-data/pearls/public-pearls.json, replaced atomically
  build   summary.json + role_groups.json + member terms -> the public document (pure, no I/O)
  write   build and replace the file (called after each pearl run)
  load    the document, cached by modification time; {"pearls": [], "by_resource": {}} when missing or malformed

Levels (charter 0, the same counts as summary.json): final = the role's rank-1 verified pearl; verified = 85+ with
successes on two different days; provisional = the role's provisional pearl (85+ on one day, ranked ahead). Badges and filters use final and verified only. Every number is from our test reports:
passed/of = recent role-task passes and tests, days = different days with a success, score = the latest score.
Our own fallback agents are not listed. Nothing about a visitor is read or written.
"""
import json
import os
import threading
from pathlib import Path

SCHEMA = 'agentcon-public-pearls-v1'
LEVELS = ('final', 'verified', 'provisional')
RANK = {level: index for index, level in enumerate(LEVELS)}
EMPTY = {'pearls': [], 'by_resource': {}}


def path():
    if os.environ.get('PEARLS_PUBLIC_PATH'):            # tests point here (tests/conftest.py); services do not set it
        return Path(os.environ['PEARLS_PUBLIC_PATH'])
    root = os.environ.get('AGENTCON_PROJECT_ROOT') or Path(__file__).resolve().parents[1]
    return Path(root) / 'gateway-data' / 'pearls' / 'public-pearls.json'


def label(role):
    """A readable name from the role id (the same rule as necklaces.orders.ROLE_NAMES): fx.rate.v1 -> Fx rate."""
    text = str(role).rsplit('.v', 1)[0].replace('.', ' ').replace('_', ' ').strip()
    return text[:1].upper() + text[1:]


def _level(member, final_id, pass_mark, confirm_days, provisional_id=None):
    rid = member.get('resource_id', member.get('id'))
    score = member.get('score', member.get('best_recent_score'))   # the latest version, as summary counts it
    days = member.get('success_days') or 0
    if type(rid) is not int or not isinstance(score, (int, float)) or score < pass_mark or member.get('outcome') not in (None, 'succeeded'):
        return None
    if days >= confirm_days:
        return 'final' if rid == final_id else 'verified'
    # Provisional is the official one per role (summary 'provisional_pearls'): the 1-day candidate ranked ahead of
    # the verified pearl, not every 85+ member with one day.
    return 'provisional' if days >= 1 and rid == provisional_id else None


def build(summary, role_groups, terms=None, generated=None, methodology=None):
    """The public document from the official results. TERMS maps resource id -> allowed/silent/prohibits."""
    rules = (summary or {}).get('rules') or {}
    pass_mark = rules.get('pass_mark', 85)
    confirm_days = rules.get('confirm_days', 2)
    terms = terms or {}
    pearls = []
    for role, entry in sorted(((role_groups or {}).get('roles') or {}).items()):
        if not isinstance(entry, dict):
            continue
        final_id = entry.get('final_pearl')
        seen = set()
        for member in entry.get('members') or []:
            if not isinstance(member, dict):
                continue
            level = _level(member, final_id, pass_mark, confirm_days, entry.get('provisional_pearl'))
            rid = member.get('resource_id', member.get('id'))
            if level is None or rid in seen:
                continue
            seen.add(rid)
            tasks = member.get('recent_tasks') or 0
            rate = member.get('recent_pass_rate') or 0
            pearls.append({
                'resource_id': rid, 'role': role, 'label': label(role), 'field': entry.get('domain'),
                'level': level, 'final': level == 'final', 'tool': member.get('tool'),
                'score': round(float(member.get('score', member.get('best_recent_score'))), 1),
                'passed': int(round(rate * tasks)), 'of': int(tasks), 'days': int(member.get('success_days') or 0),
                'last_checked': str(member.get('tested') or '')[:10] or None,
                'terms': terms.get(rid) or 'unknown'})
    by_resource = {}
    for pearl in pearls:
        key = str(pearl['resource_id'])
        current = by_resource.setdefault(key, {'level': pearl['level'], 'roles': []})
        current['roles'].append(pearl['role'])
        if RANK[pearl['level']] < RANK[current['level']]:
            current['level'] = pearl['level']
    return {'schema': SCHEMA, 'generated': generated or (summary or {}).get('generated'), 'methodology': methodology,
            'evaluator_version': rules.get('evaluator_version'),
            'rules': {'pass_mark': pass_mark, 'confirm_days': confirm_days},
            'pearls': pearls, 'by_resource': by_resource}


def write(summary, role_groups, terms=None, target=None, methodology=None):
    """Build and replace the public file atomically; returns the number of pearls written."""
    document = build(summary, role_groups, terms, methodology=methodology)
    target = Path(target or path())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.tmp')
    tmp.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    os.replace(tmp, target)
    return len(document['pearls'])


_lock = threading.Lock()
_cache = {'path': None, 'mtime': None, 'value': EMPTY}


def load(source=None):
    """The public document, re-read only when the file changes. Missing or malformed: no pearls."""
    target = Path(source or path())
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return dict(EMPTY)
    with _lock:
        if _cache['path'] == target and _cache['mtime'] == mtime:
            return _cache['value']
        try:
            value = json.loads(target.read_text(encoding='utf-8'))
            if (not isinstance(value, dict) or value.get('schema') != SCHEMA or not isinstance(value.get('pearls'), list)
                    or not isinstance(value.get('by_resource'), dict)):
                raise ValueError('not a public pearl document')
        except (OSError, ValueError):
            value = dict(EMPTY)
        _cache.update(path=target, mtime=mtime, value=value)
        return value


def pearl_of(resource_id, source=None):
    """{level, roles[, relayed]} for one listing from its final and verified entries (badges and cards), or None.
    PM 11-18 07:2x: a pearl whose provider terms prohibit our relay is shown, not hidden ("we do not relay" is not "we
    hide"); it carries relayed: False and the caller connects directly."""
    found = [p for p in load(source).get('pearls', []) if isinstance(p, dict) and p.get('resource_id') == resource_id
             and p.get('level') in ('final', 'verified')]
    if not found:
        return None
    level = 'final' if any(p['level'] == 'final' for p in found) else 'verified'
    out = {'level': level, 'roles': [p['role'] for p in found]}
    if any(p.get('terms') == 'prohibits' for p in found):
        out['relayed'] = False
    return out


def main(argv=None):
    """python -m agent_market.pearls_public write [EXPORTS]: rebuild the public file from the official results."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != 'write':
        print('usage: python -m agent_market.pearls_public write [exports/pearls]', file=sys.stderr)
        return 2
    root = Path(os.environ.get('AGENTCON_PROJECT_ROOT') or Path(__file__).resolve().parents[1])
    exports = Path(argv[1]) if len(argv) > 1 else root / 'exports' / 'pearls'
    summary = json.loads((exports / 'final' / 'summary.json').read_text(encoding='utf-8'))
    groups = json.loads((exports / 'final' / 'role_groups.json').read_text(encoding='utf-8'))
    try:
        members = json.loads((Path(__file__).resolve().parent / 'necklaces' / 'member_terms.json').read_text()).get('members') or {}
        terms = {int(k): (v or {}).get('status') for k, v in members.items() if str(k).isdigit()}
    except (OSError, ValueError, AttributeError):
        terms = {}
    count = write(summary, groups, terms)
    print(f'{count} pearls -> {path()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
