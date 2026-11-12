"""11-09 outside-traffic plan stage 0: anonymous daily traffic counts."""
import json
from datetime import date

import pytest

from agent_market.concierge import traffic
from agent_market.concierge.traffic import Traffic, client_of, entry_of, mcp_client_name, summarize
from tests.test_fast_single_recommendation import catalog  # noqa: F401

CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36'


@pytest.mark.parametrize('method,path,entry', [
    ('GET', '/', 'home'), ('GET', '/new/en/chat.html', 'page'), ('POST', '/chat', 'chat'), ('POST', '/mcp', 'mcp'),
    ('POST', '/a2a', 'a2a'), ('POST', '/api/agent/v1/discover', 'agent_api'), ('POST', '/api/gateway/mcp/5', 'gateway'),
    ('GET', '/api/explore', 'explore'), ('GET', '/llms.txt', 'llms'), ('GET', '/.well-known/agent-card.json', 'well_known'),
    ('GET', '/robots.txt', 'crawl'), ('GET', '/customer/sign-in', 'workspace'), ('GET', '/new/en/assets/operating.js', None),
    ('GET', '/wp-login.php', None)])
def test_entries(method, path, entry):
    assert entry_of(method, path) == entry


@pytest.mark.parametrize('ip,ua,expected', [
    ('127.0.0.1', CHROME, ('internal', None)),
    ('203.0.113.5', 'AgentScenarioQA/1 (+site owner QA)', ('internal', None)),
    ('203.0.113.5', 'curl/8.14.1', ('script', None)),
    ('203.0.113.5', 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)', ('ai_bot', 'GPTBot')),
    ('203.0.113.5', 'Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)', ('ai_bot', 'ClaudeBot')),
    ('203.0.113.5', 'OverwingAtlas/1.0 (+https://overwing.ai/atlas; identity check)', ('verifier', None)),
    ('203.0.113.5', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/131.0 Safari/537.36', ('headless', None)),
    ('203.0.113.5', CHROME, ('browser', None)),
    ('203.0.113.5', '', ('other', None))])
def test_clients(ip, ua, expected):
    assert client_of(ip, ua, {'127.0.0.1', '::1'}) == expected


def test_mcp_client_name_is_a_bounded_software_name():
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'claude-code', 'version': '2'}}}).encode()
    assert mcp_client_name(body) == 'claude-code'
    odd = json.dumps({'method': 'initialize', 'params': {'clientInfo': {'name': '<script>x</script>'}}}).encode()
    assert mcp_client_name(odd) == 'unnamed'
    assert mcp_client_name(b'{"method":"tools/list"}') is None and mcp_client_name(None) is None


def test_file_holds_counts_only_and_rolls_over_daily(tmp_path, monkeypatch):
    now = [1794200000.0]
    t = Traffic(tmp_path, clock=lambda: now[0])
    t.observe('GET', '/', 200, '198.51.100.7', CHROME)
    t.observe('GET', '/', 200, '198.51.100.7', CHROME)
    t.observe('GET', '/new/en/chat.html', 200, '198.51.100.8', CHROME)
    t.observe('POST', '/mcp', 200, '198.51.100.9', 'node',
              json.dumps({'method': 'initialize', 'params': {'clientInfo': {'name': 'cursor'}}}).encode())
    t.observe('GET', '/llms.txt', 200, '198.51.100.10', 'Mozilla/5.0 (compatible; PerplexityBot/1.0)')
    t.observe('GET', '/', 200, '127.0.0.1', CHROME)
    t.flush()
    files = list(tmp_path.glob('*.json'))
    assert len(files) == 1
    text = files[0].read_text()
    # No address, user agent or body reaches the file.
    for secret in ('198.51.100', 'Mozilla', 'Chrome/156', 'Windows NT'):
        assert secret not in text
    data = json.loads(text)
    assert data['requests']['home|browser'] == 2 and data['distinct']['home|browser'] == 1
    assert data['requests']['home|internal'] == 1 and data['mcp_clients'] == {'cursor': 1}
    assert data['bots'] == {'PerplexityBot|llms': 1}
    assert oct(files[0].stat().st_mode & 0o777) == '0o600'
    salt = t.salt
    now[0] += 86400
    t.observe('GET', '/', 200, '198.51.100.7', CHROME)
    assert t.salt != salt and t.requests == {'home|browser': 1}
    assert len(list(tmp_path.glob('*.json'))) == 1  # the new day is written on its next flush


