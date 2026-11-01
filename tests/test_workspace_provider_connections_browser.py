"""Real Chromium exercises connection forms without operating accounts or providers."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
import pytest
from playwright.sync_api import expect
from agent_market.customer_identity_service import COOKIE
from tests.test_workspace_provider_connections import connections, customer_flow, typed_release_world, typed_world, routing
from tests.test_front_workflow_browser import browser
from tests.human_workspace_helpers import manual

OUT=Path('reports/workspace-provider-connections-2026-10-21')

@pytest.fixture
def connection_page(connections,browser):
    x=connections;context=browser.new_context(viewport={'width':1440,'height':1000});context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        r=route.request;u=urlsplit(r.url)
        if u.hostname!='customer.test':external.append(u.hostname);route.abort();return
        result=x.client.request(r.method,u.path+('?' + u.query if u.query else ''),headers=r.headers,content=r.post_data,follow_redirects=False)
        route.fulfill(status=result.status_code,body=result.content,headers={k:v for k,v in result.headers.items() if k not in ('content-length','content-encoding','set-cookie','transfer-encoding')})
    context.route('**/*',handler)
    try:
        yield x,page
        assert not errors and not external
    finally:context.close()


def test_key_guidance_mask_save_verify_replace_remove_and_keep_draft(connection_page):
    x,page=connection_page
    def provider(request):
        body=json.loads(request.content)
        assert body['method']=='initialize'
        return httpx.Response(200 if request.headers.get('x-api-key') else 401,json={'jsonrpc':'2.0','id':body['id'],'result':{'protocolVersion':'2025-03-26'}})
    x.manager.http=httpx.Client(transport=httpx.MockTransport(provider))
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
    expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
    manual(page)
    page.locator('#name').fill('Keep my draft input')
    page.locator('.workspace-manage > summary').click()
    page.locator('#workspace-navigation').get_by_role('link',name='Provider connections',exact=True).click()
    expect(page.locator('#provider-dialog')).to_be_visible()
    page.locator('#provider-search').fill(str(x.rid))
    page.locator('#provider-search-form button').click()
    page.get_by_role('button',name='Connection options',exact=True).click()
    expect(page.locator('#provider-host')).to_contain_text('https://provider.example/mcp')
    expect(page.locator('#provider-save')).to_be_disabled()
    page.locator('#provider-key').fill('synthetic-browser-key-1234')
    expect(page.locator('#provider-key')).to_have_attribute('type','password')
    page.locator('#provider-key-toggle').click()
    expect(page.locator('#provider-key')).to_have_attribute('type','text')
    page.locator('#provider-key-toggle').click()
    page.locator('#provider-key-consent').check()
    OUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUT/'01-key-guidance-desktop.png'),full_page=True)
    page.locator('#provider-save').click()
    expect(page.locator('#provider-status')).to_contain_text('Connection saved securely.')
    expect(page.locator('#provider-key')).to_have_value('')
    expect(page.locator('#provider-current')).to_have_text('Saved · authentication not verified')
    page.locator('#provider-verify-consent').check();page.locator('#provider-verify').click()
    expect(page.locator('#provider-current')).to_have_text('Authentication verified')
    page.screenshot(path=str(OUT/'02-authentication-verified.png'),full_page=True)
    page.locator('#provider-key').fill('synthetic-replacement-key-5678');page.locator('#provider-key-consent').check()
    page.locator('#provider-save').click()
    expect(page.locator('#provider-current')).to_have_text('Saved · authentication not verified')
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(OUT/'03-key-guidance-mobile.png'),full_page=True)
    assert page.locator('#provider-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    page.locator('#provider-disconnect-panel summary').click();page.locator('#provider-disconnect').click()
    expect(page.locator('#provider-status')).to_contain_text('Stored credential removed.')
    page.locator('#provider-close').click()
    expect(page.locator('#name')).to_have_value('Keep my draft input')
    assert not x.manager.listing(x.ws,x.actor)['connections']
    x.manager.http.close()


def test_unsupported_auth_does_not_collect_secrets(connection_page):
    x,page=connection_page
    with x.w.store.tx() as db:db.execute('UPDATE resources SET auth_method=? WHERE id=?',('basic',x.rid))
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/connections')
    expect(page.locator('#provider-status')).to_contain_text('Choose an agent')
    page.locator('#provider-search').fill(str(x.rid));page.locator('#provider-search-form button').click()
    page.get_by_role('button',name='Connection options',exact=True).click()
    expect(page.locator('#provider-reason')).to_contain_text('username/password')
    expect(page.locator('#provider-key-form')).not_to_be_visible()
    expect(page.locator('#provider-oauth')).not_to_be_visible()
    page.screenshot(path=str(OUT/'04-provider-specific-setup.png'),full_page=True)


def test_oauth_permissions_and_registration_guidance(connection_page):
    x,page=connection_page
    from tests.test_workspace_provider_connections import oauth
    state,calls=oauth(x)
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/connections')
    expect(page.locator('#provider-status')).to_contain_text('Choose an agent')
    page.locator('#provider-search').fill(str(x.rid));page.locator('#provider-search-form button').click()
    page.get_by_role('button',name='Connection options',exact=True).click()
    page.locator('#provider-oauth-inspect').click()
    expect(page.locator('#provider-issuer')).to_have_text('Authorization provider: https://auth.example')
    expect(page.locator('#provider-callback')).to_contain_text('/api/customer-provider-oauth/'+str(x.rid)+'/callback')
    expect(page.locator('#provider-oauth-begin')).to_be_disabled()
    expect(page.locator('#provider-scopes input:checked')).to_have_count(0)
    page.locator('#provider-scopes input').first.check();page.locator('#provider-oauth-consent').check()
    expect(page.locator('#provider-oauth-begin')).to_be_enabled()
    page.screenshot(path=str(OUT/'05-oauth-permissions.png'),full_page=True)
    page.locator('#provider-client').fill('public-client-id')
    expect(page.locator('#provider-oauth-consent')).not_to_be_checked()
    x.manager.http.close()


def test_workspace_chooser_dark_theme_and_blocked_candidate_guidance(connection_page):
    x,page=connection_page
    page.goto('https://customer.test/customer/provider-connections')
    # With one workspace the chooser opens that workspace's connections directly.
    expect(page).to_have_url('https://customer.test/customer/organizations/'+x.ws+'/connections')
    expect(page.locator('#provider-status')).to_contain_text('Choose an agent')
    expect(page.locator('.workspace-sidebar [aria-current=page]')).to_have_count(1)
    expect(page.locator('.workspace-sidebar [aria-current=page]')).to_have_text('Provider connections')
    # UI policy 11-01: on its own menu page the panel is part of the page, so the menu stays usable.
    expect(page.locator('#provider-close')).to_be_hidden()
    page.locator('#workspace-theme').click()
    expect(page.locator('#provider-dialog')).to_be_visible()
    page.locator('#provider-search').fill(str(x.rid));page.locator('#provider-search-form button').click()
    page.get_by_role('button',name='Connection options',exact=True).click()
    page.screenshot(path=str(OUT/'06-connections-dark.png'),full_page=True)
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
    expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
    manual(page)
    page.locator('[data-field=choice]').first.select_option(str(x.rid)+'|docs.search.v1')
    expect(page.locator('.provider-candidate-hint').first).to_contain_text('Provider authorization')
    expect(page.locator('#review')).to_be_disabled()
    page.get_by_role('button',name='Provider connection options',exact=True).first.click()
    expect(page.locator('#provider-name')).to_be_visible()
