"""Chromium journeys for truthful test states and strict connection display boundaries."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from agent_market.concierge.front import clear_front_caches
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser
from tests.test_managed_agent_gateway import managed, SOURCE, DOC

playwright=pytest.importorskip('playwright.sync_api')


@pytest.fixture
def gateway_page(browser,managed):
    store,front,client,add,rid,calls,remote=managed
    clear_front_caches()
    context=browser.new_context(accept_downloads=True)
    requests=[];errors=[];external=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='agentconcierge.biz':external.append(req.url);return route.abort()
        requests.append((req.method,url.path,req.post_data))
        response=client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,
                                headers={k:v for k,v in req.headers.items() if k in ('accept','content-type','x-visitor-token')})
        route.fulfill(status=response.status_code,body=response.content,
                      headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    yield page,requests,errors,external,rid
    context.close()


def test_default_demo_does_not_claim_live_success(gateway_page,managed,tmp_path):
    page,requests,errors,external,rid=gateway_page
    page.goto('https://agentconcierge.biz/#test')
    playwright.expect(page.locator('#tbAgentMetaBox')).to_contain_text('Demo')
    playwright.expect(page.locator('#tbAgentMetaBox')).to_contain_text('Not recorded')
    assert 'Guaranteed' not in page.locator('#secTest').inner_text()
    page.locator('#tbRunBtn').click()
    playwright.expect(page.locator('#tbKpiStatus')).to_have_text('Demo — not live')
    playwright.expect(page.locator('#tbOutputPre')).to_contain_text('No provider was contacted')
    playwright.expect(page.locator('#tbHistoryTbody')).to_contain_text('Demo')
    assert not managed[5]
    with page.expect_download() as download:
        page.evaluate('exportTestbenchHistory()')
    path=tmp_path/'history.json';download.value.save_as(path)
    data=json.loads(path.read_text())
    assert data['history'][0]['simulated'] is True
    assert data['history'][0]['execution_succeeded'] is False
    assert not errors and not external


def test_registered_agent_test_has_actual_wire_and_preserves_sources(gateway_page,managed,tmp_path):
    page,requests,errors,external,rid=gateway_page
    page.goto('https://agentconcierge.biz/#test')
    page.evaluate('id=>onTestbenchAgentChange(String(id))',rid)
    playwright.expect(page.locator('#tbToolSelect')).to_have_value('get_weather')
    # The exact JSON editor is an advanced, collapsed view in the published Test page.
    if not page.locator('#tbArgsEditor').is_visible() and page.locator('#uxRawArgs').count():
        page.locator('#uxRawArgs > summary').click()
    page.locator('#tbArgsEditor').fill('{"city":"Tokyo"}')
    page.locator('#tbRunBtn').click()
    playwright.expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    # Results are shown as readable cards; source URLs stay as links, not raw text.
    output=page.locator('#tbOutputPre').inner_html()
    assert SOURCE in output and DOC in output
    exchange=json.loads(page.locator('#tbRequestWirePre').text_content())
    actual=json.loads(next(body for method,path,body in requests if path=='/api/test/execute'))
    assert exchange['body']==actual and exchange['path']=='/api/test/execute'
    assert 'managed-weather.example' not in page.locator('#secTest').inner_text()
    assert len(managed[5])>0 and not errors and not external
    page.screenshot(path=str(Path('reports/managed-gateway-hardening-2026-10-17/testbench-completed.png').resolve()),full_page=False)


@pytest.mark.parametrize('url',['https://agentconcierge.biz.evil.example/path','https://agentconcierge.biz@evil.example/path',
 'https://user@agentconcierge.biz/path','https://agentconcierge.biz:8443/path','http://agentconcierge.biz/path'])
def test_browser_origin_validation_and_missing_connection(gateway_page,url):
    page,_,errors,external,_=gateway_page
    page.goto('https://agentconcierge.biz/#chat')
    assert page.evaluate('value=>isGatewayOrigin(value)',url) is False
    assert page.evaluate('isGatewayOrigin("https://agentconcierge.biz/api/gateway/mcp/1")') is True
    result=page.evaluate('''value=>{
      appendChatBubble('bot','',{data:{recommendations:[{name:'Unbound agent',kind:'mcp',url:value}]}});
      return gatewayAgentEndpoint({id:-1,kind:'mcp'});
    }''',url)
    assert result==''
    playwright.expect(page.locator('.chat-recommendation')).to_contain_text('Connection unavailable')
    assert page.locator('.chat-recommendation a').count()==0
    assert not errors and not external


def test_result_status_and_source_escaping_under_real_csp(gateway_page):
    page,_,errors,external,_=gateway_page
    page.goto('https://agentconcierge.biz/#test')
    page.evaluate('''() => {
      renderTestbenchResult({ok:false,status_code:200,task_status:'working',execution_succeeded:false,
        output:'Source: https://news.example/latest <img src=x onerror="window.__gatewayXss=1">',latency_ms:3});
      const script=document.createElement('script');script.textContent='window.__gatewayXss=1';document.body.append(script);
    }''')
    playwright.expect(page.locator('#tbKpiStatus')).to_have_text('working')
    playwright.expect(page.locator('#tbOutputPre')).to_contain_text('https://news.example/latest')
    assert page.locator('#tbOutputPre img').count()==0
    assert page.evaluate('window.__gatewayXss||0')==0
    assert not errors and not external


def test_obsolete_endpoint_cache_and_simulated_success_history_are_not_reused(gateway_page):
    page,_,errors,external,_=gateway_page
    page.add_init_script('''localStorage.setItem('concierge_swr_agent:1',JSON.stringify({name:'Obsolete private metadata',url:'https://old-upstream.example/rpc'}));
      localStorage.setItem('unrelated-preference','keep');
      sessionStorage.setItem('agent_testbench_history',JSON.stringify([{agent_name:'Old fake success',status_code:200,result:{ok:true}}]));''')
    page.goto('https://agentconcierge.biz/#test')
    playwright.expect(page.locator('#tbAgentMetaBox')).to_contain_text('Demo')
    assert page.evaluate('localStorage.getItem("concierge_swr_agent:1")') is None
    assert page.evaluate('localStorage.getItem("unrelated-preference")')=='keep'
    assert page.evaluate('sessionStorage.getItem("agent_testbench_history")') is None
    assert 'Old fake success' not in page.locator('#secTest').inner_text()
    assert not errors and not external
