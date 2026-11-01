"""Private template ownership, credit lifecycle and real fallback routing."""
# ruff: noqa: F401,F811
import copy
import json
import secrets
from io import BytesIO
from zipfile import ZipFile

import pytest
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from agent_market.workspace_template_hub import SAVE_NOTICE, RUN_NOTICE
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workflow_products import published
from tests.test_workflow_runtime import wait


@pytest.fixture
def hub_world(customer_flow, routing):
    x = customer_flow
    # Publish against this same isolated runtime, store and mock MCP transport.
    rt, wf, ids = published(routing)
    return x, rt, wf, ids


def proposed(x, wf, old=None, query='solar energy'):
    product=x.core.templates.catalog(x.ws,x.actor)['templates'][0]
    return x.core.templates.prepare(x.ws,dict(template_id=wf['id'],definition_hash=product['definition_hash'],
        name='My research service',inputs={'query':query},draft_id=old['id'] if old else None,
        revision=old['revision'] if old else 0),x.actor)


def saved(x, proposal):
    return x.core.templates.save(x.ws,dict(proposal=proposal['proposal'],signature=proposal['signature'],authorized=True,notice=SAVE_NOTICE),x.actor)


def test_hub_real_template_copy_fallback_run_download_and_edit_charge(hub_world):
    x,rt,wf,ids=hub_world;before=len(x.w.calls)
    p=proposed(x,wf);assert p['credit_charge']==1
    draft=saved(x,p);assert len(x.w.calls)==before
    assert saved(x,p)['replayed']
    assert len(x.core.templates.listing(x.ws,x.actor))==1
    with pytest.raises(WorkspaceDenied):x.core.templates.package(x.ws,draft['id'],'1',x.actor)
    # Definitive preflight outage reaches exactly one independently bound alternate.
    x.w.modes['primary.example']='preflight'
    body=dict(revision=1,request_id=secrets.token_hex(16),authorized=True,notice=RUN_NOTICE)
    run=x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    record=json.loads(x.w.store.query('SELECT payload FROM workspace_template_records WHERE id=?',(run['id'],))[0][0])
    result=wait(rt,{'run_id':record['run_id']});assert result['status']=='succeeded',result
    history=x.core.templates.runs(x.ws,draft['id'],x.actor)
    assert history[0]['status']=='succeeded' and 'run_key' not in json.dumps(history)
    assert rt.fallback.plan(dict(x.w.store.query('SELECT * FROM workflow_runs WHERE id=?',(record['run_id'],))[0]))['selected']
    assert record['sealed'] and rt._open(record['sealed'],record['id']) not in json.dumps(record)
    with pytest.raises(WorkspaceConflict):x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    data,_=x.core.templates.package(x.ws,draft['id'],'1',x.actor)
    with ZipFile(BytesIO(data)) as z:
        html=z.read('index.html').decode();assert 'value="solar energy"' in html
        assert 'https://agentconcierge.biz' in html and 'run_key' not in html
    assert x.core.templates.package(x.ws,draft['id'],'1',x.actor)[0]
    changed=proposed(x,wf,draft,'battery recycling');assert changed['credit_charge']==1
    edited=saved(x,changed);assert edited['revision']==2
    assert proposed(x,wf,edited,'public astronomy')['credit_charge']==0
    with pytest.raises(WorkspaceDenied):x.core.templates.package(x.ws,draft['id'],'2',x.actor)
    assert len(x.core.templates.listing(x.ws,x.actor))==1


def test_hub_auth_csrf_tamper_expiry_and_changed_template(hub_world,monkeypatch):
    x,rt,wf,ids=hub_world;p=proposed(x,wf)
    path=x.base+'/templates'
    assert x.client.get(path).status_code==200
    assert x.client.post(path+'/prepare',json=p['proposal']).status_code==403
    foreign=x.base.replace(x.ws,'ws_'+'a'*32)+'/templates'
    assert x.client.get(foreign).status_code==403
    tampered=copy.deepcopy(p);tampered['proposal']['inputs']['query']='other query'
    with pytest.raises(WorkspaceDenied):saved(x,tampered)
    monkeypatch.setattr('agent_market.workspace_template_hub.time.time',lambda:p['proposal']['expires']+1)
    with pytest.raises(WorkspaceDenied):saved(x,p)
    monkeypatch.undo()
    nodes=copy.deepcopy(wf['nodes']);nodes[0]['data']['input']['query']='modified graph'
    x.w.store.update_workflow(wf['id'],{'nodes':nodes})
    assert wf['id'] not in {t['id'] for t in x.core.templates.catalog(x.ws,x.actor)['templates']}
    with pytest.raises((WorkspaceDenied,WorkspaceConflict)):saved(x,p)