def test_summary_separates_internal_agents_bots_and_people(tmp_path):
    t = Traffic(tmp_path, clock=lambda: 1794200000.0)
    for ua in ('node', 'python-httpx/0.28'):
        t.observe('POST', '/mcp', 200, '203.0.113.1', ua, json.dumps({'method': 'initialize', 'params': {'clientInfo': {'name': 'agent-x'}}}).encode())
    t.observe('POST', '/chat', 200, '203.0.113.2', CHROME)
    t.observe('GET', '/', 200, '203.0.113.3', CHROME)
    t.observe('GET', '/robots.txt', 200, '203.0.113.4', 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)')
    t.observe('GET', '/llms.txt', 200, '203.0.113.5', 'Mozilla/5.0 (compatible; ClaudeBot/1.0)')
    t.observe('POST', '/chat', 200, '127.0.0.1', 'ChatQA/1 (site owner test)')
    t.flush()
    day = date.fromtimestamp(1794200000.0)
    row = [r for r in summarize(tmp_path, 1, today=day)][0]
    assert row['agent_requests'] == 2 and row['agent_clients'] == 2 and row['mcp_client_names'] == 1
    assert row['chat_browser'] == 1 and row['human_pages'] == 1 and row['human_visitors'] == 1
    assert row['ai_bot_google'] == 1 and row['ai_bot_non_google'] == 1
    assert row['internal'] == 1 and row['external'] == 6


def test_internal_addresses_come_from_env_and_an_operator_file(tmp_path, monkeypatch):
    (tmp_path / 'internal-ips.txt').write_text('# our server\n192.0.2.44\n')
    monkeypatch.setenv('TRAFFIC_INTERNAL_IPS', '192.0.2.45')
    ips = traffic.load_internal_ips(tmp_path)
    assert {'127.0.0.1', '::1', '192.0.2.44', '192.0.2.45'} <= ips


def test_public_app_counts_requests_through_the_real_middleware(catalog, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import create_front_app
    _, front, _, _, _ = catalog
    recorder = Traffic(tmp_path)
    monkeypatch.setattr(traffic, '_SINGLETON', recorder)
    client = TestClient(create_front_app(front))
    outside = {'X-Forwarded-For': '203.0.113.9', 'User-Agent': CHROME}
    assert client.get('/robots.txt', headers=outside).status_code == 200
    assert client.get('/llms.txt', headers={'X-Forwarded-For': '203.0.113.10',
                                             'User-Agent': 'Mozilla/5.0 (compatible; ClaudeBot/1.0)'}).status_code == 200
    assert client.get('/robots.txt').status_code == 200  # loopback: our own
    snap = recorder.snapshot()
    assert snap['requests']['crawl|browser'] == 1 and snap['requests']['crawl|internal'] == 1
    assert snap['bots'] == {'ClaudeBot|llms': 1}
    recorder.flush()
    assert '203.0.113' not in next(tmp_path.glob('*.json')).read_text()


def test_middleware_hook_is_present_and_guarded():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'agent_market/concierge/front.py').read_text()
    hook = src.split("# 11-09 outside-traffic plan stage 0", 1)[1][:800]   # 11-12: the call also passes the gateway outcome
    assert 'recorder().observe(request.method, request.url.path, response.status_code, client_ip,' in hook
    assert 'except Exception:\n            pass' in hook


def test_without_log_dir_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.chdir(tmp_path)
    t = Traffic()
    t.observe('GET', '/', 200, '203.0.113.1', CHROME)
    t.flush()
    assert t.root is None and t.snapshot()['requests'] == {'home|browser': 1}
    assert not any(tmp_path.rglob('*.json'))


