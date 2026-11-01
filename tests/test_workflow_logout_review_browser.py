"""A confirmed logout must invalidate every pending workflow export immediately."""
import pytest
from tests.browser_wait import pending_request
from playwright.sync_api import expect

from agent_market.admin_workflow_webapp_v12 import build_admin_package_v12
from tests.test_admin_webapp_v12_browser import (
    browser, routing, v12_api, v12_runtime, v12_page,
    enter_export, open_review, prepare_review,
)
from tests.test_workflow_apps_v12 import export_request
from tests.test_workflow_runtime_browser import studio, login
from agent_market.admin_workflow_webapp import build_admin_package
from agent_market.workflow_apps import service_for as workflow_apps_for
from agent_market.workflow_webapp import export_config


def test_confirmed_logout_blocks_v12_download_before_logout_response(v12_page):
    page, runtime, workflow, service, calls, errors, external, _ = v12_page
    enter_export(page, workflow)
    open_review(page)
    prepare_review(page)
    page.locator('#appV12Authority').check()
    pending_exports, pending_logouts, downloads = [], [], []
    page.route('**/export-app-v12/package', lambda route: pending_exports.append(route))
    page.route('**/admin/api/auth/logout', lambda route: pending_logouts.append(route))
    page.on('download', lambda download: downloads.append(download))
    page.evaluate('''() => {
      globalThis.__reviewExportSettled = false;
      globalThis.__reviewBlobCount = 0;
      const originalDownload = downloadV12Export;
      downloadV12Export = async (...args) => {
        try { return await originalDownload(...args); }
        finally { globalThis.__reviewExportSettled = true; }
      };
      const originalCreate = URL.createObjectURL.bind(URL);
      URL.createObjectURL = (...args) => {
        globalThis.__reviewBlobCount++;
        return originalCreate(...args);
      };
    }''')
    page.locator('#appV12Zip').click()
    pending_request(page,pending_exports)
    page.on('dialog', lambda dialog: dialog.accept())
    # A DOM click returns immediately; awaiting logoutAdmin() would hide this race.
    page.evaluate('document.getElementById("logoutBtn").click()')
    page.wait_for_function('() => globalThis.__reviewExportSettled === false')
    pending_request(page,pending_logouts)
    result = service.export_admin(workflow['id'], export_request(service, workflow), 1)
    package, _ = build_admin_package_v12(result['config'], result['deployment'])
    try:
        pending_exports[0].fulfill(status=200, content_type='application/zip', body=package)
        page.wait_for_function('() => globalThis.__reviewExportSettled === true')
        observed = {
            'blob_count': page.evaluate('globalThis.__reviewBlobCount'),
            'downloads': len(downloads),
            'logout_response_still_pending': True,
        }
    finally:
        pending_logouts[0].fulfill(status=200, content_type='application/json', body='{"ok":true}')
        expect(page.locator('#adminLoginModal')).to_be_visible()
    assert observed == {
        'blob_count': 0, 'downloads': 0, 'logout_response_still_pending': True,
    }, observed
    assert not calls and not errors and not external


def assert_no_late_v11_download(studio, action):
    page, identity, front, errors, _ = studio
    login(page)
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}', identity)
    page.locator('#btnExportAppFromCanvas').click()
    expect(page.locator('#workflowAppExportModal')).to_be_visible()
    pending_exports, pending_logouts, downloads = [], [], []
    page.route('**/export-app/package', lambda route: pending_exports.append(route))
    def hold_logout(route):
        pending_logouts.append(route)
        page.evaluate('globalThis.__legacyLogoutHeld=true')
    page.route('**/admin/api/auth/logout', hold_logout)
    page.on('download', lambda download: downloads.append(download))
    page.evaluate('''() => {
      globalThis.__legacyExportSettled = false;
      globalThis.__legacyBlobCount = 0;
      const originalDownload = downloadAdminWorkflowApp;
      downloadAdminWorkflowApp = async (...args) => {
        try { return await originalDownload(...args); }
        finally { globalThis.__legacyExportSettled = true; }
      };
      const originalCreate = URL.createObjectURL.bind(URL);
      URL.createObjectURL = (...args) => {
        globalThis.__legacyBlobCount++;
        return originalCreate(...args);
      };
    }''')
    page.locator('#btnDownloadStandaloneApp').click()
    pending_request(page,pending_exports)
    if action == 'logout':
        page.on('dialog', lambda dialog: dialog.accept())
        page.evaluate('document.getElementById("logoutBtn").click()')
        page.wait_for_function('()=>globalThis.__legacyLogoutHeld===true')
        pending_request(page,pending_logouts)
    elif action == 'close': page.locator('#closeAppExportBtn').click()
    elif action == 'selection': page.evaluate('(id)=>selectWorkflow(id)', identity)
    elif action == 'role': page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    else: page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    deployment = workflow_apps_for(front.store, front.workflows).create(identity, {})
    package, _ = build_admin_package(export_config(front.store.get_workflow(identity)), deployment)
    try:
        pending_exports[0].fulfill(status=200, content_type='application/zip', body=package)
        page.wait_for_function('() => globalThis.__legacyExportSettled === true')
        observed = {'blob_count': page.evaluate('globalThis.__legacyBlobCount'), 'downloads': len(downloads)}
    finally:
        if pending_logouts:
            pending_logouts[0].fulfill(status=200, content_type='application/json', body='{"ok":true}')
            expect(page.locator('#adminLoginModal')).to_be_visible()
    assert observed == {'blob_count': 0, 'downloads': 0}, observed
    assert not errors


def test_confirmed_logout_blocks_v11_download_before_logout_response(studio):
    assert_no_late_v11_download(studio, 'logout')


@pytest.mark.parametrize('action', ['close', 'selection', 'role', 'token'])
def test_v11_late_download_cannot_outlive_review_context(studio, action):
    assert_no_late_v11_download(studio, action)
