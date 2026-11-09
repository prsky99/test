"""Evidence pages built from the task snapshot catalog (11-09 growth plan, aggressive phase).

- /agent/{id}: one page per agent with recorded evidence, plus a README badge snippet.
- /agent/{id}/card.svg: an embeddable evidence card that links back to the agent page.
- /agents/best and /agents/best/{category}[/{kind}]: category rankings with the published basis.
- /agents/compare/{a}-vs-{b}: side-by-side recorded evidence for pairs listed in the snapshot only.
- /reports/state-of-ai-agents[/{yyyy-mm}]: monthly catalog report with server-rendered charts.

Every page reads the in-memory snapshot only. Rankings follow growth_pages.rank_key and say so on
the page; no page claims more than the recorded checks show.
"""
import html
import re
import statistics
from datetime import datetime, timezone
from urllib.parse import quote

from . import growth_pages as g

esc = g.esc
TOP = 20
PAIRS_PER_GROUP = 3
BASIS = ('Order: a successful execution check in the last 30 days first, then the quality score, the test report score '
         'and the most recent health check. Only agents with recorded evidence are listed.')
BADGE = g.ORIGIN + '/api/agent/v1/badge/{id}.svg'


def categories():
    from ..broker.categories import CATEGORIES
    return {key: (value.name_en or key.replace('_', ' ').title()) for key, value in CATEGORIES.items()}


