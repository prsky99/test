"""Public site journeys use an isolated catalog; no production form submissions."""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect
from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page


def test_reported_hash_contact_journey_and_baseline_controls(pearl_page,tmp_path):
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/#register')
    expect(page.locator('#secRegister')).to_be_visible()
    page.evaluate("location.hash='contact'")
    expect(page.locator('#legalModal')).to_be_visible()
    expect(page.locator('#legalModalTitle')).to_contain_text('Contact')
    forms=page.locator('#legalModal form').evaluate_all('(nodes)=>nodes.map(n=>({id:n.id,parent:n.parentElement.closest("form")?.id||null}))')
    assert all(item['parent'] is None for item in forms)
    page.keyboard.press('Escape')
    for tab in ('overview','status','learn','explore','test','workflows','chat','register','about'):
        page.evaluate('(tab)=>location.hash=tab',tab)
        expect(page.locator('[data-panel="'+tab+'"]')).to_be_visible()
        page.wait_for_timeout(80)
        missing=page.locator('button:visible,input:visible,select:visible,textarea:visible').evaluate_all('''nodes=>nodes.filter(n=>!n.closest('[aria-hidden="true"]')).filter(n=>{
          const named=n.getAttribute('aria-label')||n.getAttribute('aria-labelledby')||n.getAttribute('title')||
            (n.labels?.length?Array.from(n.labels).map(x=>x.textContent).join(''):'')||
            (n.tagName==='BUTTON'?n.textContent:'');
          return !named.trim();
        }).map(n=>({tag:n.tagName,id:n.id,cls:n.className,html:n.outerHTML.slice(0,320)}))''')
        (tmp_path/(tab+'-missing.json')).write_text(json.dumps(missing,indent=2))
        assert not missing,(tab,missing)
    assert not errors
    assert not any(method=='POST' and path!='/chat' for method,path in calls)


def test_public_navigation_has_native_links(pearl_page):
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/')
    assert page.locator('#navTabs a[href][data-tab]').count()==8
    assert page.locator('header a.brand-box[href]').count()==1
    assert page.locator('footer button[data-footer-key]').count()==0
    assert page.locator('footer a[data-footer-key][href]').count()==8
    assert not errors


