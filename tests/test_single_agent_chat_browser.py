"""Exercise the one-agent chat with real CSP, HTTP routing, and rendered evidence."""
import json
from urllib.parse import urlsplit

import pytest
from agent_market.concierge.front import clear_front_caches
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright=pytest.importorskip('playwright.sync_api')


@pytest.fixture(params=['legacy', 'published'])
def chat_page(browser,catalog,monkeypatch,request):
    if request.param == 'legacy':
        from agent_market.concierge import pearl_view
        monkeypatch.setattr(pearl_view, 'public_page_available', lambda: False)
    store,front,client,add,now=catalog
    clear_front_caches()
    best=add('Verified Weather A',report_at=now-60)
    add('Older Weather B',grade='B',report_at=now-120)
    add('Third Weather C',grade='C',report_at=now-180)
    context=browser.new_context()
    context.add_init_script("localStorage.setItem('agent_cookie_consent_v2',JSON.stringify({analytics:false,marketing:false,essential:true,timestamp:Date.now()}))")
    errors=[];requests=[];bodies=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='agentconcierge.biz':
            route.abort();return
        requests.append((req.method,url.path))
        res=client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,
                           headers={k:v for k,v in req.headers.items() if k in ('accept','content-type','x-visitor-token')})
        if req.method=='POST' and url.path=='/chat':
            # The page asks for the progress stream; its last event carries the plain answer.
            stream=[json.loads(b[6:]) for b in res.text.split('\n\n') if b.startswith('data: ')]
            bodies.append(stream[-1].get('body',stream[-1]) if stream else res.json())
        route.fulfill(status=res.status_code,body=res.content,
                      headers={k:v for k,v in res.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    yield page,requests,bodies,errors,best
    context.close()


def test_one_quality_first_card_and_calling_details(chat_page, request):
    page,requests,bodies,errors,best=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    heading = 'Three relevant agents' if request.node.callspec.params['chat_page'] == 'legacy' else 'Start with the right agent.'
    playwright.expect(page.locator('#secChat h1')).to_have_text(heading)
    assert page.locator('#chatInput').get_attribute('data-clarity-mask')=='true'
    assert page.locator('#chatVisitorTier').count()==0
    page.locator('#chatInput').fill('무료 MCP 날씨 에이전트 추천해줘')
    page.locator('#chatSubmit').click()
    card=page.locator('#chatMessages .chat-recommendation')
    playwright.expect(card).to_have_count(3)
    playwright.expect(card.first).to_contain_text('Verified Weather A')
    playwright.expect(card.first).to_contain_text('Test report:')
    playwright.expect(card.first).to_contain_text('Active checked:')
    playwright.expect(card.first).to_contain_text('forecast')
    assert bodies[0]['data']['recommendations'][0]['id']==best
    assert len(bodies[0]['data']['recommendations'])==3
    assert ('GET','/me') not in requests
    playwright.expect(page.locator('#chatSubmit')).to_be_enabled()
    assert 'Pro SLA' not in page.locator('#secChat').inner_text()
    card.first.get_by_role('button',name='Calling details').click()
    playwright.expect(page.locator('#drawer')).to_be_visible()
    playwright.expect(page.locator('#drawerContent')).to_contain_text('Verified Weather A')
    page.locator('#closeDrawer').click()
    page.locator('.chat-alternatives > summary').click()
    for index,expected in [(1,'Older Weather B'),(2,'Third Weather C')]:
        card.nth(index).get_by_role('button',name='Calling details').click()
        playwright.expect(page.locator('#drawerContent')).to_contain_text(expected)
        page.locator('#closeDrawer').click()
    page.screenshot(path='reports/discovery-three-recommendations-2026-10-25/three-agent-cards-'+request.node.callspec.params['chat_page']+'.png',full_page=True)
    assert not errors


def test_multi_result_response_is_rendered_up_to_three(chat_page):
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate('''() => appendChatBubble('bot','', {data:{recommendations:[
        {id:1,name:'First',kind:'mcp',url:'https://first.example/mcp',active_checked_at:1e30},
        {id:2,name:'Second',kind:'mcp',url:'https://second.example/mcp'}]}})''')
    playwright.expect(page.locator('.chat-recommendation')).to_have_count(2)
    playwright.expect(page.locator('.chat-recommendation').first).to_contain_text('First')
    assert not errors


def test_all_recommendation_card_fields_are_escaped(chat_page):
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    attack='<img src=x onerror="window.__singleXss=1">'
    page.evaluate('''attack=>appendChatBubble('bot','',{data:{recommendations:[{
        id:attack,name:attack,kind:attack,description:attack,grade:attack,quality_score:attack,
        url:'javascript:window.__singleXss=1',tools:[attack],auth_required:true,auth_method:attack,
        test_report:{id:attack,created_at:1,success:true},active_checked_at:1}]}})''',attack)
    card=page.locator('.chat-recommendation')
    playwright.expect(card).to_have_count(1)
    assert card.locator('img,[onerror],a[href^="javascript:"]').count()==0
    assert page.evaluate('window.__singleXss||0')==0 and not errors


def test_schema_credentials_do_not_reach_browser_response_json(chat_page,catalog):
    store,_,_,_,_=catalog
    secret='audit-browser-placeholder-not-a-real-secret'
    guide={'tools':[{'name':'forecast','inputSchema':{'type':'object','properties':{'api_key':{'type':'string','default':secret}},'required':['api_key']}}]}
    with store.tx() as db:
        db.execute("UPDATE resources SET usage_guide=?,usage_tools=?,usage_full_tools=?",
                   (json.dumps(guide),json.dumps(guide['tools']),json.dumps(guide['tools'])))
    page,_,bodies,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('.chat-recommendation')).to_have_count(3)
    response=json.dumps(bodies[-1])
    assert secret not in response and 'api_key' in response
    assert page.locator('#chatOutput').count()==0 and not errors


def test_chat_input_autofocuses_on_open_and_tab_switch(chat_page):
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    playwright.expect(page.locator('#chatInput')).to_be_focused()
    composer = page.locator('.pearl-inline-composer')
    if composer.count():
        indicator = composer.evaluate('el => ({width:parseFloat(getComputedStyle(el).borderTopWidth),shadow:getComputedStyle(el).boxShadow})')
        assert indicator['width'] >= 1 and indicator['shadow'] != 'none'
    else:
        border_width=page.locator('#chatInput').evaluate('el => parseFloat(getComputedStyle(el).borderTopWidth)')
        assert border_width>=1.0
    page.keyboard.type('MCP weather forecast')
    assert page.locator('#chatInput').input_value()=='MCP weather forecast'
    page.locator('a.brand-box').click()
    playwright.expect(page.locator('#secOverview')).to_be_visible()
    page.locator('.nav-tab[data-tab="chat"]').click()
    playwright.expect(page.locator('#secChat')).to_be_visible()
    playwright.expect(page.locator('#chatInput')).to_be_focused()
    assert not errors



def test_cached_x402_is_hidden_until_explicit_selection(chat_page,catalog):
    _,_,client,add,now=catalog
    identity=add('Explicit x402 Weather',kind='x402',report_at=now-1)
    xcard=client.get('/api/explore',params={'kind':'x402','q':'weather'}).json()['items'][0]
    mcard=client.get('/api/explore',params={'kind':'mcp','q':'weather'}).json()['items'][0]
    assert xcard['id']==identity
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#explore')
    playwright.expect(page.locator('#xResults')).to_contain_text('Weather')
    page.evaluate('cards=>{document.getElementById("xKind").value="";renderExplore(cards,"",2)}',[xcard,mcard])
    playwright.expect(page.locator('#xResults')).not_to_contain_text('Explicit x402 Weather')
    page.evaluate('cards=>{document.getElementById("xKind").value="x402";renderExplore(cards,"",2)}',[xcard,mcard])
    playwright.expect(page.locator('#xResults')).to_contain_text('Explicit x402 Weather')
    page.evaluate('cards=>{document.getElementById("xKind").value="";renderExplore(cards,"x402 weather",2)}',[xcard,mcard])
    playwright.expect(page.locator('#xResults')).to_contain_text('Explicit x402 Weather')
    assert not errors


def test_feedback_names_the_card_and_stop_keeps_the_question(chat_page):
    page,requests,bodies,errors,best=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('weather forecast')
    page.locator('#chatSubmit').click()
    card=page.locator('#chatMessages .chat-recommendation')
    playwright.expect(card).to_have_count(3)
    card.first.get_by_role('button',name='Worked').click()
    playwright.expect(card.first.get_by_label('What happened? (optional)')).to_be_visible()
    card.first.get_by_role('button',name='Send feedback',exact=True).click()
    playwright.expect(card.first.get_by_role('button',name='Worked')).to_be_disabled()
    playwright.expect(page.locator('#chatMessages .chat-bubble.bot')).to_have_count(3)
    assert bodies[-1]['intent']=='outcome' and bodies[-1]['data']['success'] is True
    # A later answer disables feedback on earlier lists, which no longer match the latest positions.
    page.locator('#chatInput').fill('translate text')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatMessages .chat-bubble.bot')).to_have_count(4)
    playwright.expect(card.first.get_by_role('button',name="Didn't work")).to_be_disabled()
    # Stop cancels the pending request and restores the question.
    page.route('**/chat', lambda route: None)  # never answers
    page.locator('#chatInput').fill('research papers on agents')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatStop')).to_be_visible()
    page.locator('#chatStop').click()
    playwright.expect(page.locator('#chatInput')).to_have_value('research papers on agents')
    playwright.expect(page.locator('#chatStop')).to_be_hidden()
    assert not errors


@pytest.mark.parametrize('chat_page',['published'],indirect=True)
def test_progress_steps_show_in_the_conversation_then_give_way_to_the_answer(chat_page):
    """A stream's steps are listed beside the request with elapsed time; the composer stays usable."""
    page,requests,bodies,errors,best=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate("""() => { const view = chatProgressView(null);
        view.step({label:'Reading your request', elapsed_ms:40});
        view.step({label:'Searching active agents', elapsed_ms:1250}); }""")
    box=page.locator('#chatMessages .chat-progress')
    playwright.expect(box).to_have_attribute('role','status')
    playwright.expect(box.locator('li.done')).to_have_text(['Reading your request0.0s'])
    playwright.expect(box.locator('li[aria-current="step"]')).to_have_text('Searching active agents1.3s')
    page.evaluate("document.querySelector('#chatMessages .chat-progress').remove()")
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatMessages .chat-bubble.bot').first).to_contain_text('Verified Weather A')
    playwright.expect(page.locator('#chatMessages .chat-progress')).to_have_count(0)
    assert [item['id'] for item in bodies[-1]['data']['recommendations']][:1]==[best]
    assert errors==[]
