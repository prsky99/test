"""Dashboard truthfulness and independent-menu recovery in real Chromium."""
# ruff: noqa: F401,F811
from pathlib import Path

from playwright.sync_api import expect
from tests.test_admin_security_browser import admin_page
from tests.test_front_workflow_browser import browser

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def test_current_metrics_render_and_unavailable_index_is_not_reported_complete(admin_page):
    page, errors, external = admin_page
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    page.evaluate('''() => {
      clearTimeout(state.timer);
      const data=structuredClone(state.overview);
      data.resources=[{kind:'a2a',active:1,status:'healthy',n:900}];
      data.surveys.verified_working=777;
      data.public_catalog={cataloged:3,reachable:1,with_status_check:2,
        by_protocol:[{kind:'a2a',n:1},{kind:'mcp',n:1},{kind:'x402',n:1}],
        execution_24h:{completed:2,succeeded:1,failed:0,unknown:1,successful_resources:1}};
      data.rag={available:false,pct:null};
      Object.assign(data.health,{interval:21600,checks_2h:100,ok_2h:100,overdue_2h:200,
        checks_6h:9,ok_6h:8,overdue_6h:4});
      renderOverview(data);
    }''')
    expect(page.locator('#kpis .kpi').filter(has_text='공개 카탈로그').locator('.value')).to_have_text('3')
    expect(page.locator('#kpis .kpi').filter(has_text='실행 점검').locator('.value')).to_have_text('2')
    summary = page.locator('#overviewSearchVerifyBox')
    expect(summary).to_contain_text('통계를 일시적으로 조회할 수 없습니다')
    assert '100.0% 완료' not in summary.inner_text()
    assert '777' not in summary.inner_text()
    assert '900' not in page.locator('#kindStatus').inner_text()
    expect(page.locator('#overviewLaneStatus')).to_contain_text('수집기 없음')
    expect(page.locator('#kpis .kpi').filter(has_text='기본 헬스체크 주기').locator('.value')).to_have_text('6시간')
    expect(page.locator('#kpis .kpi').filter(has_text='최근 6시간 점검').locator('.value')).to_have_text('9')
    expect(page.locator('#kpis .kpi').filter(has_text='예정 시각보다 6시간 지연').locator('.value')).to_have_text('4')
    assert '2시간' not in page.locator('#kpis').inner_text()
    expect(page.locator('#overviewLanesBox')).to_contain_text('21,600초')
    assert summary.locator('.stack > span').evaluate('(e) => e.style.width') == '0%'
    folder = Path('reports/admin-current-alignment-2026-10-21')
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / 'overview-degraded-index.png'), full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.screenshot(path='reports/health-cadence-2026-10-23/overview-six-hour.png', full_page=False)
    assert not errors and not external


def test_agents_menu_opens_without_overview_and_renders_hostile_names_as_text(admin_page):
    page, errors, external = admin_page
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    page.evaluate('''() => {clearTimeout(state.timer);state.overview=null;invalidateAdminReads();}''')
    overview_reads = []
    def fail_overview(route):
        overview_reads.append(1)
        route.fulfill(status=503, content_type='application/json', body='{"detail":"Unavailable"}')
    page.route('**/admin/api/overview', fail_overview)
    page.locator('[data-tab="agents"]').click()
    expect(page.locator('[data-panel="agents"]')).to_be_visible()
    page.wait_for_function('() => !refreshInFlight')
    assert not overview_reads
    assert page.evaluate('state.overview===null')
    page.evaluate('''() => renderAgents({total:1,items:[{id:1,kind:'mcp',source:'fixture',
      name:'<img src=x onerror=alert(1)>',url:'https://fixture.example',category:'docs_knowledge',
      health_status:'unknown',active:1}]})''')
    assert page.locator('#agentTable img, #agentTable script').count() == 0
    expect(page.locator('#agentTable')).to_contain_text('<img src=x onerror=alert(1)>')
    assert not errors and not external