@pytest.mark.parametrize('width',[1440,390])
def test_history_legal_links_titles_and_form_isolation(pearl_page,width):
    page,errors,calls=pearl_page;page.set_viewport_size({'width':width,'height':950})
    page.goto(ORIGIN+'/#register')
    page.locator('#regName').fill('Keep my listing draft')
    page.locator('footer a[data-footer-key="contact"]').click()
    expect(page.locator('#legalModal')).to_be_visible()
    expect(page.locator('#legalModalTitle')).to_contain_text('Contact')
    assert page.locator('#legalModal form').evaluate('(form)=>!form.parentElement.closest("form")')
    expect(page).to_have_title(re.compile('Contact'))
    page.go_back()
    expect(page.locator('#legalModal')).not_to_be_visible()
    expect(page.locator('#secRegister')).to_be_visible()
    expect(page.locator('#regName')).to_have_value('Keep my listing draft')
    page.go_forward()
    expect(page.locator('#legalModal')).to_be_visible()
    page.keyboard.press('Escape')
    for key,title in [('terms','Terms'),('privacy','Privacy'),('accessibility','Accessibility'),('disclosures','AI'),('notifications','Notification')]:
        page.locator('footer a[data-footer-key="'+key+'"]').click()
        expect(page.locator('#legalModal')).to_be_visible()
        assert page.locator('#legalModalTitle').inner_text().strip()
        page.keyboard.press('Escape')
    page.locator('footer a[data-footer-key="cookies"]').click()
    expect(page.locator('#cookiePrefsModal')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#cookiePrefsModal')).not_to_be_visible()
    expect(page).not_to_have_url(re.compile('#cookie-preferences$'))
    assert not errors
    assert not any(method=='POST' for method,path in calls)


def test_middle_click_opens_navigation_and_policy_in_new_tabs(pearl_page):
    page,errors,_=pearl_page;page.goto(ORIGIN+'/#register')
    original=page.url
    for selector in ('#navTabs a[data-tab="learn"]','footer a[data-footer-key="privacy"]'):
        with page.context.expect_page() as opened:
            page.locator(selector).click(button='middle')
        other=opened.value;other.wait_for_load_state('domcontentloaded')
        if 'privacy' in selector:expect(other.locator('#legalModal')).to_be_visible()
        else:expect(other.locator('#secLearn')).to_be_visible()
        assert page.url==original
        other.close()
    assert not errors


@pytest.mark.parametrize('url',[
    'invalid endpoint','http://127.0.0.1/api','http://2130706433/api','http://192.168.0.24/api',
    'http://[::1]/api','http://[::ffff:192.168.0.1]/api','http://test.local/api','https://user:pass@public.example/api'
])
def test_registration_invalid_endpoint_has_feedback_without_request(pearl_page,url):
    page,errors,calls=pearl_page;page.goto(ORIGIN+'/#register')
    page.locator('#regUrl').fill(url);page.locator('#regUrl').press('Tab')
    expect(page.locator('#regUrlError')).to_be_visible()
    expect(page.locator('#regUrl')).to_have_attribute('aria-invalid','true')
    page.locator('#regUrl').fill('https://agent.example/api');page.locator('#regUrl').press('Tab')
    expect(page.locator('#regUrlError')).not_to_be_visible()
    assert page.locator('#regUrl').evaluate('(input)=>input.validationMessage')==''
    assert not any(method=='POST' for method,path in calls)
    assert not errors


def test_accessibility_tree_has_named_visible_controls_and_lazy_art(pearl_page,tmp_path):
    page,errors,calls=pearl_page;page.goto(ORIGIN+'/#explore')
    session=page.context.new_cdp_session(page)
    for route in ('overview','status','learn','explore','test','workflows','chat','register','about'):
        page.evaluate('(route)=>location.hash=route',route)
        expect(page.locator('[data-panel="'+route+'"]')).to_be_visible()
        nodes=session.send('Accessibility.getFullAXTree')['nodes']
        unnamed=[{'role':n.get('role',{}).get('value'),'id':n.get('backendDOMNodeId')} for n in nodes
                 if not n.get('ignored') and n.get('role',{}).get('value') in ('button','textbox','combobox','checkbox','radio')
                 and not n.get('name',{}).get('value','').strip()]
        assert not unnamed,(route,unnamed)
    page.goto(ORIGIN+'/')
    assert not [path for _,path in calls if path.endswith('/pearl.png')]
    # Asset URLs carry a content version; the optimized image is still the WebP file.
    assert page.locator('.necklace-bead').first.get_attribute('href').split('?')[0].endswith('pearl.webp')
    page.screenshot(path=str(tmp_path/'home-optimized.png'),full_page=True)
    assert not errors


@pytest.mark.parametrize('width,theme',[(1440,'light'),(1440,'dark'),(390,'light'),(390,'dark')])
def test_mobile_theme_keyboard_and_layout(pearl_page,width,theme,tmp_path):
    page,errors,_=pearl_page;page.set_viewport_size({'width':width,'height':1000})
    page.goto(ORIGIN+'/')
    if page.locator('body').get_attribute('data-theme')!=theme:
        page.locator('[data-pearl-action="theme"]').click()
    expect(page.locator('body')).to_have_attribute('data-theme',theme)
    if width<700:
        page.locator('[data-pearl-action="menu"]').click()
        expect(page.locator('[data-pearl-action="menu"]')).to_have_attribute('aria-expanded','true')
    page.locator('#navTabs a[data-tab="learn"]').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#secLearn')).to_be_visible()
    assert page.locator('#secLearn h1').evaluate('(heading)=>document.activeElement===heading')
    if width<700:expect(page.locator('[data-pearl-action="menu"]')).to_have_attribute('aria-expanded','false')
    for route in ('overview','status','learn','explore','test','workflows','chat','register','about'):
        page.evaluate('(route)=>location.hash=route',route)
        expect(page.locator('[data-panel="'+route+'"]')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),route
    page.evaluate("location.hash='overview'")
    expect(page.locator('#secOverview')).to_be_visible()
    artifact=Path(__file__).resolve().parents[1]/'reports/public-site-repairs-2026-10-26/screenshots'
    artifact.mkdir(exist_ok=True)
    page.screenshot(path=str(artifact/('home-'+str(width)+'-'+theme+'.png')),full_page=True)
    assert not errors


def test_invalid_check_and_autofill_stays_local(pearl_page):
    page,errors,calls=pearl_page;page.goto(ORIGIN+'/#register')
    page.locator('#regUrl').fill('http://192.168.0.24/api')
    page.locator('#uxInspectEndpoint').click()
    expect(page.locator('#regUrlError')).to_be_visible()
    expect(page.locator('#regUrl')).to_be_focused()
    assert not any(method=='POST' for method,path in calls)
    assert not errors


def test_testbench_completes_from_a_different_page_and_shows_final_output(pearl_page):
    from tests.test_pearl_click_journeys import install_examples
    page,errors,_=pearl_page;install_examples(page)
    sent=[]
    def execute(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'protocol':'mcp','output':'Verified synthetic source A\nVerified synthetic source B',
            'execution_succeeded':True,'task_status':'succeeded','latency_ms':10})
    page.route('**/api/test/execute',execute)
    page.goto(ORIGIN+'/#register');page.evaluate("location.hash='test'")
    expect(page.locator('#secTest')).to_be_visible()
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.locator('#tbRunBtn').click()
    expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    expect(page.locator('#tbOutputPre')).to_have_text('Verified synthetic source A\nVerified synthetic source B')
    assert len(sent)==1
    assert not errors


def test_testbench_example_failure_offers_a_real_retry(pearl_page):
    from tests.test_pearl_click_journeys import install_examples
    page,errors,_=pearl_page
    page.route('**/api/test/presets',lambda route:route.fulfill(status=503,json={'error':'Synthetic unavailable'}))
    page.goto(ORIGIN+'/#test')
    expect(page.locator('#pearlRetryExamples')).to_be_visible()
    expect(page.locator('#pearlExampleLoadState')).to_contain_text('could not')
    install_examples(page)
    page.locator('#pearlRetryExamples').click()
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    expect(page.locator('#pearlTestExampleName')).to_have_text('Technology news')
    assert not errors


def test_contact_submission_is_independent_of_an_empty_registration_form(pearl_page):
    page,errors,calls=pearl_page;submitted=[]
    def contact(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(json={'inquiry_id':'synthetic-contact-only'})
    page.route('**/api/contact/submit',contact)
    page.goto(ORIGIN+'/#register')
    assert page.locator('#regName').input_value()==''
    page.locator('footer a[data-footer-key="contact"]').click()
    for id,value in [('inqName','Synthetic visitor'),('inqEmail','synthetic@example.test'),('inqSubject','Isolated form validation'),('inqMessage','Synthetic request intercepted before network.')]:
        page.locator('#'+id).fill(value)
    page.locator('#btnSubmitInquiry').click()
    expect(page.locator('#inqFeedbackMsg')).to_contain_text('synthetic-contact-only')
    assert len(submitted)==1 and submitted[0]['subject']=='Isolated form validation'
    assert not any(method=='POST' and path=='/api/register' for method,path in calls)
    assert not errors
