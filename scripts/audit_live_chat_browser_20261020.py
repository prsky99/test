"""One authorized browser Chat request through the existing local service.

Async relay preserves frontend timers; no new web server or identity is created
outside normal anonymous Chat behavior. Visitor headers are never serialized.
"""
import asyncio
import json
from urllib.parse import urlsplit

import httpx
from playwright.async_api import async_playwright
from scripts.audit_frontend_ux_20261020 import OUT,ORIGIN,INSPECT


async def main():
    evidence={'scope':'actual browser and actual operating backend via async same-origin relay; deployment edge not exercised',
              'requests':[],'screens':[],'errors':[],'visitor_tokens_stored':False}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8400',timeout=40) as service, async_playwright() as runtime:
        browser=await runtime.chromium.launch(headless=True)
        context=await browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        await context.add_init_script("localStorage.setItem('agent_cookie_consent_v2',JSON.stringify({analytics:false,marketing:false,essential:true,timestamp:Date.now()}))")
        async def relay(route):
            req=route.request;u=urlsplit(req.url)
            if u.hostname!='agentconcierge.biz':return await route.abort()
            if req.method not in ('GET','HEAD') and not (req.method=='POST' and u.path=='/chat'):
                return await route.fulfill(status=403,json={'detail':'Audit action not authorized.'})
            try:
                response=await service.request(req.method,u.path+('?' +u.query if u.query else ''),content=req.post_data,
                    headers={k:v for k,v in req.headers.items() if k in ('accept','content-type','origin','x-visitor-token')})
                if u.path=='/chat':evidence['requests'].append({'method':req.method,'path':u.path,'http_status':response.status_code})
                await route.fulfill(status=response.status_code,body=response.content,
                    headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding','set-cookie')})
            except Exception as exc:
                evidence['errors'].append({'path':u.path,'type':type(exc).__name__})
                try:await route.abort()
                except Exception:pass
        await context.route('**/*',relay)
        page=await context.new_page()
        await page.goto(ORIGIN+'/new/en/chat.html',wait_until='domcontentloaded',timeout=60000)
        await page.locator('#chatInput').wait_for()
        await page.locator('.pearl-chat-protocol [data-value="mcp"]').click()
        await page.locator('#chatInput').fill('Find an MCP agent for searching official software documentation with sources.')
        async def capture(name):
            row=await page.evaluate(INSPECT);row.update(name=name,device='desktop',screenshot='evidence/'+name+'.png')
            await page.screenshot(path=str(OUT/row['screenshot']),full_page=True)
            evidence['screens'].append(row)
            (OUT/'live-chat-browser.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        await capture('live-chat-before-submit')
        await page.locator('#chatSubmit').click()
        await page.wait_for_timeout(1000);await capture('live-chat-request-in-progress')
        await page.wait_for_timeout(10000);await capture('live-chat-after-client-time-budget')
        evidence['visible_status']=await page.locator('#chatStatus').inner_text()
        evidence['input_after_request']=await page.locator('#chatInput').input_value()
        evidence['submit_disabled']=await page.locator('#chatSubmit').is_disabled()
        await page.wait_for_timeout(15000)
        await capture('live-chat-final-observed-state')
        (OUT/'live-chat-browser.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        await browser.close()
    print(json.dumps({'status':evidence.get('visible_status'),'submit_disabled':evidence.get('submit_disabled'),'requests':evidence['requests'],'errors':evidence['errors']}))


if __name__=='__main__':asyncio.run(main())
