"""Report browsing is read-only, single-flight and honest about missing evidence."""
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.report_fixtures import execution_report

playwright = pytest.importorskip('playwright.sync_api')


@pytest.fixture
def report_page(browser, tmp_path, rotated_bootstrap_admin):
    path = str(tmp_path / 'admin-reports.db')
    store = Store(path)
    ids = []
    for name, slug, status in [('Alpha stored document', 'alpha-history', None),
                               ('Beta stored document', 'beta-history', 500)]:
        rid = store.create_test_report({'title': name, 'slug': slug, 'kind': 'mcp',
            'agent_name': name, 'agent_url': f'https://{slug}.example/mcp',
            'summary': name, 'is_success': 0 if status else 1, 'tags': 'history'})
        ids.append(rid)
        if status is None:
            with store.tx() as db:
                db.execute('UPDATE agent_test_reports SET status_code=NULL,latency_ms=NULL,eval_grade=NULL,eval_score=NULL WHERE id=?', (rid,))
    app = FastAPI()
    app.include_router(dashboard_router(store, path, 'isolated-report-browser-token', None,
                                       ssl_manager=Mock(get_status=lambda: {})))
    client = TestClient(app, base_url='https://admin.test')
    context = browser.new_context()
    page = context.new_page()
    state = SimpleNamespace(page=page, store=store, client=client, ids=ids, calls=[],
                            hold_lists=False, hold_details=False, errors=[], external=[])

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'admin.test':
            state.external.append(url.hostname)
            return route.abort()
        if request.method not in ('GET', 'HEAD') and url.path != '/admin/api/auth/login':
            pytest.fail('Report browsing must never send a mutation or execute a provider.')
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        call = {'route': route, 'response': response, 'path': url.path, 'method': request.method,
                'query': parse_qs(url.query), 'released': False}
        state.calls.append(call)
        if url.path == '/admin/api/test-reports' and state.hold_lists:
            return
        if url.path.startswith('/admin/api/test-reports/') and state.hold_details:
            return
        _release(call)

    context.route('**/*', serve)
    page.on('pageerror', lambda error: state.errors.append(str(error)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin')
    page.locator('#adminLoginPassword').fill('sadmin')
    page.locator('#adminLoginSubmitBtn').click()
    playwright.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    try:
        yield state
    finally:
        for call in state.calls:
            if not call['released']:
                call['released'] = True
                call['route'].abort()
        page.wait_for_timeout(0)
        context.close()
        client.close()
        store._db.close()


def _release(call, status=None):
    call['released'] = True
    response = call['response']
    if status:
        call['route'].fulfill(status=status, content_type='application/json',
                              body=json.dumps({'detail': 'Earlier isolated lookup failed.'}))
    else:
        call['route'].fulfill(status=response.status_code, body=response.content,
                             headers={key: value for key, value in response.headers.items()
                                      if key not in ('content-length', 'content-encoding', 'transfer-encoding')})


def _lists(state):
    return [call for call in state.calls if call['path'] == '/admin/api/test-reports']


def _wait(state, count, *, details=False):
    deadline = time.monotonic() + 3
    pick = lambda: [call for call in state.calls if call['path'].startswith('/admin/api/test-reports/')] if details else _lists(state)
    while len(pick()) < count and time.monotonic() < deadline:
        state.page.wait_for_timeout(10)
    assert len(pick()) == count
    return pick()


def _open(state):
    state.page.locator('[data-tab="test_reports"]').click()
    playwright.expect(state.page.locator('#testReportsFeed .report-card')).to_have_count(2)
    state.page.wait_for_function('() => !testReportsRequest')


def test_repeat_refresh_joins_one_get_and_never_creates_or_reexecutes_report(report_page):
    state = report_page
    _open(state)
    before = len(_lists(state))
    original = state.store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0]
    state.hold_lists = True
    state.page.evaluate('() => { void loadTestReports(); void loadTestReports(); void loadTestReports(); }')
    calls = _wait(state, before + 1)
    playwright.expect(state.page.locator('#refreshTestReportsBtn')).to_be_disabled()
    _release(calls[-1])
    playwright.expect(state.page.locator('#refreshTestReportsBtn')).to_be_enabled()
    playwright.expect(state.page.locator('#testReportsFeed .report-card')).to_have_count(2)
    assert state.store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == original
    assert not any(call['method'] == 'POST' and call['path'] != '/admin/api/auth/login' for call in state.calls)
    assert not state.errors and not state.external


@pytest.mark.parametrize('older_status', [None, 500], ids=['old-success', 'old-failure'])
def test_late_report_search_cannot_replace_latest_query_or_error(report_page, older_status):
    state = report_page
    _open(state)
    before = len(_lists(state))
    state.hold_lists = True
    state.page.locator('#reportSearchInput').fill('Alpha')
    state.page.locator('#reportSearchBtn').click()
    old = _wait(state, before + 1)[-1]
    state.page.locator('#reportSearchInput').fill('Beta')
    state.page.locator('#reportSearchBtn').click()
    newest = _wait(state, before + 2)[-1]
    _release(newest)
    playwright.expect(state.page.locator('#testReportsFeed')).to_contain_text('Beta stored document')
    _release(old, older_status)
    state.page.wait_for_timeout(50)
    playwright.expect(state.page.locator('#testReportsFeed')).to_contain_text('Beta stored document')
    playwright.expect(state.page.locator('#testReportsFeed')).not_to_contain_text('Alpha stored document')
    playwright.expect(state.page.locator('#reportSearchInput')).to_have_value('Beta')
    assert not state.errors and not state.external


def test_missing_measurements_never_become_success_grade_a_http_200_or_310ms(report_page):
    state = report_page
    _open(state)
    playwright.expect(state.page.locator('#kpiReportTotal')).to_have_text('2')
    playwright.expect(state.page.locator('#kpiReportSuccessRate')).to_have_text('—')
    playwright.expect(state.page.locator('#kpiReportAvgLatency')).to_have_text('—')
    playwright.expect(state.page.locator('#testReportsCountScope')).to_contain_text('보고서 2건')
    assert state.page.locator('#testReportsFeed').get_by_text('기록 문서 · 현재 실측 근거 미확인', exact=True).count() == 2
    state.page.locator(f'.open-report-btn[data-id="{state.ids[0]}"]').click()
    playwright.expect(state.page.locator('#repModalGradeBadge')).to_have_text('등급 기재 없음')
    playwright.expect(state.page.locator('#repModalStatusBadge')).to_have_text('HTTP 기재 없음')
    playwright.expect(state.page.locator('#repModalLatencyBadge')).to_have_text('지연시간 기재 없음')
    playwright.expect(state.page.locator('#repModalEvidenceBadge')).to_contain_text('기록 문서 · 현재 실측 근거 미확인')
    state.page.locator('#closeReportModalBtn').click()
    state.page.locator('#reportSearchInput').fill('No matching history')
    state.page.locator('#reportSearchBtn').click()
    playwright.expect(state.page.locator('#testReportsFeed .report-card')).to_have_count(0)
    playwright.expect(state.page.locator('#kpiReportSuccessRate')).to_have_text('—')
    playwright.expect(state.page.locator('#kpiReportAvgLatency')).to_have_text('—')
    assert not state.errors and not state.external


def test_detail_double_open_is_single_flight_and_close_blocks_late_render(report_page):
    state = report_page
    _open(state)
    state.hold_details = True
    state.page.evaluate('id => { void openTestReportModal(id); void openTestReportModal(id); }', state.ids[0])
    old = _wait(state, 1, details=True)[0]
    state.page.evaluate('id => { void openTestReportModal(id); }', state.ids[1])
    current = _wait(state, 2, details=True)[1]
    _release(current)
    playwright.expect(state.page.locator('#repModalTitle')).to_have_text('Beta stored document')
    _release(old)
    state.page.wait_for_timeout(50)
    playwright.expect(state.page.locator('#repModalTitle')).to_have_text('Beta stored document')
    state.page.locator('#closeReportModalBtn').click()
    state.page.evaluate('id => { void openTestReportModal(id); }', state.ids[0])
    late = _wait(state, 3, details=True)[2]
    state.page.evaluate('closeTestReportModal()')
    _release(late)
    state.page.wait_for_timeout(50)
    playwright.expect(state.page.locator('#testReportModal')).not_to_be_visible()
    assert state.page.evaluate('currentSelectedReport') is None
    assert not state.errors and not state.external


def test_measured_badge_and_kpis_use_backend_evidence_flag_only(report_page):
    state = report_page
    resource_id = state.store.upsert_resource({'key': 'measured-admin-fixture', 'source': 'fixture',
        'kind': 'mcp', 'name': 'Measured fixture', 'url': 'https://measured-admin.example/mcp',
        'description': 'Read documentation in an isolated fixture', 'category': 'dev_tools', 'price_usdc': 0})
    tools = json.dumps([{'name': 'read_docs', 'inputSchema': {'type': 'object'}}])
    with state.store.tx() as db:
        db.execute("UPDATE resources SET active=1,health_status='healthy',usage_tools=?,usage_full_tools=?,usage_guide=? WHERE id=?",
                   (tools, tools, json.dumps({'tools': json.loads(tools)}), resource_id))
    identity = execution_report(state.store, resource_id, time.time() - 1,
        title='Measured fixture report', slug='measured-admin-report', status_code=200, latency_ms=42)
    state.page.locator('[data-tab="test_reports"]').click()
    playwright.expect(state.page.locator('#testReportsFeed .report-card')).to_have_count(3)
    card = state.page.locator(f'.report-card[data-report-id="{identity}"]')
    playwright.expect(card).to_contain_text('실측 실행 근거 확인')
    playwright.expect(state.page.locator('#kpiReportSuccessRate')).to_have_text('100.0%')
    playwright.expect(state.page.locator('#kpiReportAvgLatency')).to_have_text('42ms')
    assert not state.errors and not state.external


def test_malformed_legacy_grade_and_kind_stay_inert_in_report_cards(report_page):
    state = report_page
    # Existing imported history can contain malformed display fields. This
    # isolated fixture tests rendering without weakening the creation API.
    with state.store.tx() as db:
        db.execute('UPDATE agent_test_reports SET kind=?,title=?,eval_grade=?,eval_score=? WHERE id=?',
                   ('mcp" onmouseover="alert(1)', '<img src=x onerror=alert(1)>', 'A', 'not-a-score', state.ids[0]))
    state.page.locator('[data-tab="test_reports"]').click()
    playwright.expect(state.page.locator('#testReportsFeed .report-card')).to_have_count(2)
    card = state.page.locator(f'.report-card[data-report-id="{state.ids[0]}"]')
    playwright.expect(card).to_contain_text('UNKNOWN')
    playwright.expect(card).to_contain_text('<img src=x onerror=alert(1)>')
    assert card.locator('img,script,[onmouseover],[onerror]').count() == 0
    assert not state.errors and not state.external
