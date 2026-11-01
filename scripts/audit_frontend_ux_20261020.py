"""Read-only visual inventory of the already-running public service.

Chromium opens the public deployment directly. No application server is started,
no customer identity is impersonated and non-read requests are blocked.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/frontend-ux-ai-review-2026-10-20'
ORIGIN = 'https://agentconcierge.biz'
PAGES = ['index', 'agent-status', 'explore', 'test', 'workflows', 'chat',
         'list-agent', 'learn', 'about', 'terms', 'privacy', 'service-disclosures',
         'accessibility', 'contact', 'cookies', 'privacy-choices', 'notifications',
         'task-updates', 'feedback', 'agent-reports', 'webapp', 'sign-in', 'sign-up',
         'workspace']
INSPECT = r'''() => {
 const visible=e=>!!(e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
 const rect=e=>{const r=e.getBoundingClientRect();return {x:Math.round(r.x),y:Math.round(r.y+scrollY),width:Math.round(r.width),height:Math.round(r.height)}};
 const info=e=>({tag:e.tagName,id:e.id,text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').trim().replace(/\s+/g,' ').slice(0,240),href:e.getAttribute('href'),type:e.getAttribute('type'),disabled:!!e.disabled,...rect(e),font:getComputedStyle(e).fontFamily,size:getComputedStyle(e).fontSize,color:getComputedStyle(e).color});
 return {url:location.pathname+location.hash,title:document.title,viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,
 headings:[...document.querySelectorAll('h1,h2,h3')].filter(visible).map(info),
 controls:[...document.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,[role=tab]')].filter(visible).map(info),
 overflow:[...document.querySelectorAll('main *,footer *,header *')].filter(e=>visible(e)&&e.getBoundingClientRect().width>0&&(e.getBoundingClientRect().right>innerWidth+2||e.getBoundingClientRect().left< -2)).slice(0,25).map(info),
 body:document.body.innerText.slice(0,22000),
 smallText:[...document.querySelectorAll('main p,main label,main small,footer a')].filter(e=>visible(e)&&parseFloat(getComputedStyle(e).fontSize)<12).slice(0,20).map(info)};
}'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'evidence').mkdir(exist_ok=True)
    manifest={'origin':ORIGIN,'backend':'public-deployment',
              'mode':'direct-public-browser',
              'post_forwarded':False,'screens':[],'blocked_writes':[], 'errors':[], 'http_errors':[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000},color_scheme='light',reduced_motion='reduce')
        def route_handler(route):
            r=route.request;u=urlsplit(r.url)
            if u.hostname!='agentconcierge.biz':return route.abort()
            if r.method not in ('GET','HEAD'):
                manifest['blocked_writes'].append({'method':r.method,'path':u.path})
                return route.fulfill(status=403,json={'detail':'Read-only UX audit: action not executed.'})
            route.continue_()
        context.route('**/*',route_handler)
        page=context.new_page()
        page.on('pageerror',lambda error:manifest['errors'].append({'page':urlsplit(page.url).path,'error':str(error)[:300]}))
        page.on('response',lambda response:manifest['http_errors'].append({'page':urlsplit(page.url).path,'path':urlsplit(response.url).path,'status':response.status}) if response.status>=400 else None)
        for name in PAGES:
            for width,height,label in ((1440,1000,'desktop'),(390,844,'mobile')):
                page.set_viewport_size({'width':width,'height':height})
                try:
                    response=page.goto(ORIGIN+'/new/en/'+name+'.html',wait_until='domcontentloaded',timeout=45000)
                    page.wait_for_timeout(2000)
                    if name=='index' and label=='desktop':
                        page.screenshot(path=str(OUT/'evidence/index-first-visit-desktop.png'),full_page=True)
                        reject=page.get_by_role('button',name='Reject Non-Essential',exact=True)
                        if reject.is_visible():reject.click()
                        page.wait_for_timeout(250)
                    data=page.evaluate(INSPECT)
                    data.update(name=name,device=label,status=response.status if response else None)
                    file='evidence/'+name+'-'+label+'.png'
                    page.screenshot(path=str(OUT/file),full_page=True,timeout=20000)
                    data['screenshot']=file
                    manifest['screens'].append(data)
                    print(json.dumps({'page':name,'device':label,'status':data['status'],'width':data['documentWidth'],'height':data['height']}),flush=True)
                except Exception as exc:
                    manifest['errors'].append({'page':name,'device':label,'error':type(exc).__name__+': '+str(exc)[:200]})
                (OUT/'live-inventory.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        browser.close()


if __name__=='__main__':main()
