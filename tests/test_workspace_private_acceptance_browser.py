"""Actual desktop dashboard buttons open current private APIs in Chromium.

The existing full-dashboard fixture routes every request into a disposable
TestClient. No project listener or external integration is contacted.
"""
from pathlib import Path

from playwright.sync_api import expect

from agent_market.gateway import admin_auth
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_workspace_browser import (workspace_browser, sign_in, make_space,
                                        make_draft, select_space)  # noqa: F401


VIEWS = (
    ('workspaceReliability', 'workspaceReliabilityDialog', 'Private evaluation contracts loaded.', 'Close evaluation evidence'),
    ('workspaceReliabilityControls', 'workspaceReliabilityControlsDialog', 'Current private controls loaded.', 'Close reliability controls'),
    ('workspaceGrowth', 'workspaceGrowthDialog', 'Current private state loaded.', 'Close app tools'),
    ('workspaceMachineUpdates', 'workspaceMachineUpdatesDialog', 'Current private machine update state loaded.', 'Close machine updates'),
)


def test_all_current_feature_buttons_open_native_centered_dialogs_and_survive_refresh(workspace_browser):
    w = workspace_browser
    w.page.set_viewport_size({'width': 1440, 'height': 1000})
    w.page.clock.install()
    ws = make_space(w)
    make_draft(w, ws)
    sign_in(w)
    select_space(w, ws)
    for button, identity, loaded, close in VIEWS:
        w.page.locator('#' + button).click()
        dialog = w.page.locator('#' + identity)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text(loaded)
        assert dialog.evaluate('(element) => element.matches(":modal")')
        box = dialog.bounding_box()
        assert abs(box['x'] + box['width'] / 2 - 720) < 2
        assert abs(box['y'] + box['height'] / 2 - 500) < 2
        assert dialog.get_attribute('aria-labelledby')
        assert dialog.locator('input[type="checkbox"]:checked').count() == 0
        if button == 'workspaceReliabilityControls':
            expect(dialog.get_by_role('button', name='Activate evaluation worker', exact=True)).to_be_disabled()
        if button == 'workspaceMachineUpdates':
            expect(dialog.get_by_role('button', name='Activate private receiver', exact=True)).to_be_disabled()
        w.page.clock.fast_forward(11000)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text(loaded)
        dialog.get_by_role('button', name=close, exact=True).click()
        expect(dialog).to_have_count(0)
    folder = Path('reports/advancement-phase2-integration-2026-10-19/acceptance')
    folder.mkdir(parents=True, exist_ok=True)
    w.page.screenshot(path=str(folder / 'full-dashboard-private-tools.png'), full_page=True)
    assert not [request for request in w.requests if request[0] != 'GET']
    assert not w.errors and not w.external


def test_actual_session_revocation_clears_machine_dialog_and_disables_workspace_actions(workspace_browser):
    w = workspace_browser
    ws = make_space(w)
    make_draft(w, ws)
    sign_in(w)
    select_space(w, ws)
    w.page.locator('#workspaceMachineUpdates').click()
    dialog = w.page.locator('#workspaceMachineUpdatesDialog')
    expect(dialog).to_contain_text('Current private machine update state loaded.')
    with w.store.tx() as db:
        assert admin_auth.delete_session(db, w.headers['owner']['Authorization'][7:])
    dialog.get_by_role('button', name='Read current state', exact=True).click()
    expect(dialog).to_have_count(0)
    for button, _, _, _ in VIEWS:
        expect(w.page.locator('#' + button)).to_be_disabled()
    assert not [request for request in w.requests if request[0] != 'GET']
    assert not w.errors and not w.external