def test_growth_pages_are_counted_by_family_and_bot(tmp_path):
    from agent_market.concierge import traffic as t
    assert [t.entry_of('GET', p) for p in ('/agents/task/x', '/agents/tasks', '/agent/12', '/agent/12/card.svg',
            '/agents/best/finance', '/agents/compare/1-vs-2', '/reports/state-of-ai-agents', '/connect',
            '/claude-plugins/marketplace.json')] == [
        'tasks', 'tasks', 'agent_pages', 'agent_pages', 'rankings', 'rankings', 'reports', 'connect', 'connect']
    rec = t.Traffic(tmp_path)
    rec.observe('GET', '/agents/task/x', 200, '203.0.113.9', 'Mozilla/5.0 (compatible; bingbot/2.0)')
    rec.observe('GET', '/agent/5', 200, '203.0.113.9', 'Mozilla/5.0 (compatible; Googlebot/2.1)')
    rec.flush()
    day = t.summarize(tmp_path, 1)[-1]
    assert day['growth_bot'] == 2


def test_security_blocks_are_counted_by_cause(tmp_path):
    """11-10: our own IP block and policy denials stay apart from protocol 403s in the 4xx counts."""
    from pathlib import Path
    rec = Traffic(tmp_path)
    body = b'{"jsonrpc":"2.0","id":1,"method":"initialize"}'
    rec.observe('POST', '/mcp', 403, '203.0.113.9', 'python-httpx/0.28', body, cause='blocked_ip')
    rec.observe('POST', '/mcp', 403, '203.0.113.9', 'python-httpx/0.28', body)
    statuses = sorted(key.split('|')[1] for key in rec.errors)
    assert statuses == ['403', '403:blocked_ip']
    src = (Path(__file__).resolve().parents[1] / 'agent_market/concierge/front.py').read_text()
    assert "cause=request.scope.get('traffic_cause')" in src
    assert src.count("request.scope['traffic_cause'] = 'blocked_ip'") == 1 and "'policy_denied'" in src


def test_spec_answers_and_missing_well_known_files_are_counted_apart(tmp_path):
    """11-11: 405 on MCP GET/DELETE and 404 on OAuth discovery are ':spec'; missing discovery files are named."""
    rec = Traffic(tmp_path)
    ua = 'python-httpx/0.28'
    rec.observe('GET', '/mcp', 405, '203.0.113.9', ua)
    rec.observe('DELETE', '/mcp', 405, '203.0.113.9', ua)
    rec.observe('GET', '/.well-known/oauth-protected-resource/mcp', 404, '203.0.113.9', ua)
    rec.observe('GET', '/.well-known/agents.json', 404, '203.0.113.9', ua)
    rec.observe('GET', '/.well-known/' + 'x' * 500, 404, '203.0.113.9', ua)
    keys = set(rec.errors)
    assert sum(k.split('|')[1] == '405:spec' for k in keys) == 2
    assert any(k.startswith('well_known|404:spec|GET|/.well-known/oauth-protected-resource/mcp|') for k in keys)
    assert any(k.startswith('well_known|404|GET|/.well-known/agents.json|') for k in keys)
    assert any(k.startswith('well_known|404|GET|other|') for k in keys) and all(len(k) < 160 for k in keys)


def test_ai_bot_errors_are_kept_per_status_and_cause(tmp_path):
    """11-11: ClaudeBot's 151 agent-page 4xx showed only as '4xx'; the day file now keeps each code."""
    from agent_market.concierge import traffic as t
    ua = 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)'
    rec = t.Traffic(tmp_path)
    rec.observe('GET', '/agent/5', 404, '216.73.217.9', ua)
    rec.observe('GET', '/agent/6', 404, '216.73.217.9', ua)
    rec.observe('GET', '/agents/compare/1-vs-2', 429, '216.73.217.9', ua)
    rec.observe('GET', '/agent/7', 403, '216.73.217.9', ua, cause='blocked_ip')
    rec.observe('GET', '/agent/8', 200, '216.73.217.9', ua)
    rec.observe('GET', '/agent/9', 404, '203.0.113.9', 'Mozilla/5.0 Chrome/120')   # people are not bots
    rec.flush()
    day = t.load_day(tmp_path, rec.day)['bot_errors']
    assert dict(day) == {'ClaudeBot|agent_pages|404': 2, 'ClaudeBot|rankings|429': 1, 'ClaudeBot|agent_pages|403:blocked_ip': 1}
