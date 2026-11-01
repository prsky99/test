"""Renewed administrator console (P1): pearl shell, v2 reads and individual sessions only."""
import re
import subprocess
from pathlib import Path

import pytest

from agent_market.admin_next import ASSETS, TimedCache, percentile, summarize_gateway
from tests.test_dashboard import dash  # noqa: F401

D = {'X-Dashboard': '1'}


def login(client):
    password = 'Renewal-fixture-password'
    response = client.post('/admin/api/auth/login', json={'username': 'sadmin', 'password': 'sadmin'}, headers=D)
    if response.status_code == 200 and response.json()['user'].get('password_change_required'):
        changed = client.post('/admin/api/auth/change-password', headers={**D, 'authorization': 'Bearer ' + response.json()['token']},
            json={'current_password': 'sadmin', 'new_password': password})
        assert changed.status_code == 200
    response = client.post('/admin/api/auth/login', json={'username': 'sadmin', 'password': password}, headers=D)
    assert response.status_code == 200
    return {**D, 'authorization': 'Bearer ' + response.json()['token']}


def test_shell_is_static_with_strict_policy_and_no_inline_script(dash):
    _, client = dash
    page = client.get('/admin/next')
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    policy = page.headers['content-security-policy']
    assert "script-src 'self'" in policy and "style-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert not re.search(r'<script(?![^>]*\bsrc=)', page.text) and ' style=' not in page.text
    assert client.get('/admin/next/assets/core/app.js').headers['content-type'].startswith('text/javascript')
    assert client.get('/admin/next/assets/admin-pearl.css').status_code == 200
    for bad in ('../dashboard.py', 'core/../../dashboard.py', 'index.html', 'core/missing.js', 'areas/HOME.js'):
        assert client.get('/admin/next/assets/' + bad).status_code == 404


def test_v2_reads_require_an_individual_session(dash):
    _, client = dash
    path = '/admin/api/v2/home/bootstrap'
    assert client.get(path, headers=D).status_code == 401
    assert client.get(path, headers={**D, 'authorization': 'Bearer secret'}).status_code == 401  # shared machine token
    staff = login(client)
    assert client.get(path, headers={'authorization': staff['authorization']}).status_code == 403  # missing X-Dashboard
    body = client.get(path, headers=staff).json()
    assert body['me'] == {'username': 'sadmin', 'role': 'superadmin', 'name': body['me']['name']}
    assert {'overview', 'gateway', 'alerts', 'captured_at'} <= set(body)
    assert body['overview']['public_catalog']['cataloged'] >= 1 and isinstance(body['alerts'], list)


def test_gateway_and_storage_reads(dash):
    _, client = dash
    staff = login(client)
    assert client.get('/admin/api/v2/gateway/summary?hours=5', headers=staff).status_code == 400
    summary = client.get('/admin/api/v2/gateway/summary?hours=24', headers=staff)
    assert summary.status_code == 200 and 'no-store' in summary.headers['cache-control']
    assert {'operations', 'success_rate', 'error_codes', 'agents', 'timeline', 'captured_at'} <= set(summary.json())
    storage = client.get('/admin/api/v2/system/storage', headers=staff).json()
    assert storage['engine'] == 'sqlite' and storage['available'] is False


def test_gateway_summary_counts_codes_and_latency():
    operations = [{'source': 'chat', 'protocol': 'a2a', 'status': 'matched', 'error_code': None, 'n': 8},
                  {'source': 'workspace', 'protocol': 'mcp', 'status': 'failed', 'error_code': 'UPSTREAM_TOOL_ERROR', 'n': 2}]
    attempts = [{'resource_id': 7, 'status': 'succeeded', 'error_code': None, 'elapsed_ms': 100 + i, 'finished': i} for i in range(9)]
    attempts.append({'resource_id': 7, 'status': 'failed', 'error_code': 'UPSTREAM_TOOL_ERROR', 'elapsed_ms': 900, 'finished': 99})
    result = summarize_gateway(operations, attempts, {7: {'name': 'Docs', 'kind': 'mcp'}}, 24, 1.0)
    assert result['operations'] == 10 and result['success_rate'] == 0.8
    assert result['error_codes'] == [{'code': 'UPSTREAM_TOOL_ERROR', 'n': 2}]
    assert result['agents'][0] | {} == {'id': 7, 'calls': 10, 'succeeded': 9, 'last_error': 'UPSTREAM_TOOL_ERROR',
                                       'name': 'Docs', 'kind': 'mcp', 'success_rate': 0.9, 'p95_ms': 900}
    assert percentile([], .5) is None and percentile([3, 1, 2], .5) == 2


