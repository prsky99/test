"""IndexNow notices for changed public pages only (PM decision 11-09: daily, differences only).

Each sitemap page gets a fingerprint built from the facts it shows that matter to a reader
(evidence types, grades, membership and order of lists), not from timestamps or latencies, so a
page is re-sent only when what it says changes. The first run records a baseline and sends nothing:
the full sitemap was submitted once by hand on 11-09.

Submission checks the key with one URL first; IndexNow answers 403 until it has fetched the key
file, so a 403 leaves the batch pending for a later attempt.
"""
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request

ORIGIN = 'https://agentconcierge.biz'
ENDPOINT = 'https://api.indexnow.org/indexnow'
USER_AGENT = 'AgentConcierge-indexnow/1.0 (site owner)'
BATCH = 10000
AGENT_FACTS = ('kind', 'name', 'description', 'category', 'health_status', 'trial_ok', 'eval_grade',
               'report_grade', 'auth_required', 'free', 'tool_count')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()[:16]


def _agent(agent):
    return {**{k: agent.get(k) for k in AGENT_FACTS}, 'execution_checked': bool(agent.get('verified_at'))}


def fingerprints(snapshot):
    """path -> fingerprint for every sitemap page of a cleaned snapshot (growth_pages.clean)."""
    from . import growth_catalog as catalog
    from .growth_pages import sitemap_paths
    paths = sitemap_paths(snapshot)
    found = {path: 'static' for path in paths}
    agents = snapshot['catalog']
    for rid, agent in agents.items():
        found['/agent/'+str(rid)] = _hash(_agent(agent))
    for task in snapshot['tasks']:
        found['/agents/task/'+task['slug']] = _hash([_agent(a) | {'id': a['id']} for a in task['agents']])
    found['/agents/tasks'] = _hash(sorted(t['slug'] for t in snapshot['tasks']))
    by_cat, by_kind = catalog.groups(snapshot)
    for category, ranked in by_cat.items():
        found['/agents/best/'+category] = _hash([a['id'] for a in ranked[:catalog.TOP]])
    for (category, kind), ranked in by_kind.items():
        found[f'/agents/best/{category}/{kind}'] = _hash([a['id'] for a in ranked[:catalog.TOP]])
    found['/agents/best'] = _hash(sorted(by_cat))
    for left, right in catalog.pairs(snapshot):
        found[catalog.compare_path(left, right)] = _hash([_agent(agents[left]), _agent(agents[right])])
    found['/reports/state-of-ai-agents/'+catalog.month(snapshot)] = _hash(snapshot.get('stats'))
    return {path: found[path] for path in paths}


def changed(previous, current):
    """Added, changed and removed paths (IndexNow accepts all three)."""
    return sorted({p for p, f in current.items() if previous.get(p) != f} | (set(previous) - set(current)))


def read_state(path):
    try:
        with open(path, encoding='utf-8') as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) and isinstance(value.get('pages'), dict) else None
    except (OSError, ValueError):
        return None


def write_state(path, value):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix='.indexnow-state.')
    with os.fdopen(handle, 'w', encoding='utf-8') as out:
        json.dump(value, out, separators=(',', ':'))
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def post(key, urls, opener=urllib.request.urlopen):
    body = json.dumps({'host': 'agentconcierge.biz', 'key': key, 'keyLocation': f'{ORIGIN}/{key}.txt', 'urlList': urls}).encode()
    request = urllib.request.Request(ENDPOINT, data=body, method='POST', headers={
        'Content-Type': 'application/json; charset=utf-8', 'User-Agent': USER_AGENT})
    try:
        with opener(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def submit(key, urls, opener=urllib.request.urlopen):
    """Check the key with one URL, then send the rest in batches. Returns (done, statuses)."""
    if not urls:
        return True, []
    first = post(key, urls[:1], opener)
    if first not in (200, 202):
        return False, [first]  # 403: key not verified yet; 422/429: try again later
    statuses = [first]
    for start in range(1, len(urls), BATCH):
        statuses.append(post(key, urls[start:start+BATCH], opener))
    return all(s in (200, 202) for s in statuses), statuses
