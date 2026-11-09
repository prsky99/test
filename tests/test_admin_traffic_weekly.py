"""관리자 화면의 외부 유입 주간 지표(2026-11-09, 운영·SRE)."""
import json
from datetime import date
from pathlib import Path

from agent_market.concierge.traffic import Traffic
from agent_market.gateway import traffic_report
from tests.test_dashboard import H, dash  # noqa: F401  (fixture)

CHROME = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
NOW = 1794200000.0


def _fill(root):
    t = Traffic(root, clock=lambda: NOW)
    t.observe('POST', '/mcp', 200, '203.0.113.1', 'node',
              json.dumps({'method': 'initialize', 'params': {'clientInfo': {'name': 'agent-x'}}}).encode())
    t.observe('GET', '/', 200, '203.0.113.3', CHROME)
    t.observe('GET', '/llms.txt', 200, '203.0.113.5', 'Mozilla/5.0 (compatible; ClaudeBot/1.0)')
    t.observe('GET', '/robots.txt', 200, '203.0.113.4', 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)')
    t.observe('POST', '/chat', 200, '127.0.0.1', 'ChatQA/1 (site owner test)')
    t.flush()


def test_weekly_totals_and_internal_ratio(tmp_path):
    _fill(tmp_path)
    report = traffic_report.weekly(tmp_path, 7, today=date.fromtimestamp(NOW))
    t = report['totals']
    assert report['available'] and len(report['rows']) == 7
    assert t['agent_sessions'] == 1 and t['mcp_clients'] == 1 and t['mcp_client_names'] == 1
    assert t['ai_bot_non_google'] == 1 and t['ai_bot_google'] == 1 and t['human_visitors'] == 1
    assert t['internal'] == 1 and t['external'] == 4 and t['internal_ratio'] == 0.2
    assert report['mcp_clients_top'] == [{'name': 'agent-x', 'count': 1}]
    assert [b['name'] for b in report['bots_non_google_top']] == ['ClaudeBot']


def test_missing_directory_is_reported_not_raised(tmp_path):
    report = traffic_report.weekly(tmp_path / 'absent')
    assert report['available'] is False and report['totals']['internal_ratio'] is None


def test_admin_process_reads_the_frontend_directory(monkeypatch, tmp_path):
    monkeypatch.delenv('TRAFFIC_DIR', raising=False)
    monkeypatch.setenv('LOG_DIR', str(tmp_path / 'logs' / 'service-admin'))
    assert traffic_report.frontend_traffic_dir() == tmp_path / 'logs' / 'service-frontend' / 'traffic'


def test_admin_api_needs_login_and_returns_counts(dash, monkeypatch, tmp_path):  # noqa: F811
    _, client = dash
    _fill(tmp_path)
    monkeypatch.setenv('TRAFFIC_DIR', str(tmp_path))
    assert client.get('/admin/api/traffic/weekly', headers={'X-Dashboard': '1'}).status_code == 401
    r = client.get('/admin/api/traffic/weekly?days=7', headers=H)
    assert r.status_code == 200 and 'no-store' in r.headers['cache-control']
    body = r.json()
    assert set(body['totals']) >= {'agent_sessions', 'mcp_clients', 'ai_bot_non_google', 'human_visitors', 'internal_ratio'}
    assert '203.0.113' not in r.text


def test_card_is_korean_and_loads_without_blocking_the_visitor_list():
    html = (Path(__file__).resolve().parents[1] / 'agent_market' / 'gateway' / 'dashboard.html').read_text(encoding='utf-8')
    assert '외부 유입 주간 지표' in html and 'internal 비율' in html and 'Google 외 AI 봇' in html
    start = html.index('async function loadVisitors() {')
    body = html[start:html.index('\n}\n', start)]
    assert '  loadTrafficWeekly();\n' in body  # 병렬: 방문자 목록을 기다리게 하지 않음
    assert 'await loadTrafficWeekly' not in html
    assert 'api("/admin/api/traffic/weekly?days=7",{silent:true})' in html  # 전체 화면 로딩 없음