def _date(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %Y') if value else None


def ranked(agents):
    return sorted(agents, key=g.rank_key, reverse=True)


def groups(snapshot):
    """category -> ranked agents, and (category, kind) -> ranked agents, from the snapshot catalog."""
    if snapshot.get('_groups') is None:
        by_cat, by_kind = {}, {}
        names = categories()
        for agent in snapshot['catalog'].values():
            if agent.get('category') in names:
                by_cat.setdefault(agent['category'], []).append(agent)
                by_kind.setdefault((agent['category'], agent['kind']), []).append(agent)
        snapshot['_groups'] = ({k: ranked(v) for k, v in by_cat.items()},
                               {k: ranked(v) for k, v in by_kind.items() if len(v) >= g.MIN_AGENTS})
    return snapshot['_groups']


def pairs(snapshot):
    """Comparison pages exist only for neighbours in a published ranking, so the URL space stays bounded."""
    if snapshot.get('_pairs') is None:
        found = set()
        lists = [t['agents'] for t in snapshot['tasks']] + list(groups(snapshot)[0].values())
        for agents in lists:
            top = [a['id'] for a in ranked(agents)[:PAIRS_PER_GROUP+1]]
            for left, right in zip(top, top[1:]):
                found.add((min(left, right), max(left, right)))
        snapshot['_pairs'] = found
    return snapshot['_pairs']


def compare_path(a, b):
    left, right = sorted((a, b))
    return f'/agents/compare/{left}-vs-{right}'


def sitemap_paths(snapshot):
    by_cat, by_kind = groups(snapshot)
    paths = ['/agents/best', '/reports/state-of-ai-agents/'+month(snapshot), '/badges']
    paths += ['/agents/best/'+c for c in sorted(by_cat) if len(by_cat[c]) >= g.MIN_AGENTS]
    paths += [f'/agents/best/{c}/{k}' for c, k in sorted(by_kind)]
    paths += [compare_path(a, b) for a, b in sorted(pairs(snapshot))]
    paths += ['/agent/'+str(i) for i in sorted(snapshot['catalog'])]
    return paths


def month(snapshot):
    return datetime.fromisoformat(snapshot['captured_at']).astimezone(timezone.utc).strftime('%Y-%m')


# ---------------------------------------------------------------- agent page
def badge_markdown(agent):
    return f'[![Agent Concierge check status]({BADGE.format(id=agent["id"])})]({g.ORIGIN}/agent/{agent["id"]})'


def card_html(agent):
    return (f'<a href="{g.ORIGIN}/agent/{agent["id"]}"><img src="{g.ORIGIN}/agent/{agent["id"]}/card.svg" '
            f'alt="{esc(agent["name"])} recorded checks on Agent Concierge" width="360" height="120"></a>')


def agent_page(rid, snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    agent = (snapshot or {}).get('catalog', {}).get(rid)
    if not agent:
        return None
    names = categories()
    kind = g.KINDS[agent['kind']]
    category = names.get(agent.get('category'))
    tasks = [t for t in snapshot['tasks'] if any(a['id'] == rid for a in t['agents'])][:8]
    peers = []
    if agent.get('category') in groups(snapshot)[0]:
        peers = [a for a in groups(snapshot)[0][agent['category']] if a['id'] != rid][:6]
    compares = [(a, b) for a, b in pairs(snapshot) if rid in (a, b)][:6]
    rows = ''.join('<div class="history-row"><span class="caption">'+esc(k)+'</span><span>'+esc(v)+'</span></div>'
                   for k, v in g.evidence_rows(agent)
                   + ([('Quality score', str(agent['eval_score']))] if agent.get('eval_score') is not None else [])
                   + ([('Published tools', str(agent['tool_count']))] if agent.get('tool_count') else []))
    title = agent['name']
    description = (f"{title}: {kind} {'agent' if agent['kind'] == 'a2a' else 'server' if agent['kind'] == 'mcp' else 'API'}"
                   + (f' for {category.lower()}' if category else '') + '. Recorded checks, quality grade and how to connect, from Agent Concierge.')
    sections = [
        '<section class="card stack" aria-labelledby="ev-h"><h2 id="ev-h">Recorded evidence</h2>'+rows
        + '<p class="caption">Snapshot captured '+esc(_date(snapshot['captured']))+'. Checks show what happened when they ran, not that the agent works now.</p></section>',
        '<section class="card stack" aria-labelledby="use-h"><h2 id="use-h">Use it</h2>'
        '<p>Open the listing in Explore for the connection details and current status, or ask Agent Concierge from your MCP client to compare it with alternatives for your task.</p>'
        '<div class="actions"><a class="btn primary" href="/new/en/explore.html#explore?q='+esc(quote(title))+'">Open in Explore</a>'
        '<a class="btn" href="/connect">Connect your MCP client</a></div></section>']
    if tasks:
        sections.append('<section class="card stack" aria-labelledby="tasks-h"><h2 id="tasks-h">Listed for these tasks</h2><ul>'
                        + ''.join('<li><a href="/agents/task/'+esc(t['slug'])+'">'+esc(g.display_title(t['title']))+'</a></li>' for t in tasks)+'</ul></section>')
    if peers:
        sections.append('<section class="card stack" aria-labelledby="peers-h"><h2 id="peers-h">Other '+esc(category.lower())+' agents with evidence</h2><ul>'
                        + ''.join('<li><a href="/agent/'+str(a['id'])+'">'+esc(a['name'])+'</a> <span class="caption">'+esc(g.KINDS[a['kind']])+'</span></li>' for a in peers)
                        + '</ul><p><a href="/agents/best/'+esc(agent['category'])+'">Full '+esc(category.lower())+' ranking</a></p></section>')
    if compares:
        sections.append('<section class="card stack" aria-labelledby="cmp-h"><h2 id="cmp-h">Comparisons</h2><ul>'
                        + ''.join('<li><a href="'+compare_path(a, b)+'">'+esc(snapshot['catalog'][a]['name'])+' vs '+esc(snapshot['catalog'][b]['name'])+'</a></li>'
                                  for a, b in compares if a in snapshot['catalog'] and b in snapshot['catalog'])+'</ul></section>')
    sections.append('<section class="card stack" aria-labelledby="badge-h"><h2 id="badge-h">Operate this agent?</h2>'
                    '<p>Show its current check status in your README. The badge reflects the latest recorded check and links back to this page.</p>'
                    '<p class="caption">Markdown</p><pre tabindex="0"><code>'+esc(badge_markdown(agent))+'</code></pre>'
                    '<p class="caption">Evidence card (HTML)</p><pre tabindex="0"><code>'+esc(card_html(agent))+'</code></pre>'
                    '<p><a href="/badges">About badges and cards</a></p></section>')
    body = (g.heading(kind + (' · '+category if category else ''), title, agent.get('description') or description)
            + '<div class="row"><span class="badge">'+esc(kind)+'</span>'+('<span class="badge success">Free</span>' if agent.get('free') else '')
            + ('<span class="badge">Grade '+esc(agent['eval_grade'])+'</span>' if agent.get('eval_grade') else '')+'</div>'
            + '<div class="grid two">'+''.join(sections)+'</div>')
    structured = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': title,
                  'applicationCategory': 'DeveloperApplication', 'operatingSystem': 'Web',
                  'description': agent.get('description') or description, 'url': g.ORIGIN+'/agent/'+str(rid),
                  'isAccessibleForFree': bool(agent.get('free')), 'dateModified': snapshot['captured_at']}
    return g.shell(title=title+' — '+kind+' recorded checks | Agent Concierge', description=description,
                   canonical=g.ORIGIN+'/agent/'+str(rid), body=body, structured=structured, index=g.fresh(snapshot))


def _svg_text(value, limit):
    value = g._text(value, limit)
    return html.escape(value, quote=True)


def card_svg(rid, snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    agent = (snapshot or {}).get('catalog', {}).get(rid)
    if not agent:
        return None
    if agent.get('verified_at'):
        line = 'Execution check succeeded · ' + _date(agent['verified_at'])
    elif agent.get('trial_ok'):
        line = 'Trial call succeeded · health ' + (_date(agent.get('last_check_at')) or 'recorded')
    else:
        line = 'Health check · ' + (_date(agent.get('last_check_at')) or 'recorded')
    grade = 'Grade ' + agent['eval_grade'] if agent.get('eval_grade') else 'Not graded'
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="120" viewBox="0 0 360 120" role="img" '
            'aria-label="'+_svg_text(agent['name'], 60)+': '+_svg_text(line, 80)+'">'
            '<title>'+_svg_text(agent['name'], 60)+' — recorded checks on Agent Concierge</title>'
            '<rect width="360" height="120" rx="14" fill="#f8f5ee" stroke="#a48154"/>'
            '<circle cx="30" cy="30" r="9" fill="#ffffff" stroke="#a48154" stroke-width="1.5"/>'
            '<text x="48" y="35" font-family="Georgia,serif" font-size="17" fill="#10272b">'+_svg_text(agent['name'], 30)+'</text>'
            '<text x="22" y="66" font-family="Arial,Helvetica,sans-serif" font-size="12" fill="#10272b">'+_svg_text(line, 52)+'</text>'
            '<rect x="22" y="80" width="86" height="24" rx="12" fill="#00626d"/>'
            '<text x="65" y="96" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="12" fill="#ffffff">'+_svg_text(grade, 14)+'</text>'
            '<text x="338" y="96" text-anchor="end" font-family="Arial,Helvetica,sans-serif" font-size="11" fill="#5b6b6e">'
            + _svg_text(g.KINDS[agent['kind']]+' · agentconcierge.biz', 40)+'</text></svg>')


# ---------------------------------------------------------------- rankings
def agent_row(position, agent):
    rows = g.evidence_rows(agent)[:3]
    return ('<article class="card stack" role="listitem"><div class="row"><span class="badge">#'+str(position)+'</span>'
            '<span class="badge">'+esc(g.KINDS[agent['kind']])+'</span>'
            + ('<span class="badge">Grade '+esc(agent['eval_grade'])+'</span>' if agent.get('eval_grade') else '')+'</div>'
            '<h3><a href="/agent/'+str(agent['id'])+'">'+esc(agent['name'])+'</a></h3>'
            + ('<p>'+esc(agent['description'])+'</p>' if agent.get('description') else '')
            + ''.join('<div class="history-row"><span class="caption">'+esc(k)+'</span><span>'+esc(v)+'</span></div>' for k, v in rows)
            + '</article>')


def best_page(category, kind=None, snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    if not snapshot:
        return None
    names = categories()
    by_cat, by_kind = groups(snapshot)
    agents = by_kind.get((category, kind)) if kind else by_cat.get(category)
    if category not in names or not agents or len(agents) < g.MIN_AGENTS:
        return None
    name = names[category]
    noun = {'a2a': 'A2A agents', 'mcp': 'MCP servers', 'x402': 'x402 APIs'}.get(kind, 'AI agents and MCP servers')
    top = agents[:TOP]
    title = f'Best {name.lower()} {noun}'
    description = (f'{len(top)} {name.lower()} {noun} ranked by recorded checks: execution checks, trial calls, quality scores. '
                   f'Snapshot {_date(snapshot["captured"])}.')
    kinds = sorted(k for c, k in by_kind if c == category)
    filters = ('<div class="actions">'+'<a class="btn small" href="/agents/best/'+esc(category)+'">All protocols</a>'
               + ''.join('<a class="btn small" href="/agents/best/'+esc(category)+'/'+k+'">'+esc(g.KINDS[k])+'</a>' for k in kinds)+'</div>')
    cmp_links = [(a, b) for a, b in pairs(snapshot) if a in {x['id'] for x in top[:4]} and b in {x['id'] for x in top[:4]}]
    compare = ('<section class="card stack" aria-labelledby="cmp-h"><h2 id="cmp-h">Compare the leaders</h2><ul>'
               + ''.join('<li><a href="'+compare_path(a, b)+'">'+esc(snapshot['catalog'][a]['name'])+' vs '+esc(snapshot['catalog'][b]['name'])+'</a></li>'
                         for a, b in sorted(cmp_links))+'</ul></section>') if cmp_links else ''
    body = (g.heading('Ranking · '+name, title, description)
            + '<div class="stack"><div class="note" role="note"><p>'+esc(BASIS)+' Rankings change as checks run; no listing pays for its position.</p></div>'
            + filters + '<div class="grid two" role="list" aria-label="'+esc(title)+'">'
            + ''.join(agent_row(i+1, a) for i, a in enumerate(top))+'</div>'+compare
            + '<p>All rankings: <a href="/agents/best">categories</a> · Task pages: <a href="/agents/tasks">by task</a></p></div>')
    structured = {'@context': 'https://schema.org', '@type': 'ItemList', 'name': title, 'description': description,
                  'url': g.ORIGIN+'/agents/best/'+category+('/'+kind if kind else ''), 'numberOfItems': len(top),
                  'itemListOrder': 'https://schema.org/ItemListOrderDescending',
                  'itemListElement': [{'@type': 'ListItem', 'position': i+1, 'name': a['name'], 'url': g.ORIGIN+'/agent/'+str(a['id'])}
                                      for i, a in enumerate(top)]}
    return g.shell(title=title+' — Agent Concierge', description=description,
                   canonical=g.ORIGIN+'/agents/best/'+category+('/'+kind if kind else ''), body=body, structured=structured,
                   index=g.fresh(snapshot))


def best_index(snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    if not snapshot:
        return None
    names = categories()
    by_cat, by_kind = groups(snapshot)
    cards = ''.join('<section class="card stack"><h2><a href="/agents/best/'+esc(c)+'">'+esc(names[c])+'</a></h2>'
                    '<p class="caption">'+str(len(by_cat[c]))+' agents with evidence</p><div class="row">'
                    + ''.join('<a class="btn small" href="/agents/best/'+esc(c)+'/'+k+'">'+esc(g.KINDS[k])+'</a>' for cc, k in sorted(by_kind) if cc == c)
                    + '</div></section>' for c in sorted(by_cat, key=lambda c: names[c]) if len(by_cat[c]) >= g.MIN_AGENTS)
    body = (g.heading('Rankings', 'Best AI agents and MCP servers by category', BASIS)
            + '<div class="grid two">'+cards+'</div>')
    return g.shell(title='Best AI Agents and MCP Servers by Category — Agent Concierge',
                   description='Category rankings of AI agents, MCP servers and x402 APIs, ordered by recorded execution checks, trial calls and quality scores.',
                   canonical=g.ORIGIN+'/agents/best', body=body,
                   structured={'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': 'Best AI agents by category', 'url': g.ORIGIN+'/agents/best'},
                   index=g.fresh(snapshot))


# ---------------------------------------------------------------- comparisons
def compare_page(left, right, snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    if not snapshot or (left, right) not in pairs(snapshot):
        return None
    a, b = snapshot['catalog'].get(left), snapshot['catalog'].get(right)
    if not a or not b:
        return None
    names = categories()

    def facts(agent):
        return dict([('Protocol', g.KINDS[agent['kind']]), ('Category', names.get(agent.get('category')) or '—')]
                    + g.evidence_rows(agent)
                    + [('Quality score', str(agent['eval_score']) if agent.get('eval_score') is not None else '—'),
                       ('Published tools', str(agent['tool_count']) if agent.get('tool_count') else '—'),
                       ('Price', 'Free' if agent.get('free') else 'Paid or unknown')])
    fa, fb = facts(a), facts(b)
    keys = list(dict.fromkeys([*fa, *fb]))
    table = ''.join('<div class="history-row"><span class="caption">'+esc(k)+'</span><span>'+esc(fa.get(k, '—'))+'</span><span>'
                    + esc(fb.get(k, '—'))+'</span></div>' for k in keys)
    title = f'{a["name"]} vs {b["name"]}'
    description = f'Compare {a["name"]} and {b["name"]} on recorded checks, quality grade, protocol and price. Snapshot {_date(snapshot["captured"])}.'
    body = (g.heading('Comparison', title, description)
            + '<div class="stack"><div class="note" role="note"><p>This page compares recorded evidence only. It does not say which agent is better for your task; '
            'describe the task in <a href="/new/en/chat.html">Chat</a> for a recommendation.</p></div>'
            + '<section class="card stack" aria-label="Side by side"><div class="history-row"><span class="caption">Field</span><strong><a href="/agent/'
            + str(a['id'])+'">'+esc(a['name'])+'</a></strong><strong><a href="/agent/'+str(b['id'])+'">'+esc(b['name'])+'</a></strong></div>'
            + table+'</section><div class="grid two">'
            + ''.join('<section class="card stack"><h2>'+esc(x['name'])+'</h2><p>'+esc(x.get('description') or '')+'</p>'
                      '<a class="btn small" href="/agent/'+str(x['id'])+'">Agent page</a></section>' for x in (a, b))+'</div></div>')
    return g.shell(title=title+' — Agent Concierge', description=description,
                   canonical=g.ORIGIN+compare_path(left, right), body=body,
                   structured={'@context': 'https://schema.org', '@type': 'WebPage', 'name': title, 'url': g.ORIGIN+compare_path(left, right),
                               'about': [{'@type': 'SoftwareApplication', 'name': x['name'], 'url': g.ORIGIN+'/agent/'+str(x['id'])} for x in (a, b)]},
                   index=g.fresh(snapshot))


# ---------------------------------------------------------------- badges guide
def badges_page():
    example = {'id': 244554, 'name': 'Your agent'}
    body = (g.heading('Badges', 'Show your agent\'s recorded checks',
                      'Every agent with recorded evidence has a page on Agent Concierge. Link to it from your README with a live badge or an evidence card.')
            + '<div class="stack"><section class="card stack"><h2>Live status badge</h2>'
            '<p>The badge reads the latest recorded check for the current version of your listing and is cached for at most five minutes. '
            'It shows Verified only while a successful execution check is less than 24 hours old; otherwise it shows Unverified.</p>'
            '<pre tabindex="0"><code>'+esc(badge_markdown(example).replace('244554', '{id}'))+'</code></pre></section>'
            '<section class="card stack"><h2>Evidence card</h2><p>A 360 × 120 card with the latest check, its date and the quality grade, from the daily snapshot.</p>'
            '<pre tabindex="0"><code>'+esc(card_html(example).replace('244554', '{id}'))+'</code></pre></section>'
            '<section class="card stack"><h2>Find your agent ID</h2><p>Search for your listing in <a href="/new/en/explore.html">Explore</a> or on a '
            '<a href="/agents/best">ranking page</a>; the agent page URL ends with the ID. Not listed yet? '
            '<a href="/new/en/list-agent.html">List your agent</a>; checks are read-only.</p></section>'
            '<section class="card stack"><h2>What the badge does not mean</h2><p>A badge reports recorded checks. It is not an endorsement, '
            'a security review or a guarantee that the agent works now, and it cannot be bought.</p></section></div>')
    return g.shell(title='Agent Concierge Badges for AI Agents and MCP Servers',
                   description='Add a live check-status badge or an evidence card for your AI agent or MCP server to your README.',
                   canonical=g.ORIGIN+'/badges', body=body,
                   structured={'@context': 'https://schema.org', '@type': 'TechArticle', 'headline': 'Agent Concierge badges', 'url': g.ORIGIN+'/badges'})


# ---------------------------------------------------------------- monthly report
def bar_chart(title, rows, unit=''):
    """Server-rendered horizontal bars; presentation attributes only (no inline styles)."""
    if not rows:
        return ''
    top = max(v for _, v in rows) or 1
    height = 28*len(rows)+12
    bars = ''.join(
        f'<text x="0" y="{28*i+22}" font-family="Arial,Helvetica,sans-serif" font-size="12" fill="currentColor">{esc(g._text(label, 34))}</text>'
        f'<rect x="230" y="{28*i+9}" width="{max(2, round(330*v/top))}" height="16" rx="4" fill="#00626d"/>'
        f'<text x="{236+max(2, round(330*v/top))}" y="{28*i+22}" font-family="Arial,Helvetica,sans-serif" font-size="12" fill="currentColor">{v:,}{unit}</text>'
        for i, (label, v) in enumerate(rows))
    table = ''.join('<tr><th scope="row">'+esc(label)+'</th><td>'+f'{v:,}{unit}'+'</td></tr>' for label, v in rows)
    return ('<figure class="card stack"><figcaption><h2>'+esc(title)+'</h2></figcaption>'
            f'<svg viewBox="0 0 640 {height}" width="100%" role="img" aria-label="{esc(title)}">{bars}</svg>'
            '<details><summary>Data table</summary><table class="data-table"><tbody>'+table+'</tbody></table></details></figure>')


def report_page(requested=None, snapshot=None):
    snapshot = g.SNAPSHOT.read() if snapshot is None else snapshot
    if not snapshot:
        return None
    current = month(snapshot)
    if requested not in (None, current):
        return None
    names = categories()
    stats = snapshot.get('stats') or {}
    agents = list(snapshot['catalog'].values())
    by_cat, _ = groups(snapshot)
    executed = sum(1 for a in agents if a.get('verified_at'))
    trial = sum(1 for a in agents if a.get('trial_ok'))
    latencies = [a['probe_latency_ms'] for a in agents if a.get('probe_latency_ms') is not None]
    open_access = sum(1 for a in agents if not a.get('auth_required'))
    free = sum(1 for a in agents if a.get('free'))
    grades = {}
    for a in agents:
        if a.get('eval_grade'):
            grades[a['eval_grade']] = grades.get(a['eval_grade'], 0)+1
    pct = lambda n: f'{100*n/len(agents):.0f}%' if agents else '—'
    headline = []
    if stats:
        headline.append(f'The catalog lists {stats["cataloged"]:,} public agents ({stats["a2a"]:,} A2A, {stats["mcp"]:,} MCP, {stats["x402"]:,} x402); '
                        f'{stats["reachable"]:,} ({100*stats["reachable"]/max(1, stats["cataloged"]):.0f}%) had a recorded reachable status in the daily snapshot of {stats["day"]}.')
    headline.append(f'{len(agents):,} agents in this report\'s sample carry recorded evidence beyond reachability: '
                    f'{executed:,} with a successful execution check in the last 30 days and {trial:,} with a successful trial call.')
    if latencies:
        headline.append(f'Median recorded response time among them: {statistics.median(latencies):,.0f} ms. '
                        f'{pct(open_access)} need no sign-in for the checked calls and {pct(free)} are free to call.')
    findings = '<section class="card stack"><h2>Key findings</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in headline)+'</ul></section>'
    charts = ''
    if stats:
        charts += bar_chart('Catalog by protocol', [('A2A agents', stats['a2a']), ('MCP servers', stats['mcp']), ('x402 APIs', stats['x402'])])
    charts += bar_chart('Agents with evidence by category', sorted(((names[c], len(v)) for c, v in by_cat.items()), key=lambda x: -x[1])[:14])
    charts += bar_chart('Agents with evidence by protocol', [(g.KINDS[k], sum(1 for a in agents if a['kind'] == k)) for k in ('a2a', 'mcp', 'x402')])
    charts += bar_chart('Quality grades among agents with evidence', [('Grade '+k, grades[k]) for k in sorted(grades)])
    method = ('<section class="card stack"><h2>Method</h2><p>Catalog counts come from the published daily snapshot (<a href="/status.json">status.json</a>). '
              'Evidence figures come from a sample of the catalog collected through the public Explore API for every category and protocol, '
              'keeping listings with a successful execution check in the last 30 days, or a successful trial call with a healthy status in the last '
              '14 days and quality grade A or B. Each category and protocol query returns at most 300 listings, so these are lower bounds, not '
              'totals. Recorded checks describe what happened when they ran.</p>'
              '<p>Cite as: Agent Concierge, "State of AI Agents, '+esc(datetime.fromisoformat(snapshot['captured_at']).strftime('%B %Y'))+'", '
              + esc(g.ORIGIN+'/reports/state-of-ai-agents/'+current)+'.</p></section>')
    title = 'State of AI Agents — ' + datetime.fromisoformat(snapshot['captured_at']).strftime('%B %Y')
    description = ' '.join(headline)[:300]
    body = (g.heading('Report · '+current, title, 'A monthly look at public A2A agents, MCP servers and x402 APIs, and how many carry recorded evidence.')
            + '<div class="stack">'+findings+charts+method
            + '<p>Explore further: <a href="/agents/best">rankings by category</a> · <a href="/agents/tasks">agents by task</a></p></div>')
    structured = {'@context': 'https://schema.org', '@type': 'Report', 'name': title, 'description': description,
                  'url': g.ORIGIN+'/reports/state-of-ai-agents/'+current, 'datePublished': snapshot['captured_at'],
                  'publisher': {'@type': 'Organization', 'name': 'Agent Concierge', 'url': g.ORIGIN+'/'}}
    return g.shell(title=title+' | Agent Concierge', description=description,
                   canonical=g.ORIGIN+'/reports/state-of-ai-agents/'+current, body=body, structured=structured, index=g.fresh(snapshot))


def install(router, page_headers, not_found):
    from fastapi.responses import HTMLResponse, Response
    from starlette.concurrency import run_in_threadpool

    def page(value):
        return HTMLResponse(value, headers=page_headers) if value else not_found()

    @router.get('/agent/{rid}', include_in_schema=False)
    async def agent(rid: str):
        return page(await run_in_threadpool(agent_page, int(rid)) if re.fullmatch(r'[1-9][0-9]{0,9}', rid) else None)

    @router.get('/agent/{rid}/card.svg', include_in_schema=False)
    async def card(rid: str):
        value = await run_in_threadpool(card_svg, int(rid)) if re.fullmatch(r'[1-9][0-9]{0,9}', rid) else None
        if not value:
            return Response(status_code=404)
        return Response(value, media_type='image/svg+xml', headers={
            'Cache-Control': 'public, max-age=3600', 'Access-Control-Allow-Origin': '*',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})

    @router.get('/agents/best', include_in_schema=False)
    async def best_all():
        return page(await run_in_threadpool(best_index))

    @router.get('/agents/best/{category}', include_in_schema=False)
    async def best(category: str):
        return page(await run_in_threadpool(best_page, category) if re.fullmatch(r'[a-z_]{2,40}', category) else None)

    @router.get('/agents/best/{category}/{kind}', include_in_schema=False)
    async def best_kind(category: str, kind: str):
        ok = re.fullmatch(r'[a-z_]{2,40}', category) and kind in g.KINDS
        return page(await run_in_threadpool(best_page, category, kind) if ok else None)

    @router.get('/agents/compare/{pair}', include_in_schema=False)
    async def compare(pair: str):
        match = re.fullmatch(r'([1-9][0-9]{0,9})-vs-([1-9][0-9]{0,9})', pair)
        return page(await run_in_threadpool(compare_page, int(match[1]), int(match[2])) if match else None)

    @router.get('/badges', include_in_schema=False)
    def badges():
        return page(badges_page())

    @router.get('/reports/state-of-ai-agents', include_in_schema=False)
    async def report_latest():
        return page(await run_in_threadpool(report_page))

    @router.get('/reports/state-of-ai-agents/{period}', include_in_schema=False)
    async def report(period: str):
        return page(await run_in_threadpool(report_page, period) if re.fullmatch(r'20[0-9]{2}-[01][0-9]', period) else None)
