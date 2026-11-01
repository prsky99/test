"""The first authenticated workspace view must finish current scoped reads.

Every browser request uses the existing disposable TestClient fixture. Neither
overview navigation nor forced visibility may bypass session readiness.
"""
import json
from pathlib import Path

from playwright.sync_api import expect
import pytest

from agent_market.gateway import admin_auth
from tests.test_front_workflow_browser import browser
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_execution_browser import private_page


def launch(w, person='owner'):
    w.page.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(w.headers[person]['Authorization'][7:])+');')
    w.page.goto('https://admin.test/admin/ui#workspaces')


def clean(w):
    assert not w.errors and not w.external and not w.calls


@pytest.mark.parametrize('person', ['owner', 'editor', 'viewer', 'operator'])
def test_direct_workspace_first_page_is_visible_only_after_current_scope_load_and_does_not_poll(private_page, person):
    w = private_page
    launch(w, person)
    expect(w.page.locator('main')).to_be_visible()
    expect(w.page.locator('#workspacePanel')).to_be_visible()
    expect(w.page.locator('#workspaceSelect')).to_be_enabled()
    expect(w.page.locator('#adminLoginModal')).to_be_hidden()
    assert w.page.evaluate('adminSessionReady && Boolean(currentUser) && state.tab==="workspaces"')
    assert not any(path == '/admin/api/overview' for _, path, _ in w.requests)
    w.page.locator('#workspaceSelect').select_option(w.ws['id'])
    expect(w.page.locator('#workspaceSummary')).to_contain_text(w.ws['name'])
    assert w.page.locator('#workspaceDraftCreate').is_enabled() == (person in ('owner', 'editor'))
    assert w.page.locator('#workspaceMembers').is_enabled() == (person == 'owner')
    reads = [path for method, path, _ in w.requests if method == 'GET' and '/workflow-workspaces' in path]
    w.page.clock.install()
    w.page.clock.fast_forward(65000)
    assert [path for method, path, _ in w.requests if method == 'GET' and '/workflow-workspaces' in path] == reads
    assert w.page.evaluate('state.timer===null && !canAutoRefresh()')
    if person == 'owner':
        folder = Path('reports/advancement-rnd-source-2026-10-19/research')
        w.page.set_viewport_size({'width': 1440, 'height': 1000})
        w.page.screenshot(path=str(folder/'workspace-initial-visibility-after.png'))
    clean(w)


@pytest.mark.parametrize('endpoint', ['/options', ''])
def test_initial_scoped_read_failure_never_marks_authenticated_workspace_ready(private_page, endpoint):
    w = private_page; failures = []
    def unavailable(route):
        failures.append(route.request.url)
        route.fulfill(status=503, content_type='application/json', body='{"detail":"Synthetic scoped read unavailable"}')
    w.page.route('**/admin/api/workflow-workspaces'+endpoint, unavailable)
    launch(w)
    expect(w.page.locator('#workspaceStatus')).to_contain_text('요청을 완료하지 못했습니다')
    expect(w.page.locator('main')).to_be_hidden()
    expect(w.page.locator('#workspaceSelect')).to_be_disabled()
    assert w.page.evaluate('!adminSessionReady && Boolean(currentUser)')
    assert len(failures) == 1
    clean(w)


def test_actual_revoked_session_reauthentication_clears_private_view_and_remains_hidden(private_page):
    w = private_page; launch(w)
    expect(w.page.locator('main')).to_be_visible()
    w.page.locator('#workspaceSelect').select_option(w.ws['id'])
    expect(w.page.locator('#workspaceSummary')).to_contain_text(w.ws['name'])
    with w.store.tx() as db:
        assert admin_auth.delete_session(db, w.headers['owner']['Authorization'][7:])
    assert w.page.evaluate('checkAdminAuth()') is False
    expect(w.page.locator('main')).to_be_hidden()
    expect(w.page.locator('#adminLoginModal')).to_be_visible()
    expect(w.page.locator('#workspaceSelect')).to_be_disabled()
    expect(w.page.locator('#workspaceDraftList')).to_be_empty()
    assert w.page.evaluate('!adminSessionReady && !token && currentUser===null')
    clean(w)


def test_late_old_session_workspace_read_cannot_show_new_session_or_private_rows(private_page):
    w = private_page; held = []
    def hold(route):
        response = w.client.get('/admin/api/workflow-workspaces', headers=route.request.headers)
        assert response.status_code == 200
        held.append((route, response))
        w.page.evaluate('window.__oldWorkspaceReadHeld=true')
    w.page.route('**/admin/api/workflow-workspaces', hold, times=1)
    launch(w)
    w.page.wait_for_function('() => window.__oldWorkspaceReadHeld===true')
    expect(w.page.locator('main')).to_be_hidden()
    w.page.evaluate('''() => {
      token='synthetic-unverified-next-session';currentUser={user_id:999,username:'unverified-next',role:'admin'};
      updateUserUI(currentUser,false);
    }''')
    route, response = held[0]
    route.fulfill(status=200, content_type='application/json', body=response.content)
    w.page.wait_for_function('() => !refreshInFlight')
    expect(w.page.locator('main')).to_be_hidden()
    expect(w.page.locator('#workspaceSelect')).to_be_disabled()
    expect(w.page.locator('#workspaceDraftList')).to_be_empty()
    assert w.page.locator('#workspaceSelect option').count() == 1
    assert w.page.evaluate('!adminSessionReady && token==="synthetic-unverified-next-session" && currentUser.user_id===999')
    clean(w)
