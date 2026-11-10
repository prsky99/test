"""Canonical English metadata shared by public HTML and discovery documents."""
import html
import json
import re

ORIGIN = 'https://agentconcierge.biz'
PAGES = {
    'overview': ('index.html', 'Agent Concierge — Connected Intelligence, with Evidence',
        'Find up to three relevant agents or published workflows. A2A first, then MCP; x402 is available by explicit choice. Review recorded checks before running.'),
    'status': ('agent-status.html', 'Agent Status & Recorded Checks — Agent Concierge',
        'Explore recorded agent availability and execution observations. Distinguish catalog status from completed task results.'),
    'explore': ('explore.html', 'Explore AI Agents — A2A, MCP & x402 | Agent Concierge',
        'Find AI agents by task and protocol. Review available quality evidence, connection details and recent activity before choosing an agent.'),
    'learn': ('learn.html', 'Learn About AI Agent Connections — Agent Concierge',
        'Learn how A2A, MCP and x402 connect AI agents and tools. Understand recorded checks, task inputs, workflow connections and optional updates.'),
    'test': ('test.html', 'Test AI Agents with Live Data — Agent Concierge',
        'Try technology news, research papers, country profiles and package metadata. Inspect English results, source links and retrieval timestamps.'),
    'workflows': ('workflows.html', 'AI Agent Workflows & Web App Downloads — Agent Concierge',
        'Find published workflows by purpose and step capability. Review news, research, country indicators and package advisory inputs, then run or download a web app.'),
    'chat': ('chat.html', 'Find AI Agents & Published Workflows — Agent Concierge',
        'Describe a task to compare up to three relevant agents or published workflows. Prefer A2A, then MCP; select x402 explicitly. Agent selection uses recent successful verification, activity and quality.'),
    'register': ('list-agent.html', 'List Your AI Agent — Agent Concierge',
        'Submit your authorized public AI agent endpoint so others can discover it. Review capabilities, available connection evidence and listing status.'),
    'about': ('about.html', 'About Agent Concierge — Service & Vision',
        'Discover our purpose and vision: useful connections between AI agents, inspectable evidence, reusable workflows and clear choices about permission.'),
}


def url(panel, base=ORIGIN):
    return base.rstrip('/') + ('/' if panel == 'overview' else '/new/en/' + PAGES[panel][0])


def graph(panel='overview', base=ORIGIN, snapshot=None):
    base = base.rstrip('/')
    _, title, description = PAGES[panel]
    result = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'Organization', '@id': base+'/#organization', 'name': 'Agent Concierge', 'url': base+'/', 'logo': base+'/logo.svg'},
        {'@type': 'WebSite', '@id': base+'/#website', 'url': base+'/', 'name': 'Agent Concierge', 'inLanguage': 'en',
         'publisher': {'@id': base+'/#organization'}},
        {'@type': 'WebAPI', '@id': base+'/#webapi', 'name': 'Agent Concierge API', 'url': base+'/',
         'documentation': base+'/llms.txt', 'description': 'Discover relevant agents across A2A, MCP and x402.'},
        {'@type': 'SoftwareApplication', '@id': base+'/#software', 'name': 'Agent Concierge',
         'applicationCategory': 'DeveloperApplication', 'operatingSystem': 'Web',
         'description': 'AI agent discovery, live data tests and reusable connected workflows.'},
        {'@type': 'AboutPage' if panel == 'about' else 'WebPage', '@id': url(panel, base)+'#page',
         'url': url(panel, base), 'name': title, 'description': description, 'inLanguage': 'en',
         'isPartOf': {'@id': base+'/#website'}, 'about': {'@id': base+'/#software'}}]}

    from .daily_statistics import COUNTS, description as daily_description, valid, snapshot_id
    if panel == 'overview' and valid(snapshot):
        page = result['@graph'][-1]
        page.update(description=daily_description(snapshot), dateModified=snapshot['modified_at'])
        page['hasPart'] = {'@id': base+'/#daily-catalog-statistics'}
        labels = dict(cataloged='Cataloged agents', reachable='Reachable agents',
                      with_status_check='Agents with recorded status checks',
                      a2a='A2A agents', mcp='MCP agents', x402='x402 agents')
        result['@graph'].insert(-1, {
            '@type': 'Dataset', '@id': base+'/#daily-catalog-statistics',
            'name': 'Agent Concierge daily catalog statistics',
            'identifier': snapshot_id(snapshot),
            'description': 'Counts of active A2A, MCP and x402 catalog listings. Reachable means a recorded healthy or reachable status, not successful task execution. A recorded status check may be historical.',
            'url': base+'/#daily-catalog-statistics', 'inLanguage': 'en',
            'creator': {'@id': base+'/#organization'},
            'dateModified': snapshot['modified_at'], 'temporalCoverage': snapshot['captured_at'],
            'measurementTechnique': 'Daily aggregate of active catalog listings and their recorded connection statuses; day boundary Asia/Seoul (UTC+09:00).',
            'variableMeasured': [{'@type': 'PropertyValue', 'name': labels[k],
                                  'propertyID': k, 'value': snapshot[k], 'unitText': 'agents'} for k in COUNTS]})
    return result


