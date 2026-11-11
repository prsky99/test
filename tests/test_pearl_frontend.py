"""Separate Pearl UI: real API contracts, retained state and existing security gates."""
import ast
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://agentconcierge.biz'


@pytest.fixture
def client(tmp_path):
    store=Store(str(tmp_path/'pearl.db'))
    for i in range(8):
        rid=store.upsert_resource({'key':'pearl-'+str(i),'name':'Research '+str(i),'kind':['a2a','mcp','x402'][i%3],
            'source':'isolated','url':'https://agent-'+str(i)+'.example/api','description':'Public research sources',
            'category':'web_search'})
        with store.tx()as db:db.execute("UPDATE resources SET health_status='healthy',last_check_at=1 WHERE id=?",(rid,))
    clear_front_caches()
    front=Front(store)
    client=TestClient(create_front_app(front,manage_book_lifecycle=False))
    yield client
    client.close();front.book.close();store._db.close()


def test_separate_view_assets_csp_and_no_original_html_mutation(client):
    response=client.get('/new/en/index.html')
    assert response.status_code==200 and 'Find the right AI agent for your task.'in response.text
    assert "script-src 'self' 'sha256-" in response.headers['content-security-policy'] and 'nonce-' not in response.headers['content-security-policy']  # 11-11 hashes
    assert "script-src-attr 'none'"in response.headers['content-security-policy']
    assert response.headers['x-frame-options']=='DENY'
    assert client.get('/new/en/assets/operating.js').status_code==200
    assert client.get('/new/en/assets/pearl.png').headers['content-type'].startswith('image/png')
    source=ast.parse((ROOT/'agent_market/concierge/front.py').read_text())
    html=next(ast.literal_eval(n.value)for n in source.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='HTML'for t in n.targets))
    assert html==(ROOT/'extracted_html.txt').read_text()


def test_default_html_entry_uses_published_composition_and_keeps_json_contract(client):
    response=client.get('/',headers={'accept':'text/html'})
    assert response.status_code==200
    assert 'data-pearl-entry="overview"' in response.text
    assert re.search(r'/new/en/assets/(pearl-ui\.js|bundle\.js\?f=[^"]*pearl-ui)', response.text)  # 11-11: one bundle
    assert 'reference-about-hero' in response.text
    assert 'pearlWorkflowChoices' in response.text
    assert 'noindex' not in response.headers.get('x-robots-tag','')
    assert "script-src 'self' 'sha256-" in response.headers['content-security-policy']  # 11-11: hashes, so the edge may keep the page
    assert client.get('/',headers={'accept':'application/json'}).headers['content-type'].startswith('application/json')


@pytest.mark.parametrize('path',['/new/en/../build_en.py','/new/en/assets/../../en-manifest.json','/new/en/assets/.env',
                                '/new/design/manifest.json','/new/design/../../AGENTS.md','/new/en/private.html'])
def test_no_private_or_traversal_files(client,path):
    assert client.get(path).status_code in (403,404)


def test_public_metrics_are_consistent_and_do_not_create_execution(client):
    data=client.get('/api/pearl/status').json()
    assert data['cataloged']==8 and data['reachable']==8 and data['with_status_check']==8
    assert data['new_24h']==8
    assert sum(p['n']for p in data['by_protocol'])==8
    assert data['execution_24h']['completed']==0
    assert data['execution_24h']['successful_resources']==0
    assert set(data)=={'captured_at_utc','cataloged','reachable','with_status_check','reachable_share','new_24h','by_protocol','categories','execution_24h'}
    assert client.get('/api/pearl/access').json()=={'workspace_available':False}
    assert client.get('/api/customer-auth/session').status_code==404


