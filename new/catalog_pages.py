"""Publish the approved catalog-status revision from one timestamped snapshot."""
from datetime import datetime
from html import escape as e
from pathlib import Path
from urllib.parse import urlencode
import json

REVISION = 'revisions/2026-10-19-catalog-status/'
SNAPSHOT = json.loads((Path(__file__).parent / 'design' / REVISION / 'metrics-snapshot.json').read_text())
STAMP = datetime.fromisoformat(SNAPSHOT['captured_at_utc'])
PROTOCOLS = [('A2A', 'a2a'), ('MCP', 'mcp'), ('x402', 'x402')]
STATUSES = ['healthy', 'reachable', 'failing', 'down', 'unknown']


def number(value):
    return f'{value:,}'


def explore_link(**filters):
    return 'explore.html' + ('?' + urlencode(filters) if filters else '')


def timestamp():
    return f'<time datetime="{STAMP.isoformat()}">As of {STAMP:%d %b %Y} · {STAMP:%H:%M} UTC</time>'


def status_counts(kind):
    return {status: sum(row['n'] for row in SNAPSHOT['by_protocol_status'] if row['kind'] == kind and row['status'] == status) for status in STATUSES}


def metrics(ui, band=False):
    s, execution = SNAPSHOT, SNAPSHOT['execution_24h']
    values = [
        ('cataloged', s['cataloged'], 'Cataloged agents & services', f'+{number(s["new_24h"])} newly cataloged · last 24h', 'file'),
        ('reachable', s['reachable'], 'Recorded as reachable', f'{s["reachable_share"]}% of current listings', 'network'),
        ('with_status_check', s['with_status_check'], 'With a status check', 'Recorded connection observations', 'shield'),
        ('execution', execution['completed'], 'Execution checks · last 24h', f'{number(execution["successful_resources"])} agents with a successful check', 'settings'),
    ]
    cards = ''.join(
        '<div class="metric-card">' + (ui.pearl('small') if band else '<span class="icon-disc">' + ui.icon(ico) + '</span>')
        + f'<strong class="metric-value" data-metric="{key}">{number(value)}</strong><h2>{e(title)}</h2><p>{e(detail)}</p></div>'
        for key, value, title, detail, ico in values
    )
    if band:
        return '<section class="catalog-band" aria-label="Catalog snapshot"><div class="snapshot-heading"><span class="eyebrow">Design preview · Data snapshot</span><div class="row">' + timestamp() + '<a href="agent-status.html">View agent status →</a></div></div><div class="metric-grid metrics-band">' + cards + '</div></section>'
    return '<section class="metric-grid metrics-cards" aria-label="Catalog snapshot">' + cards + '</section>'


def outcomes(ui):
    execution = SNAPSHOT['execution_24h']
    return '<dl class="outcome-grid">' + ''.join(
        f'<div><dt><span class="status-dot {key}" aria-hidden="true"></span>{title}</dt><dd data-outcome="{key}">{number(execution[key])}</dd></div>'
        for key, title in [('succeeded', 'Succeeded'), ('failed', 'Failed'), ('unknown', 'Unknown')]
    ) + '</dl>'


def definitions(ui):
    items = [
        ('Catalog listings', 'Current active catalog entries for agents, tools and services.', 'file'),
        ('Connection observations', 'Recorded endpoint reachability checks, distinct from task success.', 'network'),
        ('Execution checks', 'Recorded task attempts in the stated 24-hour window.', 'settings'),
    ]
    return '<div class="grid three definition-grid">' + ''.join(
        '<article class="evidence-item"><span class="icon-disc">' + ui.icon(ico) + '</span><div><h3>' + title + '</h3><p>' + text + '</p></div></article>'
        for title, text, ico in items
    ) + '</div>'


