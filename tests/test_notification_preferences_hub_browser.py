"""Real footer controls and authenticated Customer Requests rendering under CSP."""
from pathlib import Path

import pytest
from tests.test_footer_customer_requests_browser import journey, footer, admin_tab  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_task_updates_security import UpdateCourier
from tests.test_task_updates_security import updates  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_destination_verification import delivery  # noqa: F401
from tests.test_destination_verification_browser import (notification_page, review,
    push_to_worker, click_notification)  # noqa: F401

from tests.conftest import staff_session  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

pw = pytest.importorskip('playwright.sync_api')
REPORT = Path('reports/notification-preferences-2026-10-17')


def start(s, channel='poll', marketing=False):
    s.front.updates.courier = UpdateCourier()
    s.public.goto('https://agentconcierge.biz/#chat')
    s.public.locator('#chatInput').fill('weather forecast')
    s.public.locator('#chatSubmit').click()
    s.public.get_by_role('button',name='Get updates for this task').click()
    s.public.locator('#taskUpdateChannel').select_option(channel)
    if channel != 'poll':
        s.public.locator('#taskUpdateUrl').fill('https://inbox.example/private-preference-route')
    s.public.locator('#taskUpdateAuthority').check()
    s.public.locator('#taskUpdateConsent').check()
    if marketing:
        s.public.locator('#taskUpdateMarketing').check()
    s.public.locator('#taskUpdateSubmit').click()
    s.public.locator('#taskUpdateConfirmDestination').click()
    if channel == 'poll':
        pw.expect(s.public.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
        s.public.locator('#taskUpdateClose').click()
    else:
        pw.expect(s.public.locator('#taskUpdateVerify')).to_be_visible()
        # A reloaded page can recover an unfinished request through the footer.
        s.public.reload()
    footer(s,'cancellation')
    return s.store.query('SELECT id FROM agent_task_watches')[0]['id']


def open_admin_detail(s, wid, text):
    if s.admin.locator('#notificationDetail').count() and s.admin.locator('#notificationDetail').is_visible():
        s.admin.locator('#notificationDetailClose').click()
    admin_tab(s,'notifications')
    pw.expect(s.admin.locator('#notificationsTable')).to_contain_text(wid)
    s.admin.locator(f'[data-notification-id="{wid}"]').click()
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text(text)
    pw.expect(s.admin.locator('#notificationDetailId')).to_have_text(wid)


@pytest.mark.parametrize('width',[390,1280])
def test_pause_resume_renew_check_stop_delete_and_admin_history(journey,width):
    s = journey
    s.public.set_viewport_size({'width':width,'height':950})
    s.admin.set_viewport_size({'width':width,'height':950})
    wid = start(s)
    original = s.front.updates._get(wid)['expires']
    for label, front_status, admin_action in [
        ('Pause updates','Paused','일시정지'),('Resume updates','On','재개'),
        ('Renew for 90 days','On','90일 연장')]:
        s.public.get_by_role('button',name=label,exact=True).click()
        pw.expect(s.public.locator('#taskPreferences')).to_contain_text(front_status)
        open_admin_detail(s,wid,admin_action)
    assert s.front.updates._get(wid)['expires'] > original
    s.public.get_by_role('button',name='Check for updates',exact=True).click()
    pw.expect(s.public.get_by_role('button',name='No new verification changes.',exact=True)).to_be_visible()
    open_admin_detail(s,wid,'업데이트 수동 확인')
    s.public.get_by_role('button',name='Stop updates',exact=True).click()
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Stopped')
    open_admin_detail(s,wid,'중지')
    s.public.get_by_role('button',name='Delete notification data',exact=True).click()
    open_admin_detail(s,wid,'알림 데이터 삭제')
    pw.expect(s.admin.locator('#notificationHistory')).to_contain_text('일시정지')
    pw.expect(s.admin.locator('#notificationHistory')).to_contain_text('재개')
    pw.expect(s.admin.locator('#notificationHistory')).to_contain_text('90일 연장')
    assert s.admin.locator('#notificationDetail').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    assert not s.front.updates.courier.events
    REPORT.mkdir(parents=True,exist_ok=True)
    s.admin.screenshot(path=str(REPORT/f'admin-history-{width}.png'))


@pytest.mark.parametrize('channel',['webhook','a2a'])
def test_footer_endpoint_confirmation_marketing_withdrawal_and_admin_filters(journey,channel):
    s = journey
    wid = start(s,channel,marketing=True)
    open_admin_detail(s,wid,'주소 확인 대기')
    s.public.get_by_role('textbox',name='Verification code',exact=True).fill('0000000')
    # The UI bounds a verification code to six characters and reports rejection.
    code = s.front.updates.courier.challenges[-1]['verification_code']
    s.public.get_by_role('textbox',name='Verification code',exact=True).fill('000001' if code!='000001' else '000002')
    s.public.get_by_role('button',name='Confirm endpoint',exact=True).click()
    pw.expect(s.public.get_by_role('button',name='Check the code and try again.',exact=True)).to_be_visible()
    assert s.front.updates._get(wid)['state'] == 'pending_verification'
    s.public.get_by_role('textbox',name='Verification code',exact=True).fill(code)
    s.public.get_by_role('button',name='Check the code and try again.',exact=True).click()
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Destination verified.')
    open_admin_detail(s,wid,'주소 인증 완료')
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text('별도 동의 및 인증 완료')
    s.public.get_by_role('button',name='Withdraw marketing permission',exact=True).click()
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Marketing: Not enabled.')
    open_admin_detail(s,wid,'광고 동의 철회')
    assert s.front.updates._get(wid)['state'] == 'active'
    assert 'private-preference-route' not in s.admin.locator('#notificationDetail').inner_text()
    s.admin.locator('#notificationDetailClose').click()
    with s.admin.expect_response('**/admin/api/needs/notifications?*state=active*'):
        s.admin.locator('#notificationState').select_option('active')
    with s.admin.expect_response('**/admin/api/needs/notifications?*channel='+channel+'*'):
        s.admin.locator('#notificationChannel').select_option(channel)
    with s.admin.expect_response('**/admin/api/needs/notifications?q=*'):
        s.admin.locator('#notificationSearch').fill(wid)
    pw.expect(s.admin.locator('#notificationsTable')).to_contain_text(wid)
    s.admin.reload()
    open_admin_detail(s,wid,'광고 동의 철회')
    assert not s.front.updates.courier.events
    REPORT.mkdir(parents=True,exist_ok=True)
    s.admin.screenshot(path=str(REPORT/f'admin-verified-{channel}.png'))


@pytest.mark.parametrize('channel',['webhook','a2a'])
def test_decline_pending_footer_request_removes_admin_row(journey,channel):
    s = journey
    wid = start(s,channel,marketing=True)
    open_admin_detail(s,wid,'주소 확인 대기')
    s.public.get_by_role('button',name='Decline and delete request',exact=True).click()
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('No task updates have been requested')
    s.admin.locator('#notificationDetailRefresh').click()
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text('삭제되었거나')
    s.admin.locator('#notificationDetailClose').click()
    with s.admin.expect_response('**/admin/api/needs/notifications?*'):
        s.admin.locator('#btnRefreshNeedsHub').click()
    pw.expect(s.admin.locator('#notificationsTable')).not_to_contain_text(wid)
    pw.expect(s.admin.locator('#notificationDetail')).to_be_hidden()
    assert not s.store.query('SELECT 1 FROM agent_task_permissions WHERE watch_id=?',(wid,))
    assert s.admin_client.get('/admin/api/needs/notifications/'+wid,
        headers=staff_session(s.store)).status_code == 404


def test_empty_preferences_and_failed_action_preserve_truthful_state(journey):
    s = journey
    footer(s,'cancellation')
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Start a conversation')
    s.public.keyboard.press('Escape')
    wid = start(s)
    s.fail_paths.add('/api/task-updates/'+wid+'/action')
    s.public.get_by_role('button',name='Pause updates',exact=True).click()
    pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Unable to complete this request')
    assert s.front.updates._get(wid)['state'] == 'active'
    open_admin_detail(s,wid,'활성')
    pw.expect(s.admin.locator('#notificationHistory')).not_to_contain_text('일시정지')


def test_notification_labels_and_history_are_escaped_and_list_failure_preserves_dialog(journey):
    s = journey
    wid = start(s)
    attack = '<img src=x onerror="window.__notificationXss=1">'
    with s.store.tx() as db:
        db.execute('UPDATE agent_task_watches SET task=? WHERE id=?',(attack,wid))
    open_admin_detail(s,wid,attack)
    assert s.admin.locator('#notificationDetail img').count() == 0
    assert s.admin.evaluate('window.__notificationXss || 0') == 0
    s.fail_paths.add('/admin/api/needs/notifications')
    s.admin.evaluate('loadNotificationPreferences()')
    pw.expect(s.admin.locator('#notificationsTable')).to_contain_text('불러오지 못했습니다')
    pw.expect(s.admin.locator('#notificationDetail')).to_be_visible()
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text(attack)
    s.fail_paths.add('/admin/api/needs/notifications/'+wid)
    s.admin.locator('#notificationDetailRefresh').click()
    pw.expect(s.admin.locator('#notificationDetailBody')).to_contain_text('조회할 수 없습니다')
    pw.expect(s.admin.locator('#notificationDetail')).to_be_visible()


def test_admin_pagination_and_search_reach_records_beyond_first_page(journey):
    import time
    s = journey
    wid = start(s)
    now = time.time()
    with s.store.tx() as db:
        for number in range(50):
            db.execute('''INSERT INTO agent_task_watches (id,visitor_id,task,protocol,channel,state,created,expires,notice_version,authority)
                SELECT ?,visitor_id,?,protocol,channel,state,?,?,notice_version,authority FROM agent_task_watches WHERE id=?''',
                ('tw_'+f'{number:032x}',f'Page test {number}',now+number,now+10000,wid))
    admin_tab(s,'notifications')
    pw.expect(s.admin.locator('#notificationPage')).to_have_text('1–50 / 51')
    with s.admin.expect_response('**/admin/api/needs/notifications?*offset=50'):
        s.admin.locator('#notificationNext').click()
    pw.expect(s.admin.locator('#notificationPage')).to_have_text('51–51 / 51')
    pw.expect(s.admin.locator('#notificationsTable')).to_contain_text(wid)
    with s.admin.expect_response('**/admin/api/needs/notifications?*offset=0'):
        s.admin.locator('#notificationPrev').click()
    with s.admin.expect_response('**/admin/api/needs/notifications?q=*'):
        s.admin.locator('#notificationSearch').fill(wid)
    pw.expect(s.admin.locator('#notificationPage')).to_have_text('1–1 / 1')
    pw.expect(s.admin.locator('#notificationsTable')).to_contain_text(wid)


def test_manual_check_with_new_evidence_returns_to_chat_and_records_check(journey):
    import time
    s = journey
    wid = start(s)
    rid = s.store.query('SELECT id FROM resources')[0]['id']
    from tests.report_fixtures import execution_report
    at=time.time()
    execution_report(s.store,rid,at,title='New weather evidence',slug='weather-new-evidence',
        is_success=1,status_code=200,created_at=at)
    s.public.get_by_role('button',name='Check for updates',exact=True).click()
    pw.expect(s.public.locator('#legalModal')).to_be_hidden()
    pw.expect(s.public.locator('#chatMessages .chat-recommendation')).to_have_count(2)
    open_admin_detail(s,wid,'업데이트 수동 확인')
    pw.expect(s.admin.locator('#notificationDeliveries')).to_contain_text('ready')
    assert not s.front.updates.courier.events


@pytest.mark.parametrize('decision',['confirm','decline'])
def test_browser_push_confirmation_and_footer_actions_are_visible_to_admin(notification_page, tmp_path, decision):
    from unittest.mock import Mock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway.dashboard import dashboard_router

    page, context, origin, _, errors, env = notification_page
    store, front, _, _, _, courier, _, _, push, _ = env
    app = FastAPI()
    app.include_router(dashboard_router(store,store._path,
        'native-browser-hub-test',None,front=front,ssl_manager=Mock(get_status=lambda:{})))
    auth = staff_session(store)
    endpoint = '/admin/api/needs/notifications'
    with TestClient(app) as admin:
        review(page,marketing=True)
        page.locator('#taskUpdateConfirmDestination').click()
        pw.expect(page.locator('#taskUpdateBrowserPending')).to_be_visible()
        wid = store.query('SELECT id FROM agent_task_watches')[0]['id']
        pending = admin.get(endpoint,headers=auth,params={'channel':'browser'}).json()['items'][0]
        assert pending['state']=='pending_verification' and not pending['destination_verified']
        if decision == 'decline':
            page.reload()
            page.locator('footer [data-doc="cancellation"]').click()
            page.get_by_role('button',name='Decline and delete request',exact=True).click()
            pw.expect(page.locator('#taskPreferences')).to_contain_text('No task updates have been requested')
            assert admin.get(endpoint+'/'+wid,headers=auth).status_code == 404
            assert admin.get(endpoint,headers=auth).json()['summary']['total'] == 0
        else:
            click_notification(push_to_worker(context,push.sent[-1][1]))
            pw.expect(page.locator('#taskUpdateStatus')).to_have_text('Browser notifications are verified and on.')
            page.locator('#taskUpdateManage').click()
            for label, state, recorded in [
                ('Pause updates','paused','pause'),('Resume updates','active','resume'),
                ('Withdraw marketing permission','active','withdrawn'),('Stop updates','revoked','stop')]:
                with page.expect_response('**/api/task-updates/'+wid+'/action'):
                    page.get_by_role('button',name=label,exact=True).click()
                result = admin.get(endpoint+'/'+wid,headers=auth).json()
                assert result['item']['state'] == state
                assert any(r['action']==recorded for r in result['history'])
            assert not result['item']['marketing_eligible']
            assert 'sealed' not in str(result) and 'subscription' not in str(result)
        assert not courier.events and not errors