def test_runner_cannot_save_and_unverified_templates_cannot_inherit_fallback(hub_world):
    x,rt,wf,ids=hub_world;p=proposed(x,wf)
    with x.s.identity.tx() as db:db.execute("UPDATE customer_workspace_links SET role='runner',revision=revision+1 WHERE workspace_id=?",(x.ws,))
    with pytest.raises(WorkspaceDenied):saved(x,p)
    rt.fallback.set_control({'enabled':False,'revision':rt.fallback.control()['revision']},0)
    assert wf['id'] not in {t['id'] for t in x.core.templates.catalog(x.ws,x.actor)['templates']}


@pytest.mark.parametrize('inputs',[{'query':'private@example.com'},{'query':'https://private.example'},{'query':'a'},{'query':True},{'query':'safe query','undeclared':1},{}])
def test_invalid_template_inputs_never_saved(hub_world,inputs):
    x,rt,wf,ids=hub_world;p=proposed(x,wf)['proposal']
    body={k:p[k] for k in ('template_id','definition_hash','name','inputs','draft_id','revision')};body['inputs']=inputs
    with pytest.raises(WorkspaceInvalid):x.core.templates.prepare(x.ws,body,x.actor)
    assert not x.core.templates.listing(x.ws,x.actor)


def test_ambiguous_dispatch_is_retained_and_never_replayed(hub_world,monkeypatch):
    x,rt,wf,ids=hub_world;draft=saved(x,proposed(x,wf));calls=[]
    def interrupted(*args,**kwargs):
        calls.append(1)
        raise WorkspaceConflict()
    monkeypatch.setattr(rt,'submit',interrupted)
    body=dict(revision=1,request_id=secrets.token_hex(16),authorized=True,notice=RUN_NOTICE)
    with pytest.raises(WorkspaceConflict):x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    with pytest.raises(WorkspaceConflict):x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    assert calls==[1]
    history=x.core.templates.runs(x.ws,draft['id'],x.actor)
    assert history[0]['status']=='unknown' and 'run_key' not in json.dumps(history)


def test_review_stale_cas_and_owner_permission_never_bypass_credit_quote(hub_world):
    x,rt,wf,ids=hub_world;draft=saved(x,proposed(x,wf))
    first=proposed(x,wf,draft,'first revision');second=proposed(x,wf,draft,'second revision')
    saved(x,first)
    with pytest.raises(WorkspaceConflict):saved(x,second)
    with x.s.identity.tx() as db:db.execute("UPDATE customer_workspace_links SET role='viewer',revision=revision+1 WHERE workspace_id=?",(x.ws,))
    assert x.core.templates.listing(x.ws,x.actor)
    with pytest.raises(WorkspaceDenied):x.core.templates.execute(x.ws,draft['id'],dict(revision=2,request_id=secrets.token_hex(16),authorized=True,notice=RUN_NOTICE),x.actor)
    with pytest.raises(WorkspaceDenied):x.core.templates.package(x.ws,draft['id'],'2',x.actor)


def test_api_save_run_csrf_and_history_masking(hub_world):
    x,rt,wf,ids=hub_world;p=proposed(x,wf)
    body=dict(proposal=p['proposal'],signature=p['signature'],authorized=True,notice=SAVE_NOTICE)
    path=x.base+'/templates'
    assert x.client.post(path+'/drafts',json=body).status_code==403
    result=x.client.post(path+'/drafts',json=body,headers=x.headers)
    assert result.status_code==200,result.text
    draft=result.json()['draft'];run_body=dict(revision=1,request_id=secrets.token_hex(16),authorized=True,notice=RUN_NOTICE)
    assert x.client.post(path+'/drafts/'+draft['id']+'/runs',json=run_body).status_code==403
    assert x.client.get(path+'/drafts/'+draft['id']+'/runs').json()['runs']==[]
    assert 'no-store' in result.headers['cache-control']