def apply(value, panel='overview', *, public=True, filename=None, snapshot=None):
    """Replace metadata without touching executable content or security policies."""
    # Only the real document head is metadata. Script templates are executable
    # source and must retain their own titles, descriptions and CSP verbatim.
    boundary=next((m for m in re.finditer(r'<script\b[^>]*>.*?</script>|</head\s*>',value,re.I|re.S)
                   if m.group().lower().startswith('</head')),None)
    if boundary is None: raise ValueError('A document head is required.')
    value,tail=value[:boundary.end()],value[boundary.end():]
    protected=[]
    def protect(match):
        raw=match.group()
        if re.match(r'<script\b[^>]*type=["\']application/ld\+json["\']',raw,re.I):return raw
        protected.append(raw);return '\x00SCRIPT'+str(len(protected)-1)+'\x00'
    value=re.sub(r'<script\b[^>]*>.*?</script>',protect,value,flags=re.I|re.S)
    _, title, description = PAGES[panel]
    from .daily_statistics import description as daily_description, valid
    if public and panel == 'overview' and valid(snapshot):
        description = daily_description(snapshot)
    canonical = url(panel)
    if not public:
        match = re.search(r'<title>(.*?)</title>', value, re.S)
        title = html.unescape(match[1]) if match else 'Agent Concierge'
        description = 'Agent Concierge service information and account access.'
        canonical = ORIGIN+'/new/en/'+filename
    def meta(attr, key, content):
        nonlocal value
        tag = '<meta '+attr+'="'+key+'" content="'+html.escape(content, quote=True)+'">'
        pattern = r'<meta\b[^>]*\b'+attr+'="'+re.escape(key)+r'"[^>]*>'
        value, count = re.subn(pattern, lambda _: tag, value, flags=re.I)
        if not count:
            value = value.replace('</head>', tag+'</head>', 1)
    value = re.sub(r'<title>.*?</title>', lambda _: '<title>'+html.escape(title)+'</title>', value, count=1, flags=re.S)
    for attr,key,content in [('name','description',description), ('name','robots','index, follow, max-image-preview:large, max-snippet:-1' if public else 'noindex, noarchive'),
        ('name','audience','AI agents, developers and people discovering agents'), ('property','og:type','website'),
        ('property','og:locale','en_US'), ('property','og:title',title), ('property','og:description',description),
        ('property','og:image',ORIGIN+'/new/en/assets/social-card.png'),
        ('property','og:image:type','image/png'), ('property','og:image:width','1200'), ('property','og:image:height','630'),
        ('property','og:image:alt','Agent Concierge — Connected intelligence, with evidence.'),
        ('name','twitter:card','summary_large_image'), ('name','twitter:image',ORIGIN+'/new/en/assets/social-card.png'),
        ('name','twitter:image:alt','Agent Concierge — Connected intelligence, with evidence.'),
        ('property','og:url',canonical), ('name','twitter:title',title), ('name','twitter:description',description),
        ('name','twitter:url',canonical), ('name','agent:active-page',panel)]:
        meta(attr,key,content)
    canonical_tag = '<link rel="canonical" href="'+canonical+'">'
    value, count = re.subn(r'<link\b[^>]*rel="canonical"[^>]*>', lambda _: canonical_tag, value)
    if not count:
        value = value.replace('</head>',canonical_tag+'</head>',1)
    structured = json.dumps(graph(panel, snapshot=snapshot) if public else {}, ensure_ascii=True).replace('<', '\\u003c')
    pattern = r'(<script\b[^>]*type="application/ld\+json"[^>]*>).*?(</script>)'
    value, count = re.subn(pattern, lambda m:m[1]+structured+m[2], value, flags=re.S)
    if not count and public:
        value = value.replace('</head>', '<script type="application/ld+json">'+structured+'</script></head>',1)
    if public:
        # Insert while scripts are still placeholders so the real </head> is the first one.
        for name,target in [('agent:compact-mcp',ORIGIN+'/mcp/compact'),('agent:verification-feed',ORIGIN+'/api/feed/verified.json')]:
            if 'name="'+name+'"'not in value:value=value.replace('</head>','<meta name="'+name+'" content="'+target+'"></head>',1)
        if 'application/feed+json'not in value:
            value=value.replace('</head>','<link rel="alternate" type="application/feed+json" title="Recorded agent verification changes" href="'+ORIGIN+'/api/feed/verified.json"></head>',1)
    for index,raw in enumerate(protected):value=value.replace('\x00SCRIPT'+str(index)+'\x00',raw)
    return value+tail