def publish_home(ui):
    s = SNAPSHOT
    content = metrics(ui, band=True)
    content += '<section class="hero catalog-hero"><div><p class="eyebrow">Connected intelligence</p><h1>Valuable alone.<br>Remarkable together.</h1><p class="lead">Discover capable AI agents. Inspect the evidence.<br>Connect the right ones into purposeful workflows.</p><div class="actions">' + ui.btn(f'Explore {number(s["cataloged"])} listings', 'explore.html', 'search', 'primary') + ui.btn('View agent status', 'agent-status.html', 'activity') + '</div><form class="home-query" data-form="home">' + ui.icon('sparkles') + '<label class="sr-only" for="home-task">What do you want to accomplish?</label><input id="home-task" name="task" placeholder="What do you want to accomplish?"><label class="sr-only" for="home-protocol">Protocol</label><select name="protocol" id="home-protocol"><option>A2A</option><option>MCP</option><option>x402</option><option>Any</option></select><button class="icon-btn" aria-label="Find an agent">' + ui.icon('arrow') + '</button></form><a class="link-button small" href="test.html">Try a news example →</a></div>' + ui.necklace() + '</section>'
    content += '<section class="home-protocols" aria-label="Explore by protocol">' + ''.join(
        '<article><span class="icon-disc">' + ui.icon('network' if key == 'a2a' else 'settings' if key == 'mcp' else 'file') + '</span><div><h2>' + label + '</h2><p><strong>' + number(row['n']) + '</strong> listings</p><a href="' + e(explore_link(protocol=label), quote=True) + '">Explore ' + label + ' agents →</a></div></article>'
        for label, key in PROTOCOLS for row in s['by_protocol'] if row['kind'] == key
    ) + '</section>'
    content += '<section class="section catalog-changes"><h2>See what is changing.</h2><p class="lead">New listings and recent execution checks from our catalog.</p><div class="grid two"><article class="card change-card"><span class="icon-disc">' + ui.icon('file') + '</span><div><h3>' + number(s['new_24h']) + ' new listings in the last 24 hours</h3><p>Recently added agents and services across all protocols.</p><a class="link-button" href="' + explore_link(view='new') + '">Explore new arrivals →</a></div>' + ui.pearl('large') + '</article><article class="card change-card"><span class="icon-disc">' + ui.icon('settings') + '</span><div><h3>' + number(s['execution_24h']['completed']) + ' recorded execution checks</h3><p><strong>' + number(s['execution_24h']['succeeded']) + '</strong> succeeded · <strong>' + number(s['execution_24h']['failed']) + '</strong> failed · <strong>' + number(s['execution_24h']['unknown']) + '</strong> unknown</p><p class="caption">MCP execution evidence in this window.</p><a class="link-button" href="agent-status.html#execution-checks">Inspect the checks →</a></div>' + ui.pearl('large') + '</article></div></section>'
    content += '<section class="section"><h2>Turn individual strengths into a shared outcome.</h2>' + ui.strands([('Discover a capability', 'Start with the agent your task needs.'), ('Inspect the evidence', 'Understand the checks and limitations.'), ('Connect with purpose', 'Combine capabilities for a clearer result.')], True) + '</section>'
    content += '<section class="section"><h2>Start with something useful.</h2><p class="lead">Explore example use cases to see how agents can work together.</p><div class="grid three">' + ''.join(
        '<article class="card example-card"><div class="card-title"><span class="icon-disc">' + ui.icon(ico) + '</span><h3>' + title + '</h3></div><span class="badge">Example preview</span><p>' + copy + '</p>' + ui.btn('Try an example', 'test.html', 'arrow') + ui.pearl() + '</article>'
        for title, copy, ico in [('Technology news', 'Find, summarize and compare recent developments from multiple sources.', 'file'), ('Research', 'Bring together search, analysis and synthesis for a clearer understanding.', 'search'), ('Documentation', 'Turn information into structured documents, summaries or explanations.', 'book')]
    ) + '</div></section>'
    content += '<section class="section home-evidence"><h2>Evidence you can inspect.</h2><p class="lead">Understand what an agent does, how it connects, and what it produced before you run it.</p><div class="grid three definition-grid">' + ''.join(
        '<article class="evidence-item"><span class="icon-disc">' + ui.icon(ico) + '</span><div><h3>' + title + '</h3><p>' + copy + '</p></div></article>'
        for title, copy, ico in [('Recorded reports', 'See recorded outputs, source references and notes from earlier checks.', 'file'), ('Connection observations', 'Review how the endpoint responded through A2A, MCP or x402.', 'search'), ('Execution checks', 'Inspect recorded task attempts and notes about their limitations.', 'network')]
    ) + '</div>' + ui.note('Availability changes. Recorded checks are evidence, not a guarantee.') + '<details class="evidence-preview"><summary>Preview an agent report</summary><article class="card"><h3>Example agent report</h3><div class="tabs"><button class="tab" aria-selected="true" data-tab="overview">Overview</button><button class="tab" aria-selected="false" data-tab="evidence">Evidence</button><button class="tab" aria-selected="false" data-tab="connections">Connections</button></div><div data-tab-panel="overview"><p>Review the agent capability and intended input.</p></div><div data-tab-panel="evidence" hidden><p>Inspect recorded outputs and source references before connecting.</p></div><div data-tab-panel="connections" hidden><p>Review the selected protocol and intended connection.</p></div></article></details></section>'
    content += '<section class="end-cta pearl-cta"><div><h2>What will you connect next?</h2><p>Explore capable agents or browse example workflows.</p></div><div class="actions">' + ui.btn('Explore agents', 'explore.html', 'arrow', 'primary') + ui.btn('See agent status', 'agent-status.html', 'activity') + '</div></section>'
    ui.page('index.html', 'Connected intelligence, with evidence', content, REVISION + '01-home-with-catalog-status.png')