def test_timed_cache_serves_stale_once_and_refreshes_in_background():
    now = [0.0]; calls = []
    cache = TimedCache(5, 30, clock=lambda: now[0])
    loader = lambda: calls.append(1) or {'n': len(calls)}  # noqa: E731
    assert cache.get('k', loader) == {'n': 1, 'cache': 'miss'}
    assert cache.get('k', loader)['cache'] == 'hit'
    now[0] = 10.0
    assert cache.get('k', loader) == {'n': 1, 'cache': 'stale'}
    for _ in range(50):
        if cache.values['k'][1]['n'] == 2: break
        import time; time.sleep(.01)
    assert cache.values['k'][1] == {'n': 2}
    now[0] = 100.0
    assert cache.get('k', loader) == {'n': 3, 'cache': 'miss'}


def test_console_assets_are_korean_pearl_modules_without_inline_styles_or_emoji():
    files = sorted(ASSETS.rglob('*.js'))
    assert {p.name for p in files} >= {'app.js', 'api.js', 'ui.js', 'home.js', 'catalog.js', 'gateway.js', 'system.js', 'legacy.js'}
    for path in files:
        text = path.read_text()
        assert "setAttribute('style'" not in text and 'innerHTML' not in text and 'localStorage.setItem(TOKEN' not in text
        assert not re.search('[\U0001F300-\U0001FAFF☀-➿]', text), path
        checked = subprocess.run(['node', '--input-type=module', '--check'], input=text, text=True, capture_output=True)
        assert checked.returncode == 0, (path, checked.stderr)
    css = (ASSETS / 'admin-pearl.css').read_text() + (ASSETS / 'pearl-tokens.css').read_text()
    assert '--pearl-face' in css and 'prefers-reduced-motion' in css and 'body[data-theme=dark]' in css


def test_conditional_reads_answer_304_when_unchanged(dash):
    _, client = dash
    staff = login(client)
    first = client.get('/admin/api/v2/system/storage', headers=staff)
    tag = first.headers['etag']
    again = client.get('/admin/api/v2/system/storage', headers={**staff, 'If-None-Match': tag})
    assert again.status_code == 304 and again.content == b''


def test_catalog_cursor_pages_and_rejects_bad_filters(dash):
    _, client = dash
    staff = login(client)
    first = client.get('/admin/api/v2/catalog/agents?limit=2', headers=staff).json()
    assert len(first['items']) == 2 and first['total'] >= 3 and first['next_cursor'] == first['items'][-1]['id']
    second = client.get('/admin/api/v2/catalog/agents?limit=2&cursor=%d' % first['next_cursor'], headers=staff).json()
    assert second['total'] is None and all(item['id'] < first['next_cursor'] for item in second['items'])
    assert not {item['id'] for item in first['items']} & {item['id'] for item in second['items']}
    for bad in ('kind=evil', 'status=x', 'limit=0', 'limit=500', 'cursor=-1', 'q=' + 'a' * 121):
        assert client.get('/admin/api/v2/catalog/agents?' + bad, headers=staff).status_code == 400
    like = client.get('/admin/api/v2/catalog/agents?q=%25', headers=staff).json()  # a literal %, not a wildcard
    assert like['items'] == [] or all('%' in (item['name'] or '') + (item['url'] or '') for item in like['items'])


