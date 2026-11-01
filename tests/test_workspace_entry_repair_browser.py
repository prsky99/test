"""Offline Chromium verifies first-visit copy, return navigation and expiry."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_customer_identity import customer  # noqa: F401
from tests.test_customer_identity_browser import page_for
from tests.test_front_workflow_browser import browser  # noqa: F401


@pytest.mark.parametrize('inherited_fragment',[False,True])
def test_sign_in_has_no_expected_401_and_preserves_destination_through_refresh_and_oauth(customer, browser,inherited_fragment):
    client, context, page, errors, unexpected, requests = page_for(customer, browser)
    console=[]; statuses=[]
    page.on('console',lambda message:console.append(message.text) if message.type=='error' else None)
    page.on('response',lambda response:statuses.append(response.status))
    target='/customer/workspaces?workspace=ws_'+'a'*32+'#detail'
    try:
        from urllib.parse import urlencode
        source = 'https://customer.test/customer/sign-in?'+urlencode({'next':target.split('#')[0] if inherited_fragment else target})
        page.goto(source+('#detail' if inherited_fragment else ''))
        expect(page.locator('#google')).to_be_enabled()
        expect(page.locator('#status')).to_have_text('Choose a sign-in provider.')
        page.reload()
        expect(page.locator('#google')).to_be_enabled()
        page.locator('#google').click()
        page.wait_for_url('https://customer.test'+target)
        expect(page.locator('#status')).to_contain_text('You are signed in.')
        assert not console and not errors and not unexpected and 401 not in statuses
    finally:
        context.close();client.close()


@pytest.mark.parametrize('previously_authenticated',[False,True])
def test_guest_and_expired_navigation_are_distinct_and_preserve_context(browser,previously_authenticated):
    context=browser.new_context();context.set_offline(True);page=context.new_page();sent=[]
    target='/customer/organizations?workspace=ws_'+'a'*32+'#detail'
    def serve(route):
        assert urlsplit(route.request.url).hostname=='customer.test'
        route.fulfill(content_type='text/html',body='<main><h1>Local sign-in fixture</h1><button id="read">Read</button></main>')
    context.route('**/*',serve)
    try:
        page.goto('https://customer.test'+target)
        page.evaluate("""()=>{window.sent=[];window.fetch=async(path,options)=>{sent.push({path,method:options.method||'GET'});return new Response('{}',{status:401})}}""")
        page.add_script_tag(content=Path('new/live-assets/workspace-interactions.js').read_text())
        if previously_authenticated:page.evaluate("document.dispatchEvent(new Event('workspace-session-ready'))")
        page.evaluate("document.getElementById('read').onclick=()=>workspaceUI.request('/api/customer-support/cases')")
        page.locator('#read').click()
        page.wait_for_url('**/customer/sign-in?*')
        query=parse_qs(urlsplit(page.url).query)
        assert query['next']==[target]
        assert query.get('result')==(['expired'] if previously_authenticated else None)
    finally:context.close()
