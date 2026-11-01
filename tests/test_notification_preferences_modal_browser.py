"""Centered modal, timer refresh persistence, focus and in-flight request boundaries."""
from pathlib import Path

import pytest
from tests.test_footer_customer_requests_browser import journey, admin_tab  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_notification_preferences_hub_browser import start, open_admin_detail

# Imported fixtures do not inherit their defining module's fixture marks.
# Rotation enforcement is exercised separately by the authentication regression.
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

pw = pytest.importorskip('playwright.sync_api')
REPORT = Path('reports/notification-preferences-modal-2026-10-17')


@pytest.mark.parametrize('width',[390,1280])
def test_centered_modal_survives_two_real_timer_cycles_with_scroll_and_focus(journey,width):
    s = journey
    s.admin.set_viewport_size({'width':width,'height':850})
    s.admin.clock.install()
    wid = start(s)
    open_admin_detail(s,wid,'활성')
    page = s.admin
    page.bring_to_front()
    dialog = page.get_by_role('dialog',name='알림 설정 상세 및 이력')
    pw.expect(dialog).to_be_visible()
    assert dialog.evaluate('(el)=>el.matches(":modal")')
    assert dialog.evaluate('(el)=>el.parentElement===document.body')
    box = dialog.bounding_box()
    assert abs(box['x']+box['width']/2-width/2) < 2
    assert abs(box['y']+box['height']/2-850/2) < 2
    assert box['x']>=0 and box['y']>=0 and box['x']+box['width']<=width
    assert dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    assert page.locator('#notificationDetailBody').evaluate('(el)=>el.scrollHeight<=el.clientHeight || getComputedStyle(el).overflowY==="auto"')
    body = page.locator('#notificationDetailBody')
    body.evaluate('(el)=>el.scrollTop=180')
    position = body.evaluate('(el)=>el.scrollTop')
    before = body.inner_html()
    page.locator('#notificationDetailRefresh').focus()
    for _ in range(2):
        with page.expect_response('**/admin/api/needs/notifications?*'):
            page.clock.fast_forward(10001)
        pw.expect(dialog).to_be_visible()
        pw.expect(page.locator('#notificationDetailId')).to_have_text(wid)
        assert body.inner_html() == before
        assert body.evaluate('(el)=>el.scrollTop') == position
        pw.expect(page.locator('#notificationDetailRefresh')).to_be_focused()
    assert len([path for method,path in s.requests if method=='GET' and path=='/admin/api/needs/notifications/'+wid]) == 1
    # Keyboard focus remains within the native modal, while list buttons are inert.
    for _ in range(4):
        page.keyboard.press('Tab')
        assert dialog.evaluate('(el)=>el.contains(document.activeElement) || document.activeElement===document.body')
    REPORT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(REPORT/f'centered-{width}.png'))
    page.keyboard.press('Escape')
    pw.expect(dialog).to_be_hidden()
    assert page.evaluate('document.activeElement.dataset.notificationId') == wid


def test_explicit_modal_refresh_updates_same_request_without_disrupting_scroll(journey):
    s = journey
    wid = start(s)
    open_admin_detail(s,wid,'활성')
    s.front.updates.action(s.front.updates._get(wid)['visitor_id'],wid,'pause')
    body = s.admin.locator('#notificationDetailBody')
    body.evaluate('(el)=>el.scrollTop=100')
    position = body.evaluate('(el)=>el.scrollTop')
    s.admin.locator('#notificationDetailRefresh').click()
    pw.expect(s.admin.locator('#notificationHistory')).to_contain_text('일시정지')
    pw.expect(s.admin.locator('#notificationDetail')).to_be_visible()
    assert body.evaluate('(el)=>el.scrollTop') == position
    pw.expect(s.admin.locator('#notificationDetailRefresh')).to_be_focused()
    s.admin.locator('#notificationDetailClose').click()
    pw.expect(s.admin.locator('#notificationDetail')).to_be_hidden()


def test_close_during_fetch_discards_late_response_and_supports_reopen_and_backdrop(journey):
    s = journey
    wid = start(s)
    admin_tab(s,'notifications')
    pending = []
    s.admin.route('**/admin/api/needs/notifications/'+wid,lambda route:pending.append(route))
    s.admin.locator(f'[data-notification-id="{wid}"]').click()
    pw.expect(s.admin.locator('#notificationDetail')).to_be_visible()
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text('불러오는 중')
    s.admin.locator('#notificationDetailClose').click()
    assert pending
    pending.pop().fulfill(status=200,content_type='application/json',body='{"item":{"id":"late"}}')
    pw.expect(s.admin.locator('#notificationDetail')).to_be_hidden()
    assert s.admin.locator('#notificationDetailBody').inner_text() == ''
    s.admin.unroute('**/admin/api/needs/notifications/'+wid)
    s.admin.locator(f'[data-notification-id="{wid}"]').click()
    pw.expect(s.admin.locator('#notificationDetailId')).to_have_text(wid)
    s.admin.mouse.click(2,2)
    pw.expect(s.admin.locator('#notificationDetail')).to_be_hidden()