def test_agent_actions_need_reason_current_state_and_record_the_reason(dash):
    world, client = dash
    staff = login(client)
    rid = client.get('/admin/api/v2/catalog/agents?limit=1', headers=staff).json()['items'][0]['id']
    url = '/admin/api/v2/catalog/agents/%d/actions' % rid
    assert client.post(url, json={'action': 'deactivate', 'expected_active': True}, headers=staff).status_code == 400
    assert client.post(url, json={'action': 'deactivate', 'reason': 'ab', 'expected_active': True}, headers=staff).status_code == 400
    assert client.post(url, json={'action': 'drop', 'reason': '테스트 사유입니다'}, headers=staff).status_code == 400
    assert client.post(url, json={'action': 'deactivate', 'reason': '중복 등록 정리', 'expected_active': False}, headers=staff).status_code == 409
    since = client.get('/admin/api/v2/home/changes', headers=staff).json()['version']
    done = client.post(url, json={'action': 'deactivate', 'reason': '중복 등록 정리', 'expected_active': True}, headers=staff)
    assert done.status_code == 200 and 'catalog:agent:%d' % rid in done.json()['invalidate']
    assert world.store.resource(rid)['active'] == 0
    changed = client.get('/admin/api/v2/home/changes?since=%d' % since, headers=staff).json()
    assert changed['version'] > since and {'catalog:agents', 'catalog:agent:%d' % rid} <= set(changed['tags'])
    logs = client.get('/admin/api/audit/logs?action=AGENT_DEACTIVATE', headers=staff).json()['logs']
    assert '중복 등록 정리' in (logs[0]['details'] or '') and 'admin-next' in logs[0]['details']
    assert client.post(url, json={'action': 'activate', 'reason': '복구 확인', 'expected_active': False}, headers=staff).status_code == 200
    assert client.post(url, json={'action': 'activate', 'reason': '복구 확인', 'expected_active': True},
                       headers={**D, 'authorization': 'Bearer secret'}).status_code == 401


def test_execution_controls_are_superadmin_only_and_revision_checked(dash):
    world, client = dash
    staff = login(client)
    state = client.get('/admin/api/v2/gateway/controls', headers=staff).json()
    execution = state['execution']
    body = {'target': 'execution', 'reason': '점검을 위한 일시 중지', 'state': {
        'invoke_enabled': not execution['invoke_enabled'], 'workflow_enabled': execution['workflow_enabled'],
        'delivery_enabled': execution['delivery_enabled'], 'revision': execution['revision']}}
    saved = client.post('/admin/api/v2/gateway/controls', json=body, headers=staff)
    assert saved.status_code == 200 and saved.json()['result']['revision'] == execution['revision'] + 1
    assert client.post('/admin/api/v2/gateway/controls', json=body, headers=staff).status_code == 409  # stale revision
    back = {**body, 'state': {**body['state'], 'invoke_enabled': execution['invoke_enabled'], 'revision': execution['revision'] + 1}}
    # Turning a stopped switch back on is a reviewed command; without its migration it stays blocked.
    released = client.post('/admin/api/v2/gateway/controls', json=back, headers=staff)
    assert released.status_code == 409 and '마이그레이션' in released.json()['detail']
    assert client.post('/admin/api/v2/gateway/controls', json={**back, 'target': 'other'}, headers=staff).status_code in (400, 409)


def test_uncached_lists_also_revalidate_with_304(dash):
    _, client = dash
    staff = login(client)
    first = client.get('/admin/api/v2/catalog/agents?limit=2', headers=staff)
    assert client.get('/admin/api/v2/catalog/agents?limit=2', headers={**staff, 'If-None-Match': first.headers['etag']}).status_code == 304


def test_retention_preview_is_read_only_and_reports_unavailable_on_sqlite(dash):
    _, client = dash
    staff = login(client)
    body = client.get('/admin/api/v2/system/retention/preview', headers=staff).json()
    assert body['available'] is False and body['days'] == [3, 7, 14, 30]
    assert client.get('/admin/api/v2/system/retention/preview', headers=D).status_code == 401
