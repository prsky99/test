"""Registration consent and unconfirmed-protocol UX on both public presentations."""
import json
from pathlib import Path

import pytest
from tests.test_single_agent_chat_browser import chat_page
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser

playwright=pytest.importorskip('playwright.sync_api')


def test_public_registration_consent_and_unconfirmed_protocol(chat_page,catalog,monkeypatch,request):
    page,requests,bodies,errors,_=chat_page
    store,front,client,_,_=catalog
    sent=[]
    monkeypatch.setattr('agent_market.concierge.registration_policy._resolve_addresses',lambda *a:['8.8.8.8'])
    monkeypatch.setattr('agent_market.concierge.front.inspect_register_url',lambda *a,**k:{'ok':True,'protocol_verified':False,'url':'https://public.example/mcp','kind':None,'name':'','description':'','details':{}})
    page.goto('https://agentconcierge.biz/#register')
    if page.locator('.pearl-registration-import').count():page.locator('.pearl-registration-import > summary').click()
    page.locator('#regAutoUrl').fill('https://public.example/mcp')
    page.locator('#regInspectBtn').click()
    playwright.expect(page.locator('#regBanner')).to_contain_text('Protocol not confirmed')
    assert not errors
    page.locator('#regKind').select_option('mcp')
    page.locator('#regUrl').fill('https://public.example/mcp')
    page.locator('#regName').fill('QA isolated protocol')
    page.locator('#regDesc').fill('Find public documentation for this isolated test.')
    page.locator('#regTermsConsent').check()
    if page.locator('#pearlRegAuthority').count():page.locator('#pearlRegAuthority').check()
    def submit(route):
        sent.append(route.request.post_data_json)
        response=client.post('/api/register',json=route.request.post_data_json)
        route.fulfill(status=response.status_code,content_type='application/json',body=response.content)
    page.route('**/api/register',submit)
    page.locator('#regSubmitBtn').click()
    playwright.expect(page.locator('#regBanner')).to_contain_text('Registration rejected')
    assert sent[-1]['legal_consent']['agreed'] is True
    assert not store.query("SELECT id FROM resources WHERE name=?",('QA isolated protocol',))
    assert not errors
    target=Path('reports/registration-hardening-2026-10-27');target.mkdir(exist_ok=True)
    page.screenshot(path=str(target/('registration-'+request.node.callspec.params['chat_page']+'.png')),full_page=True)
