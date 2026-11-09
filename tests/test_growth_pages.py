"""Connect guide, task pages, MCP Registry metadata and the HTTP domain proof (11-09 growth plan)."""
import base64
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge import growth_pages as g

ROOT = Path(__file__).resolve().parents[1]
NOW = time.time()


def agent(rid, **extra):
    value = {'id': rid, 'kind': 'mcp', 'name': f'Agent {rid}', 'description': 'Weather forecasts for any city.',
             'health_status': 'healthy', 'last_check_at': NOW-3600, 'verified_at': None, 'trial_ok': True,
             'eval_grade': 'A', 'report_grade': None, 'probe_latency_ms': 120, 'auth_required': False, 'price_usdc': 0}
    value.update(extra)
    return value


def snapshot(captured=None, tasks=None):
    captured = captured or datetime.now(timezone.utc)
    return {'version': 1, 'captured_at': captured.isoformat(timespec='seconds'), 'tasks': tasks if tasks is not None else [
        {'slug': 'weather-forecast', 'title': 'Weather forecast', 'query': 'weather forecast', 'group': 'Weather, maps and travel',
         'agents': [agent(1, verified_at=NOW-7200), agent(2)]},
        {'slug': 'current-weather', 'title': 'Current weather', 'query': 'current weather', 'group': 'Weather, maps and travel',
         'agents': [agent(3), agent(4, eval_grade='C')]},  # one agent without evidence: page dropped
    ]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    folder = tmp_path/'public-pages'
    folder.mkdir()
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    monkeypatch.setattr(g, 'SNAPSHOT', g.Snapshot())
    app = FastAPI()
    app.include_router(g.growth_router())
    return TestClient(app), folder


def write(folder, value):
    (folder/g.SNAPSHOT_NAME).write_text(json.dumps(value))
    g.SNAPSHOT.checked = 0.


# ---------------------------------------------------------------- MCP Registry metadata
def test_server_json_matches_the_registry_schema_constraints_and_live_endpoint():
    path = ROOT/'deploy/mcp-registry/server.json'
    if not path.exists():
        pytest.skip('release copies do not carry deploy/mcp-registry')
    data = json.loads(path.read_text())
    assert data['$schema'] == 'https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json'
    assert re.fullmatch(r'[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+', data['name'])
    assert data['name'].startswith('biz.agentconcierge/')  # domain namespace for agentconcierge.biz
    assert 1 <= len(data['description']) <= 100 and 1 <= len(data['title']) <= 100
    assert re.fullmatch(r'\d+\.\d+\.\d+', data['version'])
    assert data['remotes'] == [{'type': 'streamable-http', 'url': g.MCP_URL}]
    assert 'packages' not in data


def test_registry_auth_serves_only_a_single_public_key_line(client):
    c, folder = client
    assert c.get('/.well-known/mcp-registry-auth').status_code == 404
    line = 'v=MCPv1; k=ed25519; p=' + base64.b64encode(b'k'*32).decode()
    (folder/g.AUTH_NAME).write_text(line+'\n')
    response = c.get('/.well-known/mcp-registry-auth', headers={'User-Agent': 'mcp-registry/1.0', 'Accept': 'text/plain'})
    assert response.status_code == 200 and response.text.strip() == line
    assert response.headers['content-type'].startswith('text/plain')
    for bad in ['-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEI\n-----END PRIVATE KEY-----', line+'\n'+line, 'x'*5000,
                'v=MCPv1; k=rsa; p=abc']:
        (folder/g.AUTH_NAME).write_text(bad)
        assert c.get('/.well-known/mcp-registry-auth').status_code == 404


# ---------------------------------------------------------------- connect guide
def test_connect_page_has_copyable_settings_for_each_client(client):
    c, _ = client
    response = c.get('/connect')
    assert response.status_code == 200
    text = response.text
    assert 'claude mcp add --transport http agent-concierge https://agentconcierge.biz/mcp' in text
    assert '&quot;type&quot;: &quot;http&quot;' in text and '&quot;servers&quot;' in text  # VS Code
    assert '&quot;mcpServers&quot;' in text  # Cursor
    assert 'MCPServerStreamableHttp' in text and 'HostedMCPTool' in text
    assert 'Add custom connector' in text
    link = re.search(r'href="(cursor://[^"]+)"', text).group(1).replace('&amp;', '&')
    query = parse_qs(urlparse(link).query)
    assert query['name'] == ['agent-concierge']
    assert json.loads(base64.b64decode(query['config'][0])) == {'url': g.MCP_URL}


@pytest.mark.parametrize('path', ['/connect', '/agents/tasks', '/agents/task/weather-forecast'])
def test_pages_use_the_shared_design_system_and_english_only(client, path):
    c, folder = client
    write(folder, snapshot())
    text = c.get(path).text
    for asset in ('styles.css', 'necklace.css', 'pearl-live.css', 'app.js'):
        assert '/new/en/assets/'+asset in text
    assert 'pearl-header' in text and 'main-wrap' in text and 'global-footer' in text
    assert '<style' not in text and ' style=' not in text  # no page-only styles
    assert not re.search(r'[ㄱ-힣]', text)  # public pages are English only
    assert '<link rel="canonical" href="https://agentconcierge.biz'+path+'">' in text
    data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', text).group(1))
    assert data['@context'] == 'https://schema.org'


# ---------------------------------------------------------------- task pages
def test_task_pages_list_only_agents_with_evidence(client):
    c, folder = client
    write(folder, snapshot())
    page = c.get('/agents/task/weather-forecast')
    assert page.status_code == 200
    assert 'Agent 1' in page.text and 'Agent 2' in page.text
    assert 'Execution check' in page.text and 'Trial call' in page.text and 'Quality grade' in page.text
    assert 'index, follow' in page.text
    # current-weather had only one agent with evidence, so it has no page.
    assert c.get('/agents/task/current-weather').status_code == 404
    assert c.get('/agents/task/..%2Fetc').status_code == 404
    index = c.get('/agents/tasks').text
    assert '/agents/task/weather-forecast' in index and '/agents/task/current-weather' not in index


def test_listing_text_is_escaped(client):
    c, folder = client
    hostile = agent(9, name='<script>alert(1)</script>', description='"><img src=x onerror=alert(1)>')
    write(folder, snapshot(tasks=[{'slug': 'web-search', 'title': 'Web search', 'query': 'web search', 'group': 'Search',
                                   'agents': [hostile, agent(10)]}]))
    text = c.get('/agents/task/web-search').text
    assert '<script>alert' not in text and '<img src=x' not in text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in text


def test_stale_or_missing_snapshot_leaves_the_sitemap(client):
    c, folder = client
    assert g.sitemap_paths() == ['/connect']
    assert c.get('/agents/tasks').status_code == 200  # still a page, with a fallback
    write(folder, snapshot())
    assert g.sitemap_paths() == ['/connect', '/agents/tasks', '/agents/task/weather-forecast']
    write(folder, snapshot(captured=datetime.now(timezone.utc)-timedelta(days=30)))
    assert g.sitemap_paths() == ['/connect']
    assert 'noindex' in c.get('/agents/task/weather-forecast').text


def test_old_evidence_does_not_count():
    assert g.clean_agent(agent(1, trial_ok=False, verified_at=NOW-40*86400)) is None
    assert g.clean_agent(agent(1, last_check_at=NOW-20*86400)) is None
    assert g.clean_agent(agent(1, health_status='unhealthy')) is None
    assert g.clean_agent(agent(1, trial_ok=False, eval_grade=None, verified_at=NOW-86400)) is not None


def test_task_page_responses_are_fast_file_reads(client):
    c, folder = client
    write(folder, snapshot(tasks=[{'slug': f'task-{i}', 'title': f'Task {i}', 'query': f'task {i}', 'group': 'Group',
                                   'agents': [agent(i*10+1), agent(i*10+2)]} for i in range(300)]))
    started = time.monotonic()
    for i in range(0, 300, 30):
        assert c.get(f'/agents/task/task-{i}').status_code == 200
    assert time.monotonic()-started < 3


# ---------------------------------------------------------------- builder
def test_builder_relevance_filter_and_snapshot_validation(tmp_path):
    from scripts.build_task_pages import relevant, slugify, write as write_snapshot, TASKS
    assert relevant('github issues', {'name': 'GitHub Issues and Pull Requests', 'description': ''})
    assert not relevant('github issues', {'name': 'Canton docs', 'description': 'Ledger docs'})
    assert relevant('translate a document', {'name': 'Translate', 'description': 'Translate text or a document'})
    slugs = [slugify(p) for phrases in TASKS.values() for p in phrases]
    assert len(slugs) == len(set(slugs)) and 50 <= len(slugs) <= 400
    assert all(g.SLUG.match(s) for s in slugs)
    out = tmp_path/'task-pages.json'
    write_snapshot(str(out), snapshot())
    assert g.clean(json.loads(out.read_text()))['tasks'][0]['slug'] == 'weather-forecast'
    with pytest.raises(SystemExit):
        write_snapshot(str(tmp_path/'bad.json'), {'version': 2})


# ---------------------------------------------------------------- integration with the frontend app
def test_front_app_routes_sitemap_and_llms(monkeypatch, tmp_path):
    from tests.test_concierge import populated
    from agent_market.concierge.front import create_front_app
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    (tmp_path/'public-pages').mkdir()
    monkeypatch.setattr(g, 'SNAPSHOT', g.Snapshot())
    write(tmp_path/'public-pages', snapshot())
    world = populated()
    c = TestClient(create_front_app(world.app.state.front))
    for path, code in [('/connect', 200), ('/agents/tasks', 200), ('/agents/task/weather-forecast', 200), ('/agents/task/none', 404)]:
        response = c.get(path, headers={'Accept': 'text/html'})
        assert response.status_code == code
        # The front middleware keeps a page's own policy; the strict default would block the shared assets.
        policy = response.headers['content-security-policy']
        assert "script-src 'self'" in policy and "style-src 'self'" in policy and "'unsafe-eval'" not in policy
    llms = c.get('/llms.txt').text
    assert '/connect' in llms and '/agents/tasks' in llms
    locs = [e.text for e in ET.fromstring(c.get('/sitemap.xml').text).iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    assert 'https://agentconcierge.biz/connect' in locs
    assert 'https://agentconcierge.biz/agents/task/weather-forecast' in locs
    assert 'https://agentconcierge.biz/agents/task/current-weather' not in locs
    about = (ROOT/'new/en/about.html').read_text()
    assert 'https://agentconcierge.biz/connect' in about
