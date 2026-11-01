"""Actual Admin telemetry rendering and actions under the existing enforced CSP."""
import time

import pytest
from tests.test_admin_security_browser import admin_page
from tests.test_front_workflow_browser import browser

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def test_telemetry_controls_preserve_feedback_and_escape_task_attributes(admin_page):
    page, errors, external = admin_page
    task = 'image generation workflow " data-injected="yes <svg onload="window.auditXss=1">'
    state = {'open': False}
    writes = []

    def serve(route):
        request = route.request
        if request.method == 'POST':
            body = request.post_data_json
            writes.append(body)
            state['open'] = body['action'] == 'trip_circuit'
            route.fulfill(json={'ok': True, 'circuit_open': state['open'], 'history_preserved': True})
            return
        route.fulfill(json={'kpis': {'unmet_query_count': 27, 'unmet_queries_displayed': 15,
            'unmet_queries_pending_review': 7, 'catalog_matched_historical_count': 2,
            'outcomes_fail': 5, 'outcomes_ok': 20, 'circuit_open_count': int(state['open'])},
            'unmet_queries': [{'task': task, 'protocol': 'a2a', 'occurrences': 1, 'last_seen': time.time()}],
            'failing_agents': [{'resource_id': 1, 'name': 'Weather', 'kind': 'mcp', 'grade': 'A',
                'health_status': 'healthy', 'fail_count': 5, 'success_count': 20, 'fail_rate': 20,
                'circuit_open': state['open']}], 'source': 'live'})

    page.route('**/admin/api/agent-telemetry**', serve)
    page.locator('[data-tab="agent_telemetry"]').click()
    expect = pytest.importorskip('playwright.sync_api').expect
    expect(page.locator('#atUnmetTable')).to_contain_text('image generation workflow')
    assert page.locator('[data-injected], #atUnmetTable svg').count() == 0
    assert page.evaluate('window.auditXss || 0') == 0
    expect(page.locator('#atKpis')).to_contain_text('미해결 27유형')
    expect(page.locator('#atKpis')).to_contain_text('재확인 대기 7유형')
    page.locator('[data-fail-remediate="trip_circuit"]').click()
    expect(page.locator('[data-fail-remediate="reset_circuit"]')).to_be_visible()
    expect(page.locator('#atFailingTable')).to_contain_text('5건')
    page.locator('[data-fail-remediate="reset_circuit"]').click()
    expect(page.locator('[data-fail-remediate="trip_circuit"]')).to_be_visible()
    expect(page.locator('#atFailingTable')).to_contain_text('5건')
    page.locator('[data-unmet-resolve]').click()
    expect(page.locator('[data-unmet-resolve]')).to_be_enabled()
    assert writes[-1] == {'action': 'resolve_unmet', 'task': task, 'protocol': 'a2a'}
    assert not errors and not external
