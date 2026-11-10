"""Real Chromium interactions through disposable apps; no operating writes."""
# ruff: noqa: F811 -- imported pytest fixtures.
import json
import time

import pytest
from playwright.sync_api import expect
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_customer_identity import customer  # noqa: F401


@pytest.mark.parametrize('width',[390,1366])
def test_cookie_focus_and_delayed_chat_stay_stable(chat_page,width,request):
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':width,'height':844})
    page.add_init_script("window.__shifts=[];window.__shiftNodes=[];new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput){window.__shifts.push(e.value);window.__shiftNodes.push(e.sources.map(s=>({node:s.node?.id||s.node?.className||s.node?.tagName,old:s.previousRect,new:s.currentRect})))}})).observe({type:'layout-shift',buffered:true});")
    page.goto('https://agentconcierge.biz/#explore')
    page.evaluate("document.querySelector('#cookieConsentBanner').classList.remove('hidden')")
    page.wait_for_timeout(150);page.locator('#xGo').focus();page.wait_for_timeout(100)
    # 11-11: the strip sits in the page flow above the header (PM decision A); the focused control is never under it.
    visible=page.evaluate("()=>{const r=document.querySelector('#xGo').getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,Math.min(r.top+r.height/2,innerHeight-1));return !!hit&&!hit.closest('#cookieConsentBanner')}")
    assert visible
    page.screenshot(path='reports/feature-remediation-2026-10-29/cookie-focus-'+str(width)+'-'+request.node.callspec.params['chat_page']+'.png')
    page.evaluate("document.querySelector('#cookieConsentBanner').classList.add('hidden')")
    page.goto('https://agentconcierge.biz/#chat');page.wait_for_timeout(400)
    assert not errors,errors
    assert page.locator('#chatInput').is_visible(),page.evaluate('({hash:location.hash,tab:currentTab,types:typeof TABS,section:document.querySelector("#secChat").className,loaded:!!document.querySelector("#publicExperienceRuntime")})')
    before=page.locator('#chatForm').bounding_box()
    def delayed(route):time.sleep(1.1);route.fallback()
    page.route('**/chat',delayed)
    page.locator('#chatInput').fill('weather forecast');page.locator('#chatInput').press('Enter')
    expect(page.locator('.chat-recommendation')).to_have_count(3)
    after=page.locator('#chatForm').bounding_box()
    assert abs(before['y']-after['y'])<2,(before,after)
    assert sum(page.evaluate('window.__shifts'))<.1,(page.evaluate('window.__shiftNodes'),page.locator('#chatMessages').evaluate('(e)=>({h:e.clientHeight,s:e.scrollHeight,overflow:getComputedStyle(e).overflow,display:getComputedStyle(e).display})'))
    expect(page.locator('#chatSubmit')).to_be_enabled()
    page.wait_for_timeout(250)
    from pathlib import Path
    Path('reports/feature-remediation-2026-10-29/cls-'+str(width)+'-'+request.node.callspec.params['chat_page']+'.json').write_text(json.dumps({'isolated':True,'delayed_response_ms':1100,'cls_sum':sum(page.evaluate('window.__shifts')),'composer_y_before':before['y'],'composer_y_after':after['y']})+'\n')
    page.screenshot(path='reports/feature-remediation-2026-10-29/chat-stable-'+str(width)+'-'+request.node.callspec.params['chat_page']+'.png',full_page=True)
    assert not errors,errors


