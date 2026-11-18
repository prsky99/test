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
import re
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


def role_words(role, tool, pattern=None):
    """The words a request about ROLE may use: its readable name, the pearl's tool and the role's tool names
    (scripts.role_catalog patterns, e.g. ip_lookup|ip_geolocation|geolocate_ip), lower case and space separated."""
    names = re.findall(r'[a-z][a-z0-9_]+', str(pattern or '').lower())
    return ' '.join(dict.fromkeys(' '.join([label(role), str(tool or '')] + names).replace('_', ' ').lower().split()))


def build(summary, role_groups, terms=None, generated=None, methodology=None, role_tools=None):
    """The public document from the official results. TERMS maps resource id -> allowed/silent/prohibits; ROLE_TOOLS maps
    a role id to its tool-name pattern (scripts.role_catalog), written into each pearl's words."""
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
                'terms': terms.get(rid) or 'unknown',
                'words': role_words(role, member.get('tool'), (role_tools or {}).get(role))})
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
    try:   # report_v2 and the CLI run from the repository root; the services only load() the file
        from scripts.role_catalog import ROLES
        role_tools = {role: (spec or {}).get('tools') for role, spec in ROLES.items()}
    except Exception:
        role_tools = {}
    document = build(summary, role_groups, terms, methodology=methodology, role_tools=role_tools)
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


NOT_A_PEARL = 2


def pearl_rank(resource_id, tool=None, source=None):
    """The ordering tier for recommendations and Explore (PM 11-18 pearl priority): 0 final, 1 verified, 2 otherwise.

    With TOOL (a recommendation's chosen tool) only a pearl entry for that tool counts: the listing is a pearl for the
    role this card exercises, not for another of its tools; an empty TOOL matches nothing. Without TOOL (None, an
    Explore row) any final or verified entry counts; the caller limits that to rows already about the task. A pearl
    whose provider terms prohibit our relay gets no lift (it keeps its place below relayed choices). Missing or
    malformed list: 2 for everything."""
    if type(resource_id) is not int:
        return NOT_A_PEARL
    wanted = str(tool).casefold() if tool is not None else None
    best = NOT_A_PEARL
    for p in load(source).get('pearls', []):
        if (not isinstance(p, dict) or p.get('resource_id') != resource_id or p.get('level') not in ('final', 'verified')
                or p.get('terms') == 'prohibits'):
            continue
        if wanted is not None and (not wanted or str(p.get('tool') or '').casefold() != wanted):
            continue
        best = min(best, RANK[p['level']])
    return best


# Request words that name no role on their own (PM 11-18 pearl priority, stage 2): "whois lookup" is about domains,
# not every role whose tool is a lookup.
GENERIC_WORDS = frozenset('''search lookup look get list find fetch check query info details data records record address name
    names convert code current latest recent who when where what has many right now local'''.split())
_index = {'value': None, 'by_id': {}}


def role_lift(resource_id, terms, term_in, source=None):
    """The selection's ordering lift for one listing (PM 11-18 stage 2): 2 for a final pearl, 1 for a verified pearl,
    whose role the request names (a specific request word in the pearl's role words, matched by TERM_IN, the
    selection's own word test); 0 otherwise, for a pearl whose terms prohibit our relay, and without the list.
    It only orders the candidates; every safety and relevance check still runs on each of them."""
    if type(resource_id) is not int:
        return 0
    value = load(source)
    with _lock:
        if _index['value'] is not value:
            by_id = {}
            for p in value.get('pearls', []):
                if (isinstance(p, dict) and type(p.get('resource_id')) is int and p.get('level') in ('final', 'verified')
                        and p.get('terms') != 'prohibits'):
                    words = p.get('words') or role_words(p.get('role'), p.get('tool'))
                    by_id.setdefault(p['resource_id'], []).append((2 if p['level'] == 'final' else 1, words))
            _index.update(value=value, by_id=by_id)
        entries = _index['by_id'].get(resource_id)
    if not entries:
        return 0
    specific = [t for t in terms or () if isinstance(t, str) and t not in GENERIC_WORDS]
    return max((lift for lift, words in entries if any(term_in(t, words) for t in specific)), default=0)


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
