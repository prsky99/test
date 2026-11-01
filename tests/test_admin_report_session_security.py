"""Private report content is removed when the authenticated browser session changes."""
import json

from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_admin_report_read_browser import (report_page, _open, _wait, _release)  # noqa: F401


def test_session_change_closes_and_clears_already_rendered_private_report(report_page):
    state=report_page
    marker='Private report body and wire fixture'
    with state.store.tx()as db:
        db.execute('UPDATE agent_test_reports SET content_md=?,input_wire=?,output_wire=? WHERE id=?',
            (marker,json.dumps({'private':marker}),json.dumps({'result':marker}),state.ids[0]))
    _open(state)
    state.page.locator(f'.open-report-btn[data-id="{state.ids[0]}"]').click()
    state.page.wait_for_function('() => currentSelectedReport !== null')
    assert marker in state.page.locator('#repModalContent').inner_text()
    state.page.evaluate("() => { token = ''; currentUser = null; updateUserUI(null, false); }")
    assert not state.page.locator('#testReportModal').is_visible()
    assert state.page.evaluate('currentSelectedReport')is None
    for identity in('repModalContent','repModalInputWire','repModalOutputWire'):
        assert marker not in state.page.locator('#'+identity).text_content()
    assert state.page.evaluate('testReportsCache.length')==0
    assert 'Alpha stored document'not in state.page.locator('#testReportsFeed').text_content()
    assert not state.errors and not state.external


def test_old_session_detail_response_cannot_reopen_or_repopulate_report(report_page):
    state=report_page
    _open(state);state.hold_details=True
    state.page.evaluate('id => void openTestReportModal(id)',state.ids[0])
    held=_wait(state,1,details=True)[0]
    state.page.evaluate("() => { token = ''; currentUser = null; updateUserUI(null, false); }")
    _release(held)
    state.page.wait_for_timeout(50)
    assert not state.page.locator('#testReportModal').is_visible()
    assert state.page.evaluate('currentSelectedReport')is None
    assert 'Alpha stored document'not in state.page.locator('#repModalContent').text_content()
    assert not state.errors and not state.external
