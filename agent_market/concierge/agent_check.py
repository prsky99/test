"""Check before you call: our recorded evidence for an endpoint or agent-card URL (11-11, PM decision).

GET /api/agent/v1/check?url= and the read-only MCP tool check_agent answer from what we already hold:
the task-page snapshot (an in-memory index of URL hashes) and, when the snapshot has no match, indexed
key lookups through registered SQL. The URL is never fetched and never resolved: it is only a lookup key,
so the guard is syntactic (scheme, length, no private or reserved literal address, no local names).
"""
import hashlib
import ipaddress
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from . import growth_pages as g

MAX_URL = 2048
CARD_SUFFIXES = ('/.well-known/agent-card.json', '/.well-known/agent.json', '/agent-card.json', '/agent.json')
LOCAL_SUFFIXES = ('.local', '.localhost', '.internal', '.lan', '.home', '.corp', '.intranet', '.test', '.invalid')
KEY_PREFIXES = ('a2a', 'mcp', 'x402', 'a2a-card-mcp', 'erc8004-mcp')
BASE = 'https://agentconcierge.biz'


class CheckError(ValueError):
    pass


def normalize(raw):
    """(canonical URL, host) for a public http(s) URL, or CheckError. Never touches the network."""
    if not isinstance(raw, str) or not raw.strip():
        raise CheckError('Provide the endpoint or agent-card URL in url.')
    raw = raw.strip()
    if len(raw) > MAX_URL or re.search(r'[\s<>"\\]', raw):
        raise CheckError('The url must be one http(s) URL of at most 2048 characters.')
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise CheckError('The url is not a valid URL.') from None
    host = (parts.hostname or '').rstrip('.').lower()
    if parts.scheme.lower() not in ('http', 'https') or not host or parts.username or parts.password:
        raise CheckError('Only public http(s) URLs without credentials can be checked.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global or address.is_multicast:
            raise CheckError('Private, loopback and reserved addresses are not checked.')
    elif host == 'localhost' or host.endswith(LOCAL_SUFFIXES) or '.' not in host:
        raise CheckError('Local and internal host names are not checked.')
    netloc = host if address is None or address.version == 4 else '[' + host + ']'
    scheme = parts.scheme.lower()
    if port and not (scheme == 'https' and port == 443 or scheme == 'http' and port == 80):
        netloc += ':' + str(port)
    path = parts.path or ''
    canonical = urlunsplit((scheme, netloc, path, parts.query, ''))
    return canonical, host


def variants(canonical):
    """The URL forms a listing may have been recorded under, most specific first."""
    out = [canonical]
    if canonical.endswith('/'):
        out.append(canonical.rstrip('/'))
    elif '?' not in canonical:
        out.append(canonical + '/')
    base = canonical.split('?', 1)[0].rstrip('/')
    for suffix in CARD_SUFFIXES:
        if base.endswith(suffix):
            root = base[:-len(suffix)]
            out += [root, root + '/']
            break
    else:
        out += [base + CARD_SUFFIXES[0]]
    seen, result = set(), []
    for value in out:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def url_key(url):
    """20-hex hash of a normalized URL; the snapshot carries this instead of the provider's URL."""
    try:
        canonical, _ = normalize(url)
    except CheckError:
        return None
    return hashlib.sha256(canonical.rstrip('/').encode()).hexdigest()[:20]


def add_url_keys(store, snapshot):
    """Adds url_key to every snapshot agent from its stored URL (jobs, once per daily build)."""
    agents = list(snapshot.get('catalog') or [])
    for task in snapshot.get('tasks') or []:
        agents += task.get('agents') or []
    memo = {}
    for agent in agents:
        rid = agent.get('id')
        if rid not in memo:
            resource = store.resource(rid) if isinstance(rid, int) else None
            memo[rid] = url_key(resource.get('url')) if resource and resource.get('url') else None
        if memo[rid]:
            agent['url_key'] = memo[rid]
    return sum(1 for value in memo.values() if value)


class Index:
    """url_key -> agent id from the current snapshot, rebuilt when the snapshot object changes."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot or g.SNAPSHOT
        self.lock = threading.Lock()
        self.source = None
        self.by_key = {}

    def get(self):
        value = self.snapshot.read()
        with self.lock:
            if value is not self.source:
                self.source = value
                catalog = (value or {}).get('catalog') or {}
                self.by_key = {a['url_key']: a['id'] for a in catalog.values() if a.get('url_key')}
            return value, self.by_key


INDEX = Index()


def _find(store, canonical, index):
    snapshot, by_key = index.get()
    for value in variants(canonical):
        key = hashlib.sha256(value.rstrip('/').encode()).hexdigest()[:20]
        if key in by_key:
            return by_key[key], 'snapshot', snapshot
    for value in variants(canonical):
        for prefix in KEY_PREFIXES:
            rows = store.query('SELECT id FROM resources WHERE key=?', (f'{prefix}:{value}',))
            if rows:
                return rows[0][0], 'catalog', snapshot
    return None, None, snapshot


def _rate(history):
    rows = [h for h in history if h.get('outcome')]
    if not rows:
        return None
    ok = [h for h in rows if h['outcome'] in ('healthy', 'reachable')]  # record_health: healthy | reachable | fail
    latencies = sorted(h['latency_ms'] for h in ok if isinstance(h.get('latency_ms'), (int, float)))
    return {'checks': len(rows), 'succeeded': len(ok), 'success_rate': round(len(ok) / len(rows), 3),
            'median_latency_ms': int(latencies[len(latencies) // 2]) if latencies else None,
            'since': min(h['at'] for h in rows if h.get('at')) if any(h.get('at') for h in rows) else None}


def alternatives(snapshot, agent, limit=3):
    catalog = (snapshot or {}).get('catalog') or {}
    if not catalog:
        return []
    now = time.time()
    pool = [a for a in catalog.values() if a['id'] != (agent or {}).get('id')
            and (not agent or (a.get('category') == agent.get('category') and a['kind'] == agent.get('kind')))]
    if agent and len(pool) < limit:
        pool += [a for a in catalog.values() if a['id'] != agent.get('id') and a.get('category') == agent.get('category') and a not in pool]
    ranked = sorted(pool, key=lambda a: g.rank_key(a, now), reverse=True)[:limit]
    return [{'id': a['id'], 'name': a['name'], 'kind': a['kind'], 'eval_grade': a.get('eval_grade'),
             'health_status': a.get('health_status'), 'detail_url': f'{BASE}/agent/{a["id"]}'} for a in ranked]


def check(store, raw, index=None):
    """The public answer for one URL. Raises CheckError for a URL we will not look up."""
    canonical, host = normalize(raw)
    rid, matched, snapshot = _find(store, canonical, index or INDEX)
    resource = store.resource(rid) if rid else None
    if not resource:
        return {'found': False, 'url': canonical, 'match': 'none',
                'message': 'We have no record of this URL. Nothing was called; we only looked it up.',
                'register_url': f'{BASE}/new/en/list-agent.html', 'evidence_sources': [],
                'alternatives': []}
    listed = ((snapshot or {}).get('catalog') or {}).get(resource['id']) or {}
    history = _rate(store.health_history(resource['id'], 20))
    executed = listed.get('verified_at')
    sources = [{'type': 'connection_check', 'description': 'Scheduled reachability check of the listed endpoint',
                'last_at': resource.get('last_check_at'), 'summary': history}]
    sources.append({'type': 'gateway_call', 'description': 'A real tool call through our gateway',
                    'last_at': executed, 'recorded': bool(executed)})
    sources.append({'type': 'real_task_score', 'description': 'Graded real task runs (task-level evidence)',
                    'recorded': False, 'last_at': None})
    active = bool(resource.get('active'))
    agent = {'id': resource['id'], 'kind': resource.get('kind'), 'category': resource.get('category')}
    return {'found': True, 'url': canonical, 'match': 'exact', 'matched_by': matched, 'host': host,
            'agent': {'id': resource['id'], 'name': resource.get('name'), 'kind': resource.get('kind'),
                      'category': resource.get('category'), 'active': active,
                      'detail_url': f'{BASE}/agent/{resource["id"]}'},
            'status': resource.get('health_status') if active else 'inactive',
            'last_checked_at': resource.get('last_check_at'),
            'recent': history,
            'grade': listed.get('eval_grade') or resource.get('eval_grade'),
            'latency_ms': listed.get('probe_latency_ms'),
            'evidence_sources': sources,
            'alternatives': alternatives(snapshot, agent),
            'message': 'Recorded evidence only; nothing was called to answer this.'}
