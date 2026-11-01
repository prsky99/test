"""Real Chromium verification of the individual desk, escaping and scoped actions."""
from urllib.parse import urlsplit

import pytest
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_visitor_desk import desk, register, updates, catalog  # noqa: F401

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

playwright=pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('width',[390,1280])
def test_individual_desk_case_history_and_reviewed_delivery(browser,desk,width):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk)
    original=store.query('SELECT name FROM resources')[0]['name']
    add('New Current Weather',report_at=__import__('time').time())
    visitor=front.book.by_id(vid)
    request=front.book.add_message(visitor,'agent','rest','Review <img src=x onerror=alert(1)>',{'record_version':1,'protocol_mode':'any'})
    front.book.add_message(visitor,'concierge','rest','Saved response',{'record_version':1,'request_message_id':request,'recommendations':[{'name':'Untrusted <img src=x onerror=alert(1)>','kind':'mcp','grade':'A'}]})
    context=browser.new_context(viewport={'width':width,'height':950})
    requests=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='admin.test':route.abort();return
        requests.append((req.method,url.path,req.post_data))
        response=admin.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();page.on('dialog',lambda dialog:dialog.accept('Synthetic contact management reason'));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    playwright.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="visitors"]').click()
    assert page.locator('#vContact').input_value()=='registered'
    page.locator('tr[data-vid="'+vid+'"]').click()
    drawer=page.locator('#drawer')
    playwright.expect(drawer).to_contain_text(original)
    playwright.expect(drawer).not_to_contain_text('New Current Weather')
    playwright.expect(drawer).to_contain_text('https://inbox.example/…')
    assert 'private-routing-secret' not in drawer.inner_text()
    page.locator('#vCaseStatus').select_option('waiting')
    page.locator('#vCaseOwner').fill('Response team')
    page.locator('#vCaseNote').fill('<img src=x onerror=alert(1)> Confirm requested coverage')
    page.locator('#vCaseSave').click()
    playwright.expect(page.locator('#vCaseOwner')).to_have_value('Response team')
    playwright.expect(drawer).to_contain_text('Confirm requested coverage')
    assert not drawer.locator('img').count() and not courier.events
    page.locator('[data-watch-preview="'+wid+'"]').click()
    playwright.expect(page.locator('#vWatchPreview')).to_contain_text('New Current Weather')
    page.locator('#vWatchProcess').click()
    playwright.expect(page.locator('#vWatchResult')).to_contain_text('승인 대기에 등록되었습니다')
    assert not courier.events
    process=[r for r in requests if r[0]=='POST' and r[1].endswith('/process')]
    assert len(process)==1 and process[0][1].endswith('/'+wid+'/process')
    assert not any(r[1].endswith('/nurture/run') for r in requests)
    assert not page.locator('#btnRunNurtureBatch').count()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('#drawer').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    from pathlib import Path
    report=Path('reports/security-2026-10-17-visitor-desk');report.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(report/f'admin-visitor-{width}.png'))
    assert not errors
    context.close()


def test_admin_can_filter_and_inspect_verified_marketing_consent(browser,desk):
    from agent_market.concierge.task_updates import MARKETING_NOTICE
    store,front,client,add,headers,courier,data,vid,admin=desk
    body={**data,'channel':'webhook','url':'https://inbox.example/private-marketing-route','marketing':True,'marketing_notice_version':MARKETING_NOTICE}
    row=front.updates.create(vid,body);front.updates.send_challenge(row['id'])
    front.updates.verify(vid,row['id'],courier.challenges[-1]['verification_code'])
    context=browser.new_context(viewport={'width':1280,'height':950})
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='admin.test':route.abort();return
        response=admin.request(req.method,url.path,content=req.post_data,headers=req.headers) if not url.query else admin.request(req.method,url.path+'?'+url.query,content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();page.on('dialog',lambda dialog:dialog.accept('Synthetic contact management reason'));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    playwright.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="visitors"]').click();page.locator('#vContact').select_option('marketing')
    page.locator('tr[data-vid="'+vid+'"]').click()
    drawer=page.locator('#drawer')
    playwright.expect(drawer).to_contain_text('별도 동의·인증 완료')
    playwright.expect(drawer).to_contain_text(MARKETING_NOTICE)
    playwright.expect(drawer).to_contain_text('실제 광고 발송은 비활성')
    assert 'private-marketing-route' not in drawer.inner_text() and not errors and not courier.events
    from pathlib import Path
    report=Path('reports/security-2026-10-17-destination-verification');report.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(report/'admin-verified-consent.png'))
    context.close()