def test_suggestions_comparison_share_and_feedback_reason(chat_page,catalog,request):
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':390,'height':844})
    page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>{window.__copiedPublicLink=t}}})")
    page.goto('https://agentconcierge.biz/#explore');page.locator('#xQ').fill('gi')
    expect(page.locator('#xQ')).to_have_attribute('aria-expanded','true')
    page.locator('#xQ').press('ArrowDown');expect(page.locator('#xQ')).to_have_attribute('aria-activedescendant','agentTaskOption-0')
    page.locator('#xQ').press('Escape');expect(page.locator('#agentTaskSuggestions')).to_be_hidden()
    page.goto('https://agentconcierge.biz/#chat');page.locator('#chatInput').fill('weather forecast');page.locator('#chatInput').press('Enter')
    cards=page.locator('.chat-recommendation');expect(cards).to_have_count(3)
    assert not errors,errors
    assert cards.first.locator('.chat-provider-description').count(),(page.url,page.locator('script[src*=experience]').count(),page.locator('script[src*=operating]').count(),page.locator('.chat-recommendation').first.inner_text()[:100],page.evaluate('appendChatBubble.toString().slice(0,200)'))
    expect(cards.first.get_by_text('Provider description',exact=True)).to_be_visible()
    cards.first.get_by_role('button',name='Share agent',exact=True).click()
    url=page.evaluate('window.__copiedPublicLink');assert 'agents=' in url and 'vt_' not in url and 'weather' not in url
    cards.first.get_by_role('button',name='Add to comparison',exact=True).click()
    page.locator('.chat-alternatives > summary').click();cards.nth(1).get_by_role('button',name='Add to comparison',exact=True).click()
    cards.nth(1).get_by_role('button',name='Compare selected',exact=True).click()
    expect(page.locator('#agentComparison table')).to_be_visible()
    assert page.locator('#agentComparison th[scope=col]').count()==3
    assert page.evaluate('document.documentElement.scrollWidth')<=391
    page.screenshot(path='reports/feature-remediation-2026-10-29/compare-'+request.node.callspec.params['chat_page']+'.png',full_page=True)
    page.locator('#agentComparison').evaluate('(e)=>e.hidden=true')
    cards.first.get_by_role('button',name='Worked',exact=True).click()
    cards.first.get_by_label('What happened? (optional)').select_option('matched_task')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/chat')) as feedback:
        cards.first.get_by_role('button',name='Send feedback',exact=True).click()
    assert feedback.value.status==200
    expect(page.locator('#chatSubmit')).to_be_enabled()
    store=catalog[0]
    assert any('matched_task' in (r['data'] or '') for r in store.query('SELECT data FROM agent_messages'))
    assert not errors,errors


def test_cached_string_has_retrieval_time_and_gateway_label(chat_page):
    page,_,_,errors,_=chat_page;page.goto('https://agentconcierge.biz/#test')
    result={'output':json.dumps({'structuredContent':{'retrieved_at':'2026-10-28T05:21:00Z','cache':{'status':'fresh_cache'},'data':{'items':[]}}}),'latency_ms':405.6,'client_total_ms':931,'tested_at':1793250000,'execution_succeeded':True,'simulated':False,'protocol':'mcp','task_status':'succeeded','status_code':200}
    page.evaluate('(data)=>renderTestbenchResult(data)',result)
    expect(page.locator('#tbKpiLatency')).to_contain_text('gateway')
    expect(page.locator('#tbKpiLatency')).not_to_contain_text('agent')
    expect(page.locator('#tbKpiTime')).to_contain_text('05:21:00')
    expect(page.locator('#tbKpiTime')).to_contain_text('(cached)')
    assert not errors,errors


def test_webmcp_discovery_tools_preserve_session_and_abort(chat_page,request):
    page,requests,_,errors,_=chat_page
    page.add_init_script("window.__nativeTools={};Object.defineProperty(document,'modelContext',{value:{registerTool:(tool,options)=>{window.__nativeTools[tool.name]={tool,signal:options.signal}}}})")
    page.goto('https://agentconcierge.biz/#chat')
    # 11-11: the published page adds inspect_agent (reads one public record, never contacts the provider);
    # the legacy fallback page keeps the two discovery tools.
    published=request.node.callspec.params['chat_page']=='published'
    expected=['inspect_agent','recommend_agents','search_agents'] if published else ['recommend_agents','search_agents']
    assert page.evaluate('Object.keys(window.__nativeTools).sort()')==expected
    assert page.evaluate('window.__nativeTools.search_agents.tool.annotations.readOnlyHint') is True
    if published:
        assert page.evaluate('window.__nativeTools.inspect_agent.tool.annotations.readOnlyHint') is True
        assert page.evaluate("window.__nativeTools.inspect_agent.tool.execute({agent_id:0})")['error']
    assert page.evaluate('window.__nativeTools.recommend_agents.tool.annotations.readOnlyHint') is False
    before=len(requests)
    assert page.evaluate("window.__nativeTools.search_agents.tool.execute({query:'x'})")['error']
    assert len(requests)==before
    found=page.evaluate("window.__nativeTools.search_agents.tool.execute({query:'weather',protocol:'mcp'})")
    assert found['items'] and all(item['kind']=='mcp' for item in found['items'])
    if published:
        inspected=page.evaluate("id=>window.__nativeTools.inspect_agent.tool.execute({agent_id:id})",found['items'][0]['id'])
        assert inspected['id']==found['items'][0]['id'] and inspected['execution_performed'] is False,inspected
    reply=page.evaluate("window.__nativeTools.recommend_agents.tool.execute({task:'weather forecast',protocol:'mcp'})")
    assert len(reply['recommendations'])==3 and 'visitor' not in reply
    assert page.evaluate("!!sessionStorage.getItem('visitorToken')&&activeVisitorToken===sessionStorage.getItem('visitorToken')")
    aborted=page.evaluate("""async()=>{const c=new AbortController();c.abort();try{await window.__nativeTools.search_agents.tool.execute({query:'weather'},{signal:c.signal});return false}catch(e){return e.name==='AbortError'}}""")
    assert aborted
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    assert page.evaluate('Object.values(window.__nativeTools).every(x=>x.signal.aborted)')
    assert not errors,errors


