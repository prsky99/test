"""Real Chromium exercises the actual Admin Edge function, with all IO mocked."""
import json
from pathlib import Path

import pytest
from tests.test_front_workflow_browser import browser

LOCAL='http://localhost:8200'
PUBLIC='https://agentconcierge.biz'
RUN='er_'+'a'*32


@pytest.mark.parametrize('mode',['edge','unknown','unavailable','session-change'])
def test_renewal_uses_direct_edge_delivery_without_bypassing_private_reason_or_session(browser,mode):
    base='/admin/next/assets/core/'
    plan={'backend':'worker','base':PUBLIC,'run_id':RUN,'stream_path':'/api/edge-gateway/v1/runs/'+RUN+'/stream',
          'access_token':'short-run-ticket','input':{'message':'Weather?'},'protocol':'a2a'}
    local=[];remote=[]
    context=browser.new_context()
    context.add_cookies([{'name':'private-cookie','value':'never-forward','url':PUBLIC}])
    def serve(route):
        req=route.request
        if req.url==LOCAL+'/fixture':
            route.fulfill(body='<script type="module" src="/harness.js"></script>',headers={'Content-Type':'text/html',
                'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; script-src 'self'; connect-src 'self' https://agentconcierge.biz"});return
        if req.url==LOCAL+'/harness.js':
            route.fulfill(body="import {write,session} from '"+base+"api.js';session.set('private-admin-session');"
                "window.changeSession=()=>session.set('different-session');window.run=()=>write('/admin/api/v2/catalog-tools/test/execute',"
                "{resource_id:1,message:'Weather?'},{reason:'Reviewed test fixture'});",content_type='application/javascript');return
        if req.url in [LOCAL+base+n for n in ('api.js','edge-delivery.js','output-delivery.js')]:
            route.fulfill(body=Path('agent_market/gateway/admin_next/core/'+req.url.rsplit('/',1)[1]).read_text(),content_type='application/javascript');return
        if req.url.startswith(LOCAL+'/admin/api/'):
            local.append(req)
            assert req.headers['authorization']=='Bearer private-admin-session'
            assert req.headers['x-admin-reason']=='Reviewed%20test%20fixture'
            if req.url.endswith('/prepare'):
                if mode=='session-change':route.abort();return
                value={'backend':'origin'} if mode=='unavailable' else plan
            elif req.url.endswith('/execute'):value={'ok':True,'output_text':'Origin fallback','delivery_backend':'origin'}
            else:value={'run_id':RUN,'state':'dispatch_reserved' if mode=='unknown' else 'succeeded','backend':'worker'}
            route.fulfill(json=value);return
        if req.url==PUBLIC+plan['stream_path']:
            remote.append(req)
            assert req.headers['authorization']=='Bearer short-run-ticket'
            assert not any(k in req.headers for k in ('cookie','x-dashboard','x-admin-reason','x-visitor-token','referer'))
            if mode=='unknown':route.abort();return
            route.fulfill(json={'run_id':RUN,'state':'succeeded','backend':'worker','output':{'parts':[{'kind':'text','text':'Ready'}]}},
                headers={'Access-Control-Allow-Origin':LOCAL,'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Edge-Result-Format'});return
        route.abort()
    context.route('**/*',serve);page=context.new_page();page.goto(LOCAL+'/fixture');page.wait_for_function('typeof run==="function"')
    if mode=='session-change':
        # Change identity while preparation is in flight; no public dispatch follows.
        result=page.evaluate("async()=>{const promise=run().catch(e=>({failed:true}));changeSession();return await promise;}")
        assert result['failed'] and not remote
    else:
        result=page.evaluate('run()')
        assert result['ok']==(mode!='unknown')
        assert len(remote)==(0 if mode=='unavailable' else 1)
        assert sum(req.url.endswith('/execute') for req in local)==(1 if mode=='unavailable' else 0)
    context.close()


@pytest.mark.parametrize('mode',['edge','unknown','unavailable'])
def test_admin_browser_keeps_credentials_local_and_never_replays_uncertain_io(browser,mode):
    html=Path('agent_market/gateway/dashboard.html').read_text()
    function=html.split('async function executeAdminEdgeTest(payload) {',1)[1].split('\nfunction renderTestResult',1)[0]
    script='async function executeAdminEdgeTest(payload) {'+function
    plan={'backend':'worker','base':PUBLIC,'run_id':RUN,'stream_path':'/api/edge-gateway/v1/runs/'+RUN+'/stream',
          'access_token':'short-run-ticket','input':{'message':'Weather?'},'protocol':'a2a'}
    script+='\nwindow.calls=[]; window.api=async(path,options)=>{calls.push({path,body:options.json});'
    script+='if(path.endsWith("/prepare"))return '+json.dumps({'backend':'origin'} if mode=='unavailable' else plan)+';'
    script+='if(path.endsWith("/execute"))return {ok:true,output_text:"Origin fallback",delivery_backend:"origin"};'
    script+='return '+json.dumps({'run_id':RUN,'state':'dispatch_reserved' if mode=='unknown' else 'succeeded','backend':'worker'})+';};'
    script+='\nwindow.run=()=>executeAdminEdgeTest({resource_id:1,message:"Weather?",timeout_seconds:10});'
    seen=[];external=[]
    context=browser.new_context()
    context.add_cookies([{'name':'private-cookie','value':'never-forward','url':PUBLIC}])
    def serve(route):
        request=route.request
        if request.url==LOCAL+'/fixture':
            route.fulfill(body='<script src="/harness.js"></script>',headers={'Content-Type':'text/html',
                'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; script-src 'self'; connect-src 'self' https://agentconcierge.biz; base-uri 'none'"});return
        if request.url==LOCAL+'/harness.js':route.fulfill(body=script,content_type='application/javascript');return
        if request.url==PUBLIC+plan['stream_path']:
            seen.append(request)
            if mode=='unknown':route.abort();return
            assert request.headers.get('authorization')=='Bearer short-run-ticket'
            assert not any(k in request.headers for k in ('cookie','x-dashboard','x-visitor-token'))
            assert request.headers.get('referer') is None
            route.fulfill(body=json.dumps({'run_id':RUN,'state':'succeeded','backend':'worker',
                'output':{'parts':[{'kind':'text','text':'<img src=x onerror="window.injected=true"> Ready'}]}}),headers={
                    'Content-Type':'application/json','Access-Control-Allow-Origin':LOCAL,
                    'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Edge-Result-Format'});return
        external.append(request.url);route.abort()
    context.route('**/*',serve)
    page=context.new_page();page.goto(LOCAL+'/fixture')
    result=page.evaluate('run()');calls=page.evaluate('calls')
    if mode=='edge':
        assert result['ok'] and result['delivery_backend']=='worker' and len(seen)==1
        assert all(not x['path'].endswith('/execute') for x in calls)
    elif mode=='unknown':
        assert result['ok'] is False and len(seen)==1
        assert all(not x['path'].endswith('/execute') for x in calls)
        assert calls[1]['body']['recover'] is True
        assert all(not x['body'].get('recover') for x in calls[2:])
    else:assert result['delivery_backend']=='origin' and not seen
    assert not external and page.evaluate('window.injected') is None
    context.close()
