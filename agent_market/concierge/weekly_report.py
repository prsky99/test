"""Weekly evidence report (11-10 user request): /reports/weekly and /reports/weekly/<YYYY-Www>.

Every Monday the jobs refresher turns the day's task snapshot into one issue file under
public-pages/weekly/<id>.json (build + write); the frontend only reads those files. An issue states facts
from recorded checks: agents with a successful execution check in the seven days before the snapshot
(per protocol, ranked by the published basis growth_pages.rank_key), counts, and the change against the
previous issue (agents that newly meet the evidence rule, agents that no longer do, per category).

The issue id is the ISO week of the day before the snapshot, so a Monday-morning snapshot names the week
that just ended. Issues are never rewritten once published, except by an explicit rebuild.
"""
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import growth_pages as g

esc = g.esc
FOLDER = 'weekly'
ISSUE = re.compile(r'20[0-9]{2}-W(0[1-9]|[1-4][0-9]|5[0-3])')
TOP = 10
WINDOW = 7*86400
AGENT_FIELDS = ('id', 'kind', 'name', 'category', 'verified_at', 'last_check_at', 'health_status', 'eval_grade',
                'report_grade', 'probe_latency_ms', 'auth_required', 'free', 'trial_ok')


def issue_id(captured):
    day = (captured - timedelta(days=1)).isocalendar()
    return f'{day[0]}-W{day[1]:02d}'


def build(snapshot, previous=None):
    """An issue dict from a cleaned snapshot (growth_pages.clean) and the previous issue, if any."""
    captured = datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc)
    end = captured.timestamp()
    agents = list(snapshot['catalog'].values())
    executed = [a for a in agents if a.get('verified_at') and end - WINDOW <= a['verified_at'] <= end + 3600]
    top, basis = {}, {}
    for kind in ('mcp', 'a2a', 'x402'):
        pool = [a for a in executed if a['kind'] == kind]
        basis[kind] = 'execution'
        if not pool:  # x402 calls are paid, so they are not executed; fall back to trial calls checked this week
            pool = [a for a in agents if a['kind'] == kind and a.get('trial_ok') and a.get('last_check_at')
                    and end - WINDOW <= a['last_check_at'] <= end + 3600]
            basis[kind] = 'trial'
        ranked = sorted(pool, key=lambda a: g.rank_key(a, end), reverse=True)
        top[kind] = [{k: a.get(k) for k in AGENT_FIELDS} for a in ranked[:TOP]]
    categories = {}
    for a in agents:
        if a.get('category'):
            categories[a['category']] = categories.get(a['category'], 0) + 1
    ids = sorted(a['id'] for a in agents)
    issue = {'version': 1, 'week': issue_id(captured), 'captured_at': captured.isoformat(timespec='seconds'),
             'window_start': datetime.fromtimestamp(end - WINDOW, timezone.utc).isoformat(timespec='seconds'),
             'counts': {'evidence': len(agents), 'executed': len(executed), 'trial_ok': sum(1 for a in agents if a.get('trial_ok')),
                        'evidence_by_kind': {k: sum(1 for a in agents if a['kind'] == k) for k in ('mcp', 'a2a', 'x402')},
                        'executed_by_kind': {k: sum(1 for a in executed if a['kind'] == k) for k in ('mcp', 'a2a', 'x402')}},
             'categories': categories, 'top': top, 'basis': basis, 'ids': ids, 'previous': None, 'changes': None}
    if previous and previous.get('week') != issue['week']:
        before, now = set(previous.get('ids') or []), set(ids)
        cats = set(categories) | set(previous.get('categories') or {})
        issue['previous'] = previous['week']
        issue['changes'] = {'added': len(now - before), 'removed': len(before - now),
                            'by_category': {c: categories.get(c, 0) - (previous.get('categories') or {}).get(c, 0) for c in sorted(cats)}}
    return issue


def folder(path_fn=None):
    base = g.data_dir() if path_fn is None else path_fn()
    return Path(base) / FOLDER if base else None


def issues(path_fn=None):
    """Published issue ids, newest first."""
    target = folder(path_fn)
    try:
        names = [p.stem for p in target.glob('*.json')] if target else []
    except OSError:
        return []
    return sorted((n for n in names if ISSUE.fullmatch(n)), reverse=True)


_cache = {}
_lock = threading.Lock()


