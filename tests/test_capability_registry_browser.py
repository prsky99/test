"""Current connection evidence stays private and readable in real browser dialogs."""
import time

from playwright.sync_api import expect

from agent_market.capability_registry import Registry
from tests.test_operational_observability_browser import trace_page
from tests.test_front_workflow_browser import browser
from tests.test_single_agent_chat_browser import chat_page
from tests.test_fast_single_recommendation import catalog


def test_admin_version_evidence_dialog_is_centered_and_survives_refresh(trace_page):
    page,store,_,errors,external=trace_page
    rid=store.upsert_resource({'key':'verified','kind':'a2a','source':'fixture','url':'https://agent.example/a2a','name':'Verified Agent','description':'Search','category':'other','networks':[]})
    with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',last_ok_at=?,auth_observed=0 WHERE id=?",(time.time(),rid))
    registry=Registry(store);now=time.time();registry.record(registry.current(rid),scope='execution',outcome='succeeded',started=now,finished=now)
    page.locator('[data-tab="errors"]').click();page.locator('#connectionResourceId').fill(str(rid));page.locator('#connectionInspect').click()
    dialog=page.locator('#observationDialog');expect(dialog).to_be_visible()
    expect(page.locator('#observationDetail')).to_contain_text('Verified callable: true')
    expect(page.locator('#observationDetail')).to_contain_text('succeeded')
    box=dialog.bounding_box();viewport=page.viewport_size
    assert abs(box['y']+box['height']/2-viewport['height']/2)<5
    page.evaluate('() => loadErrors()');expect(dialog).to_be_visible()
    page.screenshot(path='reports/advancement-r03-2026-10-18/admin-connection-evidence.png')
    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
    assert not errors and not external


def test_public_drawer_shows_fixed_verification_copy_without_private_reason(chat_page):
    page,_,_,errors,_=chat_page;page.goto('https://agentconcierge.biz/#explore')
    reject=page.get_by_role('button',name='Reject Non-Essential',exact=True)
    if reject.is_visible():reject.click()  # the fixture may have stored consent already
    page.evaluate("""() => renderDrawerAgent({id:1,kind:'a2a',name:'Verification example',connection_readiness:{profile_available:true,verified_callable:false,reason:'<img src=x onerror=alert(1)> private-system-detail'}},'live')""")
    expect(page.locator('#drawerContent')).to_contain_text('Connection available; current verification pending')
    page.evaluate("""() => {document.getElementById('drawer').classList.remove('hidden');document.getElementById('drawerBackdrop').classList.remove('hidden');}""")
    expect(page.locator('#drawer')).to_be_visible()
    assert 'private-system-detail' not in page.locator('#drawerContent').inner_text()
    assert page.locator('#drawerContent img').count()==0
    page.screenshot(path='reports/advancement-r03-2026-10-18/public-connection-verification.png')
    assert not errors
