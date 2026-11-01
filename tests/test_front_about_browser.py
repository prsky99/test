"""Native About navigation, mobile layout, metadata and links with isolated API fixtures."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_about import about_client
from agent_market.concierge.public_metadata import PAGES,url
TITLE=PAGES['about'][1]
from tests.test_front_workflow_browser import browser

REPORT=Path('reports/advancement-completion-2026-10-18/about')

@pytest.fixture
def about_page(about_client,browser):
    context=browser.new_context();page=context.new_page();errors=[];calls=[];violations=[]
    page.add_init_script("document.addEventListener('securitypolicyviolation',event=>{window.__aboutCsp=(window.__aboutCsp||[]).concat(event.violatedDirective)});")
    def serve(route):
        req=route.request;url=urlsplit(req.url);calls.append((req.method,url.path))
        if url.hostname!='agentconcierge.biz':return route.abort()
        response=about_client.request(req.method,url.path+('?' +url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);page.on('pageerror',lambda value:errors.append(str(value)))
    yield page,errors,calls
    context.close()


def test_about_deep_link_has_current_seo_and_native_keyboard_navigation(about_page):
    page,errors,calls=about_page;page.goto('https://agentconcierge.biz/#about');expect(page.locator('#secAbout')).to_be_visible();expect(page).to_have_title(TITLE)
    description=page.locator('head meta[name="description"]').get_attribute('content')
    assert description==page.locator('head meta[property="og:description"]').get_attribute('content')==page.locator('head meta[name="twitter:description"]').get_attribute('content')
    assert page.locator('head link[rel="canonical"]').get_attribute('href')==url('about')
    assert page.locator('head meta[property="og:url"]').get_attribute('content')==url('about')
    assert page.locator('head script[type="application/ld+json"]').inner_text().find('AboutPage')>=0
    about=page.get_by_role('button',name='About',exact=True);expect(about).to_have_attribute('aria-current','page')
    listing=page.get_by_role('button',name='List Your Agent',exact=True);listing.focus();page.keyboard.press('Tab');expect(about).to_be_focused();page.keyboard.press('Enter');expect(page.locator('#secAbout')).to_be_visible()
    brand=page.get_by_role('link',name='Agent Concierge Home',exact=True);brand.focus();page.keyboard.press('Enter');expect(page.locator('#secOverview')).to_be_visible();expect(page).to_have_title(PAGES['overview'][1]);expect(brand).to_have_attribute('aria-current','page')
    assert not any(method=='POST' for method,_ in calls) and not errors


@pytest.mark.parametrize('width',[320,390,768,1440])
def test_about_responsive_layout_theme_and_local_icons(about_page,width):
    page,errors,_=about_page;page.set_viewport_size({'width':width,'height':1000});page.emulate_media(color_scheme='dark' if width==390 else 'light',reduced_motion='reduce');page.goto('https://agentconcierge.biz/#about');expect(page.locator('#secAbout')).to_be_visible()
    geometry=page.locator('#secAbout').evaluate('(node)=>({scroll:node.scrollWidth,width:node.clientWidth,document:document.documentElement.scrollWidth,viewport:innerWidth})')
    assert geometry['scroll']<=geometry['width']+1 and geometry['document']<=geometry['viewport']
    for selector in ('#aboutTitle','#aboutValueTitle','#aboutJourneyTitle','#aboutPrinciplesTitle','#aboutVisionTitle'):expect(page.locator(selector)).to_be_visible()
    assert page.locator('#secAbout .lucide').count()>=3
    assert not page.locator('#secAbout img[src^="http"],#secAbout iframe,#secAbout script').count()
    assert page.evaluate('window.__aboutCsp||[]')==[] and not errors
    REPORT.mkdir(parents=True,exist_ok=True)
    if width in (390,1440):
        choice=page.get_by_role('button',name='Reject Non-Essential',exact=True)
        if choice.is_visible():choice.click()
        page.screenshot(path=str(REPORT/('about-mobile-dark.png' if width==390 else 'about-desktop-light.png')),full_page=True)


@pytest.mark.parametrize('href,panel',[('#chat','#secChat'),('#explore','#secExplore'),('#workflows','#secWorkflows'),('#register','#secRegister')])
def test_about_ctas_use_existing_menus_without_submission(about_page,href,panel):
    page,errors,calls=about_page;page.goto('https://agentconcierge.biz/#about');page.locator('#secAbout a[href="'+href+'"]').first.click();expect(page.locator(panel)).to_be_visible();assert not any(method=='POST' for method,_ in calls) and not errors


def test_about_legal_links_open_existing_disclosures_without_external_navigation(about_page):
    page,errors,calls=about_page;page.goto('https://agentconcierge.biz/#about');page.locator('#secAbout a[href="#privacy"]').click();expect(page.locator('#legalModal')).to_be_visible();assert page.url.endswith('#privacy')
    page.locator('#legalModal').get_by_role('button',name='Close',exact=True).click();expect(page.locator('#secAbout')).to_be_visible()
    assert not errors and not any(method=='POST' for method,_ in calls)