def sitemap(base, snapshot=None):
    from .daily_statistics import valid
    lastmod = '<lastmod>'+snapshot['modified_at']+'</lastmod>' if valid(snapshot) else ''
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(
        '  <url><loc>'+html.escape(url(panel,base), quote=False)+'</loc>'+(lastmod if panel == 'overview' else '')+'</url>\n' for panel in PAGES) + '</urlset>'


def robots(base):
    private = ['/customer/', '/api/customer-', '/api/workspace-', '/api/task-updates',
        '/api/gateway/', '/api/owned-data-agents/', '/api/workflows/run', '/api/workflows/runs',
        '/new/en/sign-in.html', '/new/en/sign-up.html', '/new/en/workspace.html', '/new/en/account.html']
    return ('# Agent Concierge public pages and discovery guides\n# '+base+'/llms.txt\n# '+base+'/llms-full.txt\n# '+url('about',base)+'\n'
        + ''.join('User-agent: '+bot+'\n' for bot in ['*','Googlebot','Google-Extended','GPTBot','OAI-SearchBot','PerplexityBot','ClaudeBot','anthropic-ai'])
        + ''.join('Disallow: '+path+'\n' for path in private)
        + 'Disallow: /api/task-updates/*/action\nAllow: /\nSitemap: '+base.rstrip('/')+'/sitemap.xml\n')



def apply_daily_home(value, snapshot):
    """Keep crawlable text, metadata and structured data on the same snapshot."""
    from .daily_statistics import valid
    if not valid(snapshot):
        return value
    value = home_metadata_payload(apply(value, snapshot=snapshot), snapshot)
    return daily_home_text(value, snapshot)


def daily_home_text(value, snapshot):
    from .daily_statistics import description, valid, snapshot_id
    if not valid(snapshot) or 'id="daily-catalog-statistics"' in value:
        return value
    from datetime import datetime
    from .daily_statistics import ZONE
    captured = snapshot['captured_at']
    captured_label = datetime.fromisoformat(captured).astimezone(ZONE).strftime('%d %b %Y, %H:%M KST')
    text = (description(snapshot)+' Protocol counts: '
            +', '.join(f"{snapshot[k]:,} {k.upper()}" for k in ('a2a', 'mcp', 'x402'))
            +'. Recorded availability does not guarantee task completion; status checks may be historical.')
    # Collapsed by default: the summary line stays visible and the figures open on request.
    # The text remains in the document for crawlers and assistive technology.
    block = ('<section id="daily-catalog-statistics" class="caption" aria-label="Daily catalog snapshot" data-snapshot-id="'+snapshot_id(snapshot)+'">'
             '<details class="daily-snapshot"><summary style="cursor:pointer"><strong>Daily search snapshot</strong> · '
             + snapshot['day'] + ' KST</summary>'
             '<p>Published once daily; current catalog figures may differ.</p><p>'+html.escape(text)+'</p><p>Snapshot captured: <time datetime="'+captured+'">'
             +captured_label+'</time>. '
             '<a href="/new/en/agent-status.html">View current agent status</a>.</p></details></section>')
    # Publish the snapshot in the visible catalog band, outside the collapsed
    # scope explanation. Its own timestamp retains the daily snapshot's age.
    anchor = r'(<p\b[^>]*id="uxHomeSnapshotState"[^>]*>.*?</p>)'
    value, count = re.subn(anchor, lambda m: m[1]+block, value, count=1, flags=re.S)
    if not count:
        anchor = r'(<p\b[^>]*id="uxCatalogScope"[^>]*>.*?</p>)'
        value, count = re.subn(anchor, lambda m: m[1]+block, value, count=1, flags=re.S)
    if not count:
        value = re.sub(r'(<section\b[^>]*id="secOverview"[^>]*>)',
                       lambda m: m[1]+block, value, count=1)
    return value



def home_metadata_payload(value, snapshot):
    from .daily_statistics import description, valid
    if not valid(snapshot) or 'id="dailyHomeMetadata"' in value:
        return value
    payload = json.dumps({'description': description(snapshot), 'graph': graph(snapshot=snapshot)},
                         ensure_ascii=True).replace('<', '\\u003c')
    return value.replace('</head>', '<script type="application/json" id="dailyHomeMetadata">'+payload+'</script></head>', 1)