def read(week, path_fn=None):
    if not ISSUE.fullmatch(str(week or '')):
        return None
    target = folder(path_fn)
    if target is None:
        return None
    path = target / (week + '.json')
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    with _lock:
        hit = _cache.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('week') != week:
        return None
    with _lock:
        _cache[str(path)] = (stamp, value)
    return value


def write(target_folder, issue):
    target_folder = Path(target_folder)
    target_folder.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target_folder, prefix='.weekly.')
    with os.fdopen(handle, 'w', encoding='utf-8') as out:
        json.dump(issue, out, ensure_ascii=False, separators=(',', ':'))
    os.chmod(temporary, 0o644)
    os.replace(temporary, target_folder / (issue['week'] + '.json'))


def publish(target_folder, snapshot, rebuild=False):
    """Write this snapshot's issue unless it exists. Returns the issue id written, or None."""
    target_folder = Path(target_folder)
    week = issue_id(datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc))
    if (target_folder / (week + '.json')).exists() and not rebuild:
        return None
    previous = None
    older = sorted((p.stem for p in target_folder.glob('*.json') if ISSUE.fullmatch(p.stem) and p.stem < week), reverse=True) \
        if target_folder.is_dir() else []
    if older:
        try:
            previous = json.loads((target_folder / (older[0] + '.json')).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = None
    write(target_folder, build(snapshot, previous))
    return week


# ---------------------------------------------------------------- pages
def _date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%d %b %Y') if ts else '—'


def _row(agent):
    facts = (['Execution check succeeded ' + _date(agent.get('verified_at'))] if agent.get('verified_at')
             else ['Trial call succeeded'] if agent.get('trial_ok') else [])
    if agent.get('eval_grade'):
        facts.append('quality grade ' + agent['eval_grade'])
    if agent.get('report_grade'):
        facts.append('test report grade ' + agent['report_grade'])
    if agent.get('last_check_at'):
        facts.append('health check ' + (agent.get('health_status') or 'recorded') + ' ' + _date(agent['last_check_at']))
    if agent.get('probe_latency_ms') is not None:
        facts.append(f"{agent['probe_latency_ms']:,} ms")
    facts.append('sign-in required' if agent.get('auth_required') else 'no sign-in for the checked call')
    return ('<li><a href="/agent/' + str(int(agent['id'])) + '">' + esc(agent.get('name') or 'Unnamed agent') + '</a>'
            '<p class="caption">' + esc(' · '.join(facts)) + '</p></li>')


def _names():
    from .growth_catalog import categories
    return categories()


def weekly_page(week=None, path_fn=None):
    published = issues(path_fn)
    if not published:
        return None
    week = week or published[0]
    issue = read(week, path_fn)
    if issue is None:
        return None
    names = _names()
    counts = issue['counts']
    start = datetime.fromisoformat(issue['window_start'])
    end = datetime.fromisoformat(issue['captured_at'])
    period = start.strftime('%d %b') + ' – ' + end.strftime('%d %b %Y, %H:%M UTC')
    findings = [f"{counts['executed']:,} agents had a successful execution check between {period}: "
                f"{counts['executed_by_kind']['mcp']:,} MCP servers, {counts['executed_by_kind']['a2a']:,} A2A agents and "
                f"{counts['executed_by_kind']['x402']:,} x402 APIs.",
                f"{counts['evidence']:,} agents in the sample meet the evidence rule; {counts['trial_ok']:,} of them had a successful trial call."]
    changes = issue.get('changes')
    if changes:
        findings.append(f"Since {issue['previous']}: {changes['added']:,} agents newly meet the evidence rule and "
                        f"{changes['removed']:,} no longer do (inactive, failing or with checks older than the rule allows).")
    else:
        findings.append('This is the first issue, so there is no earlier week to compare with.')
    body = '<section class="card stack"><h2>This week</h2><ul>' + ''.join('<li>' + esc(x) + '</li>' for x in findings) + '</ul></section>'
    labels = {'mcp': 'MCP servers', 'a2a': 'A2A agents', 'x402': 'x402 APIs'}
    for kind in ('mcp', 'a2a', 'x402'):
        rows = issue['top'].get(kind) or []
        trial = (issue.get('basis') or {}).get(kind) == 'trial'
        heading = (' with a successful trial call and health check this week' if trial
                   else ' with a successful execution check this week')
        note = ('<p class="caption">Paid calls are not executed, so these are ranked by trial calls (the payment request '
                'answered as documented) and health checks recorded in the window.</p>' if trial else '')
        body += ('<section class="card stack" aria-labelledby="top-' + kind + '"><h2 id="top-' + kind + '">' + labels[kind]
                 + heading + '</h2>' + note
                 + ('<ol>' + ''.join(_row(a) for a in rows) + '</ol>' if rows
                    else '<p>No ' + labels[kind] + ' had a recorded execution check in this window.</p>') + '</section>')
    cats = sorted(issue['categories'].items(), key=lambda x: -x[1])
    by_cat = (changes or {}).get('by_category') or {}
    body += ('<section class="card stack" aria-labelledby="cat-h"><h2 id="cat-h">Agents meeting the evidence rule by category</h2><ul>'
             + ''.join('<li>' + esc(names.get(c, c)) + ': ' + f'{n:,}'
                       + (f' ({by_cat[c]:+,} since {esc(issue["previous"])})' if c in by_cat and changes else '') + '</li>' for c, n in cats)
             + '</ul></section>')
    body += ('<section class="card stack"><h2>Method</h2><p>Order within each list: a successful execution check in the window, then the '
             'quality score, the test report score and the latest health check. The evidence rule: a successful execution check in the '
             'last 30 days, or a successful trial call with a healthy status in the last 14 days and quality grade A or B. Figures come from '
             'a sample of the catalog collected per category and protocol (at most 300 listings each), so they are lower bounds. Recorded '
             'checks describe what happened when they ran, not that an agent works now.</p>'
             '<p>Every week: <a href="/reports/weekly">all issues</a> · Monthly: <a href="/reports/state-of-ai-agents">State of AI Agents</a> · '
             '<a href="/agents/tasks">agents by task</a></p></section>')
    title = 'Weekly agent evidence — ' + week
    description = ' '.join(findings)[:300]
    structured = {'@context': 'https://schema.org', '@type': 'Report', 'name': title, 'description': description,
                  'url': g.ORIGIN + '/reports/weekly/' + week, 'datePublished': issue['captured_at'],
                  'temporalCoverage': issue['window_start'] + '/' + issue['captured_at'],
                  'publisher': {'@type': 'Organization', 'name': 'Agent Concierge', 'url': g.ORIGIN + '/'}}
    return g.shell(title=title + ' | Agent Concierge', description=description, canonical=g.ORIGIN + '/reports/weekly/' + week,
                   body=g.heading('Weekly report · ' + week, title,
                                  'Agents with a recorded execution check this week, and how the set of agents with evidence changed.')
                   + '<div class="stack">' + body + '</div>', structured=structured, index=True)


def weekly_index(path_fn=None):
    published = issues(path_fn)
    if not published:
        return None
    items = ''.join('<li><a href="/reports/weekly/' + w + '">' + w + '</a></li>' for w in published)
    body = (g.heading('Weekly report', 'Weekly agent evidence', 'One issue per week, published every Monday from recorded checks.')
            + '<section class="card stack"><h2>Issues</h2><ul>' + items + '</ul></section>')
    return g.shell(title='Weekly agent evidence | Agent Concierge', description='Weekly issues listing agents with recorded execution checks.',
                   canonical=g.ORIGIN + '/reports/weekly', body=body,
                   structured={'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Weekly agent evidence',
                               'url': g.ORIGIN + '/reports/weekly'}, index=True)


def sitemap_paths(path_fn=None):
    published = issues(path_fn)
    return (['/reports/weekly'] + ['/reports/weekly/' + w for w in published]) if published else []


def install(router, page_headers, not_found):
    from fastapi.responses import HTMLResponse
    from starlette.concurrency import run_in_threadpool

    @router.get('/reports/weekly', include_in_schema=False)
    async def weekly_all():
        value = await run_in_threadpool(weekly_index)
        return HTMLResponse(value, headers=page_headers) if value else not_found()

    @router.get('/reports/weekly/{week}', include_in_schema=False)
    async def weekly_issue(week: str):
        value = await run_in_threadpool(weekly_page, week) if ISSUE.fullmatch(week) else None
        return HTMLResponse(value, headers=page_headers) if value else not_found()


def main(argv=None):
    """Write the issue for the current snapshot: python -m agent_market.concierge.weekly_report <public-pages dir> [--rebuild]"""
    import sys
    args = sys.argv[1:] if argv is None else argv
    base = Path(args[0]) if args else Path('logs/service-frontend/public-pages')
    snapshot = g.clean(json.loads((base / g.SNAPSHOT_NAME).read_text(encoding='utf-8')))
    print(json.dumps({'written': publish(base / FOLDER, snapshot, rebuild='--rebuild' in args)}))


if __name__ == '__main__':
    main()
