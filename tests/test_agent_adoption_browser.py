"""Real-browser adoption markup and conditional API checks on isolated data."""
import re
from urllib.parse import urlsplit

from tests.test_agent_adoption import adoption,routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from agent_market.agent_access.storage import enqueue,transaction


def test_category_csp_escaping_and_compact_discovery_in_browser(adoption,browser):
    core,v,ids,calls,modes,client,*_=adoption
    attack='Documentation <img src=x onerror="window.adoptionXss=1">'
    with transaction(core.front.store)as db:
        db.execute('UPDATE resources SET name=? WHERE id=?',(attack,ids[0]))
        enqueue(core.front.store,db,ids[0],'fixture',evidence='browser')
    core.events.publish()
    context=browser.new_context();page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='agentconcierge.biz':route.abort();return
        response=client.request(request.method,url.path+('?' +url.query if url.query else''),
            content=request.post_data,headers=request.headers)
        headers={k:v for k,v in response.headers.items()if k not in ('content-length','content-encoding','transfer-encoding')}
        route.fulfill(status=response.status_code,body=response.content,headers=headers)
    context.route('**/*',serve)
    try:
        response=page.goto('https://agentconcierge.biz/agents/category/dev_tools')
        assert response.status==200 and response.headers['content-security-policy']
        assert page.locator('html').get_attribute('lang')=='en'
        assert page.locator('main img, main [onerror]').count()==0
        assert page.evaluate('window.adoptionXss||0')==0
        assert not re.search('[\uac00-\ud7af]',page.locator('body').inner_text())
        result=page.evaluate('''async()=>{
            const first=await fetch('/api/feed/verified.json?protocol=mcp');
            const second=await fetch('/api/feed/verified.json?protocol=mcp',{headers:{'If-None-Match':first.headers.get('etag')}});  // 11-13: a shared public read, its ETag is already weak
            const found=await fetch('/api/agent/v1/discover',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({task:'public documentation search',protocol:'mcp'})});
            return {first:first.status,second:second.status,found:found.status,text:await found.text()};
        }''')
        assert (result['first'],result['second'],result['found'])==(200,304,200)
        assert 'primary.example'not in result['text']and not errors and not calls
    finally:context.close()


def test_server_pages_have_no_console_errors_in_a_fresh_tab(adoption,browser):
    """11-11: each server-made public page opens in a new context with zero console errors (CSP blocks included)."""
    core,v,ids,calls,modes,client,*_=adoption
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='agentconcierge.biz':route.abort();return
        response=client.request(request.method,url.path+('?' +url.query if url.query else''),
            content=request.post_data,headers=request.headers)
        headers={k:v for k,v in response.headers.items()if k not in ('content-length','content-encoding','transfer-encoding')}
        route.fulfill(status=response.status_code,body=response.content,headers=headers)
    failures={}
    for path in ('/agents/category/dev_tools','/agents/tasks','/connect'):
        context=browser.new_context();page=context.new_page();errors=[]
        page.on('console',lambda message,errors=errors:message.type=='error' and errors.append(message.text))
        page.on('pageerror',lambda error,errors=errors:errors.append(str(error)))
        context.route('**/*',serve)
        try:
            response=page.goto('https://agentconcierge.biz'+path)
            assert response.status==200,path
            page.wait_for_load_state('load')
            if errors:failures[path]=errors  # a CSP-blocked stylesheet is reported here as a console error
        finally:context.close()
    assert not failures,failures