@pytest.mark.parametrize('width',[390,1366])
@pytest.mark.parametrize('theme',['light','dark'])
def test_changed_widgets_have_no_serious_accessibility_errors(chat_page,width,theme):
    from pathlib import Path
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':width,'height':844})
    page.add_init_script("localStorage.setItem('theme',"+json.dumps(theme)+")")
    page.emulate_media(color_scheme=theme)
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate("theme=>{document.documentElement.dataset.theme=theme;document.body.dataset.theme=theme;document.documentElement.classList.toggle('dark',theme==='dark')}",theme)
    page.locator('#chatInput').fill('weather forecast');page.locator('#chatSubmit').click()
    expect(page.locator('.chat-recommendation')).to_have_count(3)
    expect(page.locator('#chatSubmit')).to_be_enabled();page.wait_for_timeout(250)
    page.evaluate(Path('gateway-data/feature-recheck-2026-10-29/axe.min.js').read_text())
    result=page.evaluate("async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}});return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))}")
    Path('reports/feature-remediation-2026-10-29/axe-'+str(width)+'-'+theme+'-'+('published' if page.locator('script[src*=experience]').count() else 'legacy')+'.json').write_text(json.dumps(result,indent=2))
    assert not result,result
    assert page.evaluate('document.documentElement.scrollWidth')<=width+1
    assert not errors,errors


def test_published_menu_accessibility_matrix(chat_page,catalog,customer,request):
    from pathlib import Path
    if request.node.callspec.params['chat_page']!='published':pytest.skip('Published-page matrix; retained widgets have separate coverage.')
    page,_,_,errors,_=chat_page
    from agent_market.customer_identity_service import router_for
    catalog[2].app.include_router(router_for(customer.store,b'synthetic-customer-key-32bytes!!!',identity=customer.core))
    axe_source=Path('gateway-data/feature-recheck-2026-10-29/axe.min.js').read_text()
    routes=['/','/new/en/explore.html','/new/en/chat.html','/new/en/test.html','/new/en/workflows.html','/new/en/learn.html','/new/en/agent-status.html','/new/en/list-agent.html','/new/en/about.html','/customer/sign-in']
    results=[]
    for mode,width,height,theme in [('desktop',1366,900,'light'),('mobile',390,844,'light'),('w320',320,640,'light'),('dark',1366,900,'dark')]:
        page.set_viewport_size({'width':width,'height':height});page.emulate_media(color_scheme=theme)
        page.add_init_script('localStorage.setItem("theme",'+json.dumps(theme)+')')
        for route in routes:
            response=page.goto('https://agentconcierge.biz'+route);page.wait_for_timeout(300)
            page.evaluate(axe_source)
            findings=page.evaluate("async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice']}});return r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))}")
            entry={'mode':mode,'path':route,'status':response.status,'overflow':page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth'),'findings':findings}
            results.append(entry)
    Path('reports/feature-remediation-2026-10-29/isolated-ui-matrix.json').write_text(json.dumps(results,indent=2)+'\n')
    assert len(results)==40
    assert not [r for r in results if r['status']>=400 or r['overflow']>1 or any(v['impact'] in ('serious','critical') for v in r['findings'])],results
    assert not errors,errors