@pytest.fixture
def pearl_page(browser,client):
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',color_scheme='light')
    context.add_init_script("localStorage.setItem('agent_cookie_consent_v2',JSON.stringify({analytics:false,marketing:false,essential:true,timestamp:Date.now()}))")
    page=context.new_page();errors=[];calls=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='agentconcierge.biz':return route.abort()
        calls.append((req.method,url.path))
        if req.method not in ('GET','HEAD') and not url.path.startswith('/chat'):
            return route.fulfill(status=403,json={'detail':'Isolated test: external execution is disabled.'})
        res=client.request(req.method,url.path+('?' +url.query if url.query else ''),content=req.post_data,
            headers={k:req.headers.get(k,'')for k in ['accept','content-type','origin','x-visitor-token']})
        route.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items()if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    yield page,errors,calls
    context.close()


@pytest.mark.parametrize('file,panel',[('index.html','overview'),('agent-status.html','status'),('explore.html','explore'),
    ('learn.html','learn'),('test.html','test'),('workflows.html','workflows'),('chat.html','chat'),('list-agent.html','register'),('about.html','about')])
def test_operating_menu_loads_with_real_headers(pearl_page,file,panel):
    from playwright.sync_api import expect
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/new/en/'+file)
    expect(page.locator('[data-panel="'+panel+'"]')).to_be_visible()
    page.wait_for_timeout(350)
    assert not errors


def test_live_metrics_manual_refresh_input_retention_and_home_only_refresh(pearl_page):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/new/en/index.html')
    expect(page.locator('#secOverview [data-metric="cataloged"]')).to_have_text('8')
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    page.locator('.nav-tab[data-tab="explore"]').click();page.locator('#xQ').fill('Retain this query')
    page.locator('.nav-tab[data-tab="status"]').click()
    expect(page.locator('#secStatus [data-metric="cataloged"]')).to_have_text('8')
    button=page.locator('[data-pearl-action="refresh-status"]');button.click();expect(button).to_be_enabled()
    page.locator('.nav-tab[data-tab="explore"]').click();expect(page.locator('#xQ')).to_have_value('Retain this query')
    page.clock.install();before=len([p for m,p in calls if p=='/api/pearl/status'])
    page.clock.run_for(65000)
    expect(page.locator('#xQ')).to_have_value('Retain this query')
    assert len([p for m,p in calls if p=='/api/pearl/status'])==before
    assert not errors


def test_mobile_menu_necklace_and_no_page_overflow(pearl_page):
    from playwright.sync_api import expect
    page,errors,_=pearl_page
    page.set_viewport_size({'width':390,'height':844});page.goto(ORIGIN+'/new/en/index.html')
    expect(page.locator('#secOverview [data-metric="cataloged"]')).to_have_text('8')
    page.locator('[data-pearl-action="menu"]').click();expect(page.locator('#navTabs')).to_be_visible()
    page.locator('.nav-tab[data-tab="status"]').click();expect(page.locator('#secStatus')).to_be_visible();expect(page.locator('#navTabs')).not_to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors


def test_default_entry_retains_deep_links_published_layout_and_safe_footer(pearl_page):
    from playwright.sync_api import expect
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/#explore')
    expect(page.locator('#secExplore .results-layout')).to_be_visible()
    expect(page.locator('#pearlAgentPreview h3')).not_to_have_text('Select an agent')
    page.locator('#xQ').fill('Keep my draft')
    page.locator('.nav-tab[data-tab="about"]').click()
    expect(page.locator('#secAbout .reference-about-hero')).to_be_visible()
    expect(page.locator('#secAbout h1')).to_contain_text('Individual strengths.')
    expect(page.locator('#secAbout .about-necklace-art')).to_be_hidden()
    heading=page.locator('#secAbout h1').bounding_box()
    assert heading and heading['x']>=0 and heading['x']+heading['width']<=page.viewport_size['width']
    page.locator('.nav-tab[data-tab="explore"]').click()
    expect(page.locator('#xQ')).to_have_value('Keep my draft')
    page.get_by_role('link',name='Privacy Policy',exact=True).click()
    expect(page.locator('dialog[open]')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('dialog[open]')).to_have_count(0)
    page.locator('.nav-tab[data-tab="about"]').click()
    page.locator('#secAbout a[href="#contact"]').click()
    expect(page.locator('dialog[open]')).to_be_visible()
    page.keyboard.press('Escape')
    page.locator('.brand-box').click()
    page.locator('#secOverview [data-pearl-anchor="execution-checks"]').click()
    expect(page.locator('#secStatus')).to_be_visible()
    assert not errors


