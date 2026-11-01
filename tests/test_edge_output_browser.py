"""Real Chromium renders the dashboard and exercises Edge-only output recovery."""
import json
from pathlib import Path
import pytest
from tests.test_front_workflow_browser import browser

LOCAL='http://localhost:8200';PUBLIC='https://agentconcierge.biz';RUN='er_'+'a'*32


@pytest.mark.parametrize('theme,width',[('light',1440),('dark',390)])
def test_monitor_screen_chart_filters_and_refresh_preserve_prior_values(browser,theme,width,tmp_path):
    context=browser.new_context(viewport={'width':width,'height':1100},reduced_motion='reduce')
    data={'available':True,'captured_at':1792905000,'since':1792818600,'bucket_seconds':3600,
        'policy':{'preferred_backend':'worker','reason':'free_available','account_requests_reported':600,'local_reservations':10,'soft_limit':90000,'window_utc':'2026-10-25','observed_at':1792904990},
        'totals':{'edge':8,'origin':2,'error':2,'edge_share':0.8},'timeline':[{'at':1792904000,'edge':8,'origin':2,'error':2}],
        'fallback_reasons':[{'reason':'cache_miss','count':2}], 'sources':[{'source':'admin','edge':8,'origin':2,'error':1}],
        'recent':[{'at':1792904900,'source':'admin','outcome':'edge','reason':'delivered'},{'at':1792904800,'source':'workspace','outcome':'origin','reason':'cache_miss'},
            {'at':1792904750,'source':'chat','outcome':'error','reason':'origin_http_502'},
            {'at':1792904700,'source':'chat','outcome':'error','reason':'edge_error'}],
        'failure_reasons':[{'reason':'origin_http_502','count':1},{'reason':'edge_error','count':1}],
        'execution_placement':[{'backend':'origin','state':'succeeded','count':5}]}
    script="import * as ui from '/admin/next/assets/core/ui.js';import {render} from '/admin/next/assets/areas/edge-monitor.js';"
    script+="window.loads=0;window.fail=false;window.active=true;const api={read:async()=>{loads++;if(fail)throw Error('Fixture connection error');return {data:"+json.dumps(data)+"};}};"
    script+="render(document.querySelector('main'),{ui,api,screen:{title:'Edge·Origin 모니터링'},isCurrent:()=>active});"
    def serve(route):
        p=route.request.url.removeprefix(LOCAL)
        if p=='/fixture':route.fulfill(body='<link rel="stylesheet" href="/admin/next/assets/pearl-tokens.css"><link rel="stylesheet" href="/admin/next/assets/admin-pearl.css"><body data-theme="'+theme+'"><main class="adm-main"></main><script type="module" src="/harness.js"></script>',content_type='text/html');return
        if p=='/harness.js':route.fulfill(body=script,content_type='application/javascript');return
        if p.startswith('/admin/next/assets/'):
            f=Path('agent_market/gateway/admin_next')/p.removeprefix('/admin/next/assets/')
            route.fulfill(body=f.read_text(),content_type='text/css' if f.suffix=='.css' else 'application/javascript');return
        route.abort()
    context.route('**/*',serve);page=context.new_page();page.goto(LOCAL+'/fixture');page.get_by_text('모든 Agent 출력은 Edge 우선',exact=True).wait_for()
    assert page.get_by_text('80.0%',exact=True).count()==1
    assert page.get_by_role('img').count()>=1
    page.get_by_label('최근 전달 경로').select_option('origin');assert page.get_by_text('Edge 결과 조회 실패',exact=True).count()>=1
    page.get_by_label('최근 전달 경로').select_option('error')
    assert page.get_by_text('Origin 응답 오류 · HTTP 502',exact=True).count()==2
    assert page.get_by_text('과거 응답 오류 · 상세 미수집',exact=True).count()==2
    page.evaluate('window.fail=true');page.get_by_role('button',name='지금 갱신',exact=True).click();page.get_by_text('갱신 실패',exact=False).wait_for()
    assert page.get_by_text('80.0%',exact=True).count()==1
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(tmp_path/'dashboard.png'),full_page=True)
    page.evaluate('window.active=false');context.close()


@pytest.mark.parametrize('failed',[False,True])
def test_output_consumer_sends_only_short_ticket_to_edge_and_recovers_only_saved_output(browser,failed):
    context=browser.new_context();seen=[]
    envelope={'_edge_output_v1':True,'base':PUBLIC,'run_id':RUN,'path':'/api/edge-gateway/v1/outputs/'+RUN,'access_token':'one-output-ticket'}
    script="import {resolveEdgeOutput} from '/output.js';window.calls=[];window.run=async()=>{const response=await resolveEdgeOutput(new Response(JSON.stringify("+json.dumps(envelope)+"),{headers:{'Content-Type':'application/vnd.agentconcierge.edge-output+json'}}),async path=>{calls.push(path);return new Response(JSON.stringify({answer:'Retained result'}),{headers:{'Content-Type':'application/json'}});});return response.json();};"
    def serve(route):
        u=route.request.url
        if u==LOCAL+'/fixture':route.fulfill(body='<script type="module" src="/harness.js"></script>',headers={'Content-Type':'text/html','Referrer-Policy':'no-referrer'});return
        if u==LOCAL+'/harness.js':route.fulfill(body=script,content_type='application/javascript');return
        if u==LOCAL+'/output.js':route.fulfill(body=Path('agent_market/gateway/admin_next/core/output-delivery.js').read_text(),content_type='application/javascript');return
        if u==PUBLIC+envelope['path']:
            req=route.request;seen.append(req)
            assert req.headers['authorization']=='Bearer one-output-ticket'
            assert not any(k in req.headers for k in ('cookie','x-dashboard','x-admin-reason','x-visitor-token','referer'))
            if failed:route.abort();return
            route.fulfill(json={'status':200,'body':{'answer':'Edge result'}},headers={'Access-Control-Allow-Origin':LOCAL,'Access-Control-Allow-Headers':'Authorization'});return
        route.abort()
    context.route('**/*',serve);page=context.new_page();page.goto(LOCAL+'/fixture');page.wait_for_function('typeof run==="function"')
    assert page.evaluate('run()')['answer']==('Retained result' if failed else 'Edge result')
    calls=page.evaluate('calls');assert calls==(['/admin/api/v2/gateway/edge-output/'+RUN] if failed else [])
    assert len(seen)==1;context.close()
