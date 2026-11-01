"""Review real public renderers and clicks using isolated synthetic catalog data."""
import json
from urllib.parse import urlsplit

from playwright.sync_api import expect
from tests.test_pearl_frontend import browser,client,pearl_page,ORIGIN
from tests.test_pearl_click_journeys import install_examples
from scripts.audit_frontend_ux_20261020 import INSPECT,OUT,PAGES


def test_capture_isolated_public_review(pearl_page,client):
    page,errors,calls=pearl_page
    store=client.app.state.front.store
    # Only this disposable TestClient is allowlisted to inspect many screenshots
    # without treating the artifact generator as a normal visitor load test.
    client.app.state.front.security._allowed_ips.add('testclient')
    for i in range(75):
        rid=store.upsert_resource({'key':'ux-review-fixture:'+str(i),'name':('Synthetic documentation agent '+str(i) if i%3 else 'docs.example/'+('long-public-endpoint-'*5)+str(i)),
            'kind':['a2a','mcp','x402'][i%3],'source':'isolated-ux-review','url':'https://synthetic-'+str(i)+'.example/api',
            'description':'Synthetic public research and documentation capability used only for layout review.','category':'docs_knowledge'})
        with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',last_check_at=1 WHERE id=?",(rid,))
    data={'scope':'real public handlers; isolated synthetic catalog; not deployment/provider acceptance',
          'fixture_read_limit_bypass':True,'production_security_modified':False,'screens':[],'errors':[], 'runtime_errors':[]}
    page.on('pageerror',lambda error:data['runtime_errors'].append({'path':urlsplit(page.url).path,'error':str(error)}))
    def capture(name,device='desktop',full=True):
        page.wait_for_timeout(160)
        item=page.evaluate(INSPECT);item.update(name=name,device=device)
        file='evidence/isolated-public-'+name+'-'+device+'.png'
        page.screenshot(path=str(OUT/file),full_page=full);item['screenshot']=file
        data['screens'].append(item)
        data['errors']=list(errors)
        (OUT/'isolated-public-inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    for name in PAGES:
        page.set_viewport_size({'width':1440,'height':1000})
        page.goto(ORIGIN+'/new/en/'+name+'.html')
        page.wait_for_timeout(240)
        capture(name)
        page.set_viewport_size({'width':390,'height':844});capture(name,'mobile')
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(ORIGIN+'/#explore');expect(page.locator('#xResults .acard')).to_have_count(45)
    page.get_by_role('button',name='List',exact=True).click();capture('explore-list')
    page.locator('#xResults .acard').first.click();expect(page.locator('#drawer')).to_be_visible();capture('explore-drawer',full=False)
    page.keyboard.press('Escape')
    page.get_by_role('button',name='Cards',exact=True).click()
    page.get_by_role('button',name='Load More Agents',exact=False).click()
    expect(page.locator('#xResults .acard')).to_have_count(83);capture('explore-load-more')
    page.locator('#xQ').fill('NoMatchingSyntheticTerm');page.locator('#xQ').press('Enter');page.wait_for_timeout(250);capture('explore-no-results')
    page.locator('#xQ').fill('Synthetic documentation');page.locator('#xQ').press('Enter');page.wait_for_timeout(250);capture('explore-search')
    page.locator('#xHasReport').check();page.wait_for_timeout(250);capture('explore-report-filter')
    install_examples(page)
    page.goto(ORIGIN+'/#test');expect(page.locator('#tbRunBtn')).to_be_enabled();capture('test-ready')
    page.locator('.pearl-example-choice[data-recipe="docs"]').click();capture('test-second-example')
    page.locator('.pearl-selection-options>summary').click();capture('test-agent-picker')
    page.goto(ORIGIN+'/#workflows');capture('workflow-default')
    review=page.get_by_text('Review input →',exact=True)
    if review.count():review.first.click();capture('workflow-input-editor',full=False)
    page.goto(ORIGIN+'/#chat')
    if page.locator('dialog[open]').count():
        capture('chat-route-with-previous-dialog',full=False)
        page.keyboard.press('Escape')
    n=[0]
    def reply(route):
        n[0]+=1
        route.fulfill(json={'reply':'Synthetic UI review recommendation.','data':{'recommendations':[{'id':n[0],'name':'Synthetic agent '+str(n[0]),'kind':'a2a','grade':'A','quality_score':91,'tools':['search'],'test_report':{'id':n[0],'created_at':1792400000,'success':True}}]}})
    page.route('**/chat',reply)
    for q in ('Find research sources','Find another documentation capability'):
        page.locator('#chatInput').fill(q);page.locator('#chatSubmit').click();page.wait_for_timeout(250)
    capture('chat-two-recommendations')
    page.set_viewport_size({'width':390,'height':844});capture('chat-two-recommendations','mobile')
    page.set_viewport_size({'width':1440,'height':1000})
    for title in ('Terms of Service','Privacy Policy','Cookie Preferences','AI System Disclosures','Do Not Sell or Share My Personal Info','Notification Preferences','Accessibility Statement','Contact'):
        page.goto(ORIGIN+'/');target=page.locator('footer').get_by_text(title,exact=True)
        target.click();capture('footer-'+title.lower().replace(' ','-'),full=False)
    page.keyboard.press('Escape')
    page.goto(ORIGIN+'/#register');page.locator('#regKind + .pearl-protocol-segmented [data-value="x402"]').click();capture('registration-x402')
    page.locator('#regSubmitBtn').click();capture('registration-validation',full=False)
    data['errors']=errors
    data['chat_response_scope']='synthetic response for visual state only; model relevance not evaluated'
    (OUT/'isolated-public-inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def test_auth_error_scope(pearl_page):
    page,errors,calls=pearl_page
    evidence=[]
    page.on('pageerror',lambda error:evidence.append({'url':page.url,'error':str(error),'stack':error.stack}))
    for name in ('sign-in','sign-up','workspace'):
        page.goto(ORIGIN+'/new/en/'+name+'.html');page.wait_for_timeout(300)
    (OUT/'auth-script-error-scope.json').write_text(json.dumps(evidence,indent=2)+'\n')