def mock_selectable_templates(page,client):
    """Presentation-only fixtures; actual execution uses the owned-agent tests."""
    data=client.get('/api/workflows/templates').json()
    for template in data['templates']:
        template['execution_availability']={'available':True,'message':'Isolated presentation fixture.'}
    page.route('**/api/workflows/templates',lambda route:route.fulfill(json=data))


def test_workflow_pearl_sidebar_selects_existing_template_without_execution(pearl_page,client):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    mock_selectable_templates(page,client)
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    page.locator('#btnFrontWfViewTemplates').click()
    card=page.locator('#frontTemplatesGrid .template-card').first
    selected=card.get_attribute('data-template-id')
    card.get_by_role('button',name='Use workflow',exact=True).click()
    expect(page.locator('#pearlWorkflowChoices')).to_have_attribute('data-selected-id',selected)
    expect(page.locator('#frontWfCanvasView')).to_be_visible()
    assert not [(m,p) for m,p in calls if m=='POST' and p=='/api/workflows/run']
    assert not errors


def test_published_learn_topic_protocol_keyboard_and_retained_selection(pearl_page):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/#learn')
    expect(page.locator('.reference-learn-body')).to_be_visible()
    assert not [p for m,p in calls if p=='/api/insights']
    expect(page.locator('.pearl-protocol-reference')).to_have_count(0)
    page.locator('[data-learn-tab="evidence"]').click()
    expect(page.locator('#learn-panel-evidence')).to_be_visible()
    expect(page.locator('[data-learn-tab="evidence"]')).to_have_attribute('aria-selected','true')
    expect(page).to_have_url(ORIGIN+'/new/en/learn.html#learn')
    for key in ['connections','patterns','glossary','basics']:
        page.locator('[data-learn-tab="'+key+'"]').click()
        expect(page.locator('#learn-panel-'+key)).to_be_visible()
    page.locator('[data-learn-protocol="mcp"]').click()
    expect(page.locator('#learn-protocol-context')).to_contain_text('MCP: tools and resources')
    expect(page.locator('[data-learn-protocol="mcp"]')).to_have_attribute('aria-pressed','true')
    page.locator('[data-learn-tab="basics"]').focus();page.keyboard.press('End')
    expect(page.locator('#learn-panel-glossary')).to_be_visible()
    page.locator('.nav-tab[data-tab="explore"]').click();page.locator('.nav-tab[data-tab="learn"]').click()
    expect(page.locator('#learn-panel-glossary')).to_be_visible()
    assert not [p for m,p in calls if p=='/api/insights']
    assert not errors


@pytest.mark.parametrize('width',[1440,390])
def test_footer_reference_groups_links_and_policy_actions(pearl_page,width):
    from playwright.sync_api import expect
    page,errors,_=pearl_page
    page.set_viewport_size({'width':width,'height':900})
    page.goto(ORIGIN+'/new/en/about.html')
    footer=page.locator('footer.pearl-footer')
    expect(footer.locator('.pf-group')).to_have_count(3)
    expect(footer.locator('.pf-link')).to_have_count(9)  # 11-11: Advertise is a plain link to the advertiser landing
    expect(footer.locator('[data-footer-link="advertise"]')).to_have_attribute('href','/ad-coin/v2/advertise')
    for key in ['terms','privacy','cookies','privacy-choices','accessibility','disclosures','notifications','contact']:
        footer.locator('[data-footer-key="'+key+'"]').click()
        expect(page.locator('dialog[open]')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('dialog[open]')).to_have_count(0)
    footer.locator('[data-footer-key="privacy"]').click()
    sidebar=page.locator('#legalModalTabs').bounding_box();body=page.locator('#legalModalBody').bounding_box()
    if width==1440:
        assert sidebar['x']+sidebar['width']<=body['x']+1
        assert abs(sidebar['y']-body['y'])<2
    else:
        assert sidebar['y']+sidebar['height']<=body['y']+1
    page.keyboard.press('Escape')
    assert page.evaluate('Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+2')
    footer.locator('[data-footer-link="advertise"]').click()
    page.wait_for_url('**/ad-coin/v2/advertise')
    expect(page.locator('dialog[open]')).to_have_count(0)
    assert not errors