def publish_status(ui):
    s = SNAPSHOT
    content = '<section class="status-hero"><div><p class="eyebrow">The agent ecosystem</p><h1>See the scale.<br>Inspect the checks.</h1><p class="lead">A growing catalog of agents, tools and services, with recorded connection and execution evidence.</p></div><div class="snapshot-aside"><div class="status-pearls" aria-hidden="true">' + ui.pearl() + ui.pearl('large') + ui.pearl() + '</div><div class="snapshot-panel"><p class="caption">Design preview · Data snapshot</p>' + timestamp() + ui.btn('Refresh data', ico='refresh', cls='small', attrs='data-action="refresh-status" aria-describedby="snapshot-feedback"') + '</div></div></section>'
    content += metrics(ui) + '<p id="snapshot-feedback" class="caption snapshot-feedback" role="status">Captured snapshot. Refresh reviews this snapshot; live updates are not connected in this preview.</p>'
    content += '<section class="section"><h2>Explore by protocol</h2><p class="lead">Each protocol connects valuable individual capabilities into a broader ecosystem.</p><div class="grid three protocol-cards">'
    for label, kind in PROTOCOLS:
        row = next(row for row in s['by_protocol'] if row['kind'] == kind)
        counts = status_counts(kind)
        content += '<article class="card protocol-card"><div class="row">' + ui.pearl('large') + '<h3>' + label + '</h3></div><dl><dt>Total listings</dt><dd>' + number(row['n']) + '</dd><dt>Recorded as reachable</dt><dd>' + number(counts['healthy'] + counts['reachable']) + '</dd></dl>' + ui.btn('Explore ' + label, explore_link(protocol=label), 'arrow') + '</article>'
    content += '</div></section><section class="section" id="connection-status"><div class="between status-section-heading"><h2>Recorded connection status</h2><ul class="status-legend" aria-label="Connection status legend">' + ''.join('<li><span class="status-dot ' + key + '" aria-hidden="true"></span>' + key.title() + '</li>' for key in STATUSES) + '</ul></div><p>Counts in this snapshot are based on the latest recorded observations. This shows endpoint reachability, not task success.</p><div class="connection-layout"><article class="card reachable-card"><h3>Recorded as reachable</h3><dl class="reachable-list">'
    for label, kind in PROTOCOLS:
        counts = status_counts(kind)
        total = next(row['n'] for row in s['by_protocol'] if row['kind'] == kind)
        content += '<div><dt>' + ui.pearl('small') + label + '</dt><dd><strong>' + number(counts['healthy'] + counts['reachable']) + '</strong> of ' + number(total) + ' listings</dd></div>'
    content += '</dl></article><div class="table-wrap status-table" tabindex="0" role="region" aria-label="Connection observations by protocol"><table class="data-table"><caption class="sr-only">Recorded connection observations at the snapshot time</caption><thead><tr><th scope="col">Protocol</th>' + ''.join('<th scope="col">' + key.title() + '</th>' for key in STATUSES) + '</tr></thead><tbody>'
    for label, kind in PROTOCOLS:
        counts = status_counts(kind)
        content += '<tr data-status-protocol="' + label + '"><th scope="row">' + label + '</th>' + ''.join('<td data-status="' + key + '">' + number(counts[key]) + '</td>' for key in STATUSES) + '</tr>'
    content += '</tbody></table></div></div></section>'
    content += '<section class="grid two status-activity"><article class="card" id="execution-checks"><h2>Execution checks · last 24 hours</h2><p>Recorded task attempts and outcomes in the last 24 hours.</p><div class="execution-totals"><p><strong>' + number(s['execution_24h']['completed']) + '</strong> completed checks</p><p><strong>' + number(s['execution_24h']['successful_resources']) + '</strong> agents with a successful check</p></div><p class="execution-scope">Recorded execution attempts · MCP · 24 hours</p>' + outcomes(ui) + '<p class="caption">MCP execution evidence recorded in this window. A2A and x402 connection status is shown separately.</p></article><article class="card"><h2>New to the catalog</h2><p>Newly discovered agents and services in the last 24 hours.</p><strong class="arrival-total">' + number(s['new_24h']) + '</strong><p>new listings first observed in the last 24 hours.</p>' + ui.strands([('Discovered', 'New catalog listings'), ('Connection review', 'Review the endpoint response'), ('Evidence review', 'Inspect recorded evidence')]) + ui.btn('Explore new arrivals', explore_link(view='new'), 'arrow', 'primary') + '</article></section>'
    content += '<section class="section"><div class="between"><div><h2>Find your next useful agent.</h2><p class="lead">Explore selected categories and discover capabilities that match your goals.</p></div><span class="caption">Selected categories</span></div><div class="grid four category-cards">'
    for category, ico in [('Docs, Knowledge Bases & RAG', 'book'), ('Web Search & Scraping', 'search'), ('Data Utilities & Format Conversion', 'file'), ('Database & Analytics', 'database')]:
        row = next(row for row in s['categories'] if row['name'] == category)
        content += '<article class="card"><div class="card-title"><span class="icon-disc">' + ui.icon(ico) + '</span><h3>' + e(category) + '</h3></div><strong>' + number(row['n']) + '</strong><p>listings</p>' + ui.btn('Explore category', explore_link(category=category), 'arrow', 'small') + '</article>'
    content += '</div></section><section class="section"><h2>What these numbers mean.</h2><p>A few key definitions to help you interpret the data on this page.</p>' + definitions(ui) + '<div class="between status-bottom">' + ui.note('Recorded availability can change. Check an agent before connecting.', cls='warn') + ui.btn('Explore the catalog', 'explore.html', 'arrow', 'primary') + '</div></section>'
    ui.page('agent-status.html', 'Agent status — scale and recorded checks', content, REVISION + '02-agent-status.png', active='agent-status')
