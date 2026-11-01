"""Native sign-in/account UI with isolated API and synthetic provider pages."""
from http.cookies import SimpleCookie
from dataclasses import replace
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
import pytest

from agent_market.customer_identity import CustomerIdentity
from agent_market.customer_identity_service import router_for
from tests.test_customer_identity import customer, github_world
from tests.test_front_workflow_browser import browser


def page_for(w,browser):
    google=replace(w.core.config,redirect_uri='https://customer.test/api/customer-auth/callback') if w.core.config else None
    github=replace(w.core.github_config,redirect_uri='https://customer.test/api/customer-auth/github/callback') if w.core.github_config else None
    w.core=CustomerIdentity(w.store,b'synthetic-customer-key-32bytes!!!',google,w.core.http,github_config=github)
    app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
    client=TestClient(app,base_url='https://customer.test')
    context=browser.new_context();context.set_offline(True);page=context.new_page();errors=[];unexpected=[];requests=[]
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        requests.append((request.method,url.hostname,url.path))
        if url.hostname in ('accounts.google.com','github.com'):
            query=parse_qs(url.query)
            assert query['code_challenge_method']==['S256']
            provider='google' if url.hostname=='accounts.google.com' else 'github'
            if provider=='google':w.state['nonce']=query['nonce'][0]
            callback='/api/customer-auth/callback' if provider=='google' else '/api/customer-auth/github/callback'
            issuer='https://accounts.google.com' if provider=='google' else 'https://github.com/login/oauth'
            target='https://customer.test'+callback+'?'+urlencode({'code':'synthetic-code','state':query['state'][0],'iss':issuer})
            route.fulfill(status=200,content_type='text/html',body='<script>location.assign('+json.dumps(target)+')</script>')
            return
        if url.hostname!='customer.test':unexpected.append(request.url);route.abort();return
        response=client.request(request.method,url.path+('?' +url.query if url.query else ''),headers=request.headers,
                                content=request.post_data,follow_redirects=False)
        if response.status_code==404:errors.append('fixture404:'+request.method+':'+url.path)
        # Playwright fulfill accepts one string per header. Apply each original
        # cookie separately so two callback Set-Cookie fields are not collapsed.
        for value in response.headers.get_list('set-cookie'):
            jar=SimpleCookie();jar.load(value)
            for name,item in jar.items():
                if item['max-age']=='0':context.clear_cookies(name=name);continue
                context.add_cookies([{'name':name,'value':item.value,'url':'https://customer.test',
                    'secure':bool(item['secure']),'httpOnly':bool(item['httponly']),'sameSite':'Lax'}])
        if response.status_code==303:
            from agent_market.customer_navigation import destination
            target=response.headers['location']
            assert target == '/customer/sign-in' or destination(target) == target
            # A browser redirect chain can bypass a second route callback.
            # Keep native navigation local/offline with a fixture-only page.
            route.fulfill(status=200,content_type='text/html',body='<script>location.replace('+json.dumps('https://customer.test'+response.headers['location'])+')</script>')
        else:
            route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
                if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);page.on('pageerror',lambda error:errors.append(str(error)))
    return client,context,page,errors,unexpected,requests


@pytest.mark.parametrize('provider',['google','github'])
def test_native_customer_login_callback_account_and_logout(customer,browser,provider):
    w=customer;github_world(w)
    client,context,page,errors,unexpected,requests=page_for(w,browser)
    try:
        page.goto('https://customer.test/customer/sign-in')
        button=page.get_by_role('button',name='Sign in with '+('Google' if provider=='google' else 'GitHub'))
        expect(button).to_be_enabled()
        evidence=os.environ.get('WORKSPACE_LAUNCH_EVIDENCE_DIR')
        if evidence and provider=='google':
            folder=Path(evidence);folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/'sign-in-light.png'),full_page=True)
            page.emulate_media(color_scheme='dark')
            page.screenshot(path=str(folder/'sign-in-dark.png'),full_page=True)
            page.emulate_media(color_scheme='light')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(folder/'sign-in-mobile.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':720})
        button.click()
        page.wait_for_url('**/customer/workspaces')
        assert page.locator('#status').count(),str((requests,errors))
        expect(page.locator('#status')).to_contain_text('You are signed in.')
        expect(page.locator('#customer')).to_have_text('Your account is ready.')
        assert 'cu_' not in page.locator('body').inner_text()
        if evidence and provider=='google':page.screenshot(path=str(Path(evidence)/'signed-in.png'),full_page=True)
        assert page.locator('#workspaces li').count()==0
        assert all(value not in page.content() for value in ('never-copy@example.invalid','gho_synthetic_token','synthetic-google-server-secret','synthetic-github-server-secret'))
        expect(page.get_by_role('button',name='Sign out')).to_be_visible();page.get_by_role('button',name='Sign out').click()
        page.wait_for_url('**/customer/sign-in')
        assert client.get('/api/customer-auth/session').status_code==401
        assert not errors and not unexpected
        assert len([row for row in requests if row[0]=='POST' and row[2]=='/api/customer-auth/begin'])==1
    finally:context.close();client.close();w.github_http.close()