def test_first_test_visit_selects_available_news_without_running(pearl_page):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/new/en/test.html')
    # UI policy 11-01: the shipped first example is selected at once, without a request or a run.
    first=page.evaluate("JSON.parse(document.getElementById('appBootstrapData').textContent).testbench_examples[0]")
    expect(page.locator('.pearl-example-choice[data-recipe="'+first['id']+'"]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('#tbAgentSelect')).to_have_value(str(first['resource_id']))
    expect(page.get_by_text('Agent and request',exact=True)).to_be_visible()
    expect(page.get_by_text('Test result',exact=True)).to_be_visible()
    assert not [(m,p)for m,p in calls if p in('/api/test/presets','/api/test/execute')]
    assert not errors


def test_retained_runtime_treats_markup_as_text(pearl_page):
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/new/en/chat.html')
    page.evaluate('''() => appendChatBubble('bot','<img src=x onerror="window.__pearlXss=1">',{intent:'chat',data:{}})''')
    assert page.locator('#chatMessages img[src="x"]').count()==0
    assert page.evaluate('window.__pearlXss||0')==0
    assert not errors


def test_protocol_category_discovery_and_report_preview_tabs(pearl_page):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/new/en/agent-status.html')
    expect(page.locator('#secStatus [data-metric="cataloged"]')).to_have_text('8')
    page.locator('#secStatus .protocol-card a').nth(1).click()
    expect(page.locator('#secExplore')).to_be_visible();expect(page.locator('#xKind')).to_have_value('mcp')
    page.locator('.nav-tab[data-tab="status"]').click();page.locator('#secStatus .category-cards a').nth(1).click()
    expect(page.locator('#xCategory')).to_have_value('web_search')
    page.locator('.brand-box').click();page.locator('.evidence-preview summary').click()
    tab=page.locator('.evidence-preview [role="tab"]').first;tab.focus();page.keyboard.press('ArrowRight')
    expect(page.locator('[data-tab-panel="evidence"]')).to_be_visible()
    assert not errors


@pytest.mark.parametrize('file',['sign-in.html','sign-up.html','workspace.html','account.html'])
def test_account_views_keep_closed_access_safe_and_handle_missing_session(pearl_page,file):
    from playwright.sync_api import expect
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/new/en/'+file)
    expect(page.locator('#status')).to_contain_text('unavailable' if file in ['sign-in.html','sign-up.html'] else 'could not be checked')
    if file in ['sign-in.html','sign-up.html']:
        expect(page.locator('#google')).to_be_disabled();expect(page.locator('#github')).to_be_disabled()
        expect(page.get_by_role('button',name='Sign in with GitHub',exact=True)).to_have_count(1)
    assert not errors


def test_provider_availability_is_read_with_csp_without_opening_authentication(pearl_page):
    from playwright.sync_api import expect
    page,errors,_=pearl_page
    page.route('**/api/customer-auth/session',lambda route:route.fulfill(status=401,json={'error':'Sign in required.'}))
    # The sign-in page reads the unauthenticated status endpoint, not the private session.
    page.route('**/api/customer-auth/status',lambda route:route.fulfill(status=200,json={'ok':True,'authenticated':False}))
    page.route('**/api/customer-auth/options',lambda route:route.fulfill(status=200,json={'providers':[{'id':'google','configured':True},{'id':'github','configured':False}]}))
    page.goto(ORIGIN+'/new/en/sign-in.html')
    expect(page.locator('#google')).to_be_enabled()
    expect(page.locator('#github')).to_be_disabled()
    expect(page.locator('#status')).to_have_text('Choose a sign-in provider.')
    assert not errors


@pytest.mark.parametrize('access,advertise', [(False,False),(False,True),(True,False),(True,True)])
def test_workspace_release_gate_applies_to_root_and_every_public_menu(client,access,advertise):
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.items=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':self.items.append(dict(attrs))
    app=create_front_app(client.app.state.front,workspace_access_enabled=access,
                         workspace_link_enabled=advertise,manage_book_lifecycle=False)
    with TestClient(app,base_url=ORIGIN) as published:
        manifest=json.loads((ROOT/'new/en-manifest.json').read_text())
        for path in ['/']+['/new/en/'+file for file in manifest['live_pages']]:
            response=published.get(path,headers={'Accept':'text/html'})
            assert response.status_code==200
            document=Links();document.feed(response.text)
            entry=[link for link in document.items if link.get('id')=='workspaceAccessLink']
            assert len(entry)==int(access and advertise),path
            if entry:
                assert entry[0]['href']=='/customer/sign-in'
                assert not any(key in entry[0] for key in ('disabled','aria-disabled','onclick'))
                assert 'Workspace: Google or GitHub sign-in' in response.text
            assert '<!-- WORKSPACE_ACCESS_LINK -->' not in response.text
            assert "frame-ancestors 'none'" in response.headers['content-security-policy']
        assert published.get('/api/pearl/access').json()=={'workspace_available':access and advertise}
        assert published.get('/api/customer-auth/session').status_code==(401 if access else 404)


@pytest.mark.parametrize('width', [390,960,1024,1440])
def test_public_workspace_menu_opens_secure_customer_entry_on_desktop_and_mobile(client,browser,width):
    from playwright.sync_api import expect
    app=create_front_app(client.app.state.front,workspace_access_enabled=True,
                         workspace_link_enabled=True,manage_book_lifecycle=False)
    context=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
    context.set_offline(True)
    page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    proof=ROOT/'reports/workspace-public-launch-2026-10-21';proof.mkdir(parents=True,exist_ok=True)
    with TestClient(app,base_url=ORIGIN) as published:
        def serve(route):
            req=route.request;url=urlsplit(req.url)
            assert url.hostname=='agentconcierge.biz'
            requests.append((req.method,url.path))
            response=published.request(req.method,url.path+('?' +url.query if url.query else ''),
                                       headers=req.headers,content=req.post_data,follow_redirects=False)
            route.fulfill(status=response.status_code,body=response.content,
                          headers={k:v for k,v in response.headers.items() if k not in
                                   ('content-length','content-encoding','transfer-encoding','set-cookie')})
        context.route('**/*',serve)
        try:
            page.goto(ORIGIN+'/')
            menu=page.get_by_role('navigation',name='Main navigation')
            if width<=980:
                page.get_by_role('button',name='Open navigation',exact=True).click()
            entry=menu.get_by_role('link',name='Workspace',exact=True)
            expect(entry).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            header=page.locator('header.top-nav')
            assert entry.evaluate('(e)=>e.getBoundingClientRect().right<=innerWidth')
            assert header.evaluate('(e)=>e.getBoundingClientRect().height<130')
            page.screenshot(path=str(proof/('public-menu-'+str(width)+'.png')))
            entry.focus();page.keyboard.press('Enter')
            expect(page).to_have_url(ORIGIN+'/customer/sign-in')
            expect(page.get_by_role('button',name='Sign in with Google',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Sign in with GitHub',exact=True)).to_be_visible()
            expect(page.locator('.workspace-sidebar')).to_have_count(0)
            page.screenshot(path=str(proof/('signin-from-menu-'+str(width)+'.png')))
            assert not errors
            assert not any(method not in ('GET','HEAD') for method,_ in requests)
        finally:context.close()