def test_unconfigured_native_signin_is_disabled_without_provider_or_admin_fallback(customer,browser):
    w=customer;w.core=CustomerIdentity(w.store,b'synthetic-customer-key-32bytes!!!')
    client,context,page,errors,unexpected,requests=page_for(w,browser)
    try:
        page.goto('https://customer.test/customer/sign-in')
        expect(page.locator('#status')).to_have_text('Customer sign-in is currently unavailable.')
        expect(page.get_by_role('button',name='Sign in with Google')).to_be_disabled()
        expect(page.get_by_role('button',name='Sign in with GitHub')).to_be_disabled()
        assert not w.state['calls'] and not errors and not unexpected
        assert not any('/admin/' in row[2] for row in requests)
    finally:context.close();client.close()


@pytest.mark.parametrize('provider',['google','github'])
def test_customer_can_retry_start_and_authenticated_and_guest_navigation_are_consistent(customer,browser,provider):
    w=customer;github_world(w)
    client,context,page,errors,unexpected,requests=page_for(w,browser)
    try:
        page.goto('https://customer.test/customer/sign-in')
        button=page.locator('#'+provider)
        expect(button).to_be_enabled()
        held=[]
        page.route('**/api/customer-auth/begin',lambda route:held.append(route),times=1)
        button.click()
        label='Google' if provider=='google' else 'GitHub'
        expect(button).to_have_text('Opening '+label+'…')
        expect(button).to_have_attribute('aria-busy','true')
        expect(button).to_be_disabled()
        expect(page.locator('#'+('github' if provider=='google' else 'google'))).to_be_disabled()
        expect(button.locator('.workspace-spinner')).to_be_visible()
        expect(button.locator('svg')).to_be_hidden()
        expect(page.locator('#workspace-progress')).to_be_hidden()
        assert button.evaluate("b=>getComputedStyle(b,'::before').display")=='none'
        button.dispatch_event('click')
        assert len(held)==1
        proof=Path('reports/workspace-login-feedback-2026-10-21')
        proof.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(proof/(provider+'-loading.png')),full_page=True)
        page.emulate_media(color_scheme='dark',reduced_motion='reduce')
        page.locator('#workspace-theme').click()
        expect(page.locator('body')).to_have_attribute('data-theme','dark')
        page.set_viewport_size({'width':390,'height':844})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert button.locator('.workspace-spinner').evaluate('n=>getComputedStyle(n).animationName')=='none'
        page.screenshot(path=str(proof/(provider+'-loading-mobile-dark.png')),full_page=True)
        held[0].fulfill(status=503,json={'error':'Unavailable'})
        expect(page.locator('#status')).to_have_text('Sign-in could not be started. Please try again.')
        expect(button).to_be_enabled()
        expect(button).to_have_text('Sign in with '+label)
        expect(button.locator('.workspace-spinner')).to_be_hidden()
        expect(button).not_to_have_attribute('aria-busy','true')
        page.screenshot(path=str(proof/(provider+'-retry.png')),full_page=True)
        button.click();page.wait_for_url('**/customer/workspaces')
        expect(page.locator('#status')).to_contain_text('You are signed in.')
        page.goto('https://customer.test/customer/sign-in')
        page.wait_for_url('**/customer/workspaces')
        expect(page.get_by_role('link',name='Manage workspaces and invitations')).to_be_visible()
        # Mobile navigation owns sign-out after the responsive header collapses.
        page.get_by_role('button',name='Open workspace navigation').click()
        page.get_by_role('button',name='Sign out').click();page.wait_for_url('**/customer/sign-in')
        page.goto('https://customer.test/customer/workspaces')
        page.wait_for_url('**/customer/sign-in')
        expect(button).to_be_enabled()
        assert not errors and not unexpected
        assert client.get('/api/customer-auth/session').status_code==401
    finally:context.close();client.close();w.github_http.close()
