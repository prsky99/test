"""Signed product lifecycle and private outage proofs with isolated MCP transport."""
# ruff: noqa: F401,F811
import copy
import json
import time

import pytest

from agent_market.workflow_fallback import NOTICE,RoutingDenied
from agent_market.workflows import WorkflowError,public_template
from tests.test_workflow_fallback import routing,config
from tests.test_workflow_runtime import wait


def candidate(routing,slug='documentation-api'):
    rt,wf,ids,*_=routing
    rt.store.update_workflow(wf['id'],{'is_template':0})
    wf=rt.store.get_workflow(wf['id'])
    wf['nodes'][0]['resource_id']=ids[0]
    rt.store.update_workflow(wf['id'],{'nodes':wf['nodes']})
    wf=rt.store.get_workflow(wf['id'])
    config(rt,wf,ids)
    spec={'slug':slug,'use_case':'A public documentation search endpoint.',
          'inputs':[{'name':'query','node_id':'search','argument':'query','type':'string','min_length':2,'max_length':160}]}
    rt.products.candidate(wf['id'],spec,0,lambda:True)
    return rt,wf,ids


def accepted(routing,slug='documentation-api'):
    rt,wf,ids=candidate(routing,slug)
    normal=wait(rt,rt.submit(wf,product_input={'query':'solar energy'}))
    assert normal['status']=='succeeded',normal
    expiry=rt.products.get(wf['id'])['expires']
    config(rt,wf,ids,'canary',max_runs=10,expires=expiry)
    if not rt.fallback.control()['enabled']:rt.fallback.set_control({'enabled':True,'revision':rt.fallback.control()['revision']},0)
    drill=wait(rt,rt.submit(wf,allow_fallback=True,fallback_notice=NOTICE,product_input={'query':'ocean monitoring'},product_drill=ids[0]))
    assert drill['status']=='succeeded',drill
    rt.products.accept(wf['id'],normal['run_id'],[drill['run_id']],0,lambda:True)
    return rt,wf,ids,normal,drill


def published(routing,slug='documentation-api'):
    rt,wf,ids,normal,drill=accepted(routing,slug)
    config(rt,wf,ids,'active',canary_percent=100,max_runs=20,expires=rt.products.get(wf['id'])['expires'])
    rt.products.publish(wf['id'],0,lambda:True)
    return rt,rt.store.get_workflow(wf['id']),ids


def test_product_full_lifecycle_and_parameter_binding(routing):
    rt,wf,ids=published(routing)
    projected=public_template(wf,rt)
    assert projected['product']['inputs'][0]['name']=='query'
    assert projected['fallback_available'] and 'io_profile' not in json.dumps(projected)
    with pytest.raises(WorkflowError):rt.submit(wf,source='public',public=True,product_input={'query':'new question'})
    first=wait(rt,rt.submit(wf,source='public',public=True,allow_fallback=True,fallback_notice=NOTICE,product_input={'query':'new question'}))
    assert first['status']=='succeeded'
    assert first['node_results'][0]['input']['query']=='new question'
    second=wait(rt,rt.submit(wf,source='public',public=True,allow_fallback=True,fallback_notice=NOTICE,product_input={'query':'different question'}))
    assert first['definition_hash']!=second['definition_hash']
    assert rt.fallback.plan(dict(rt.store.query('SELECT * FROM workflow_runs WHERE id=?',(first['run_id'],))[0]))['selected']
    assert rt.store.get_workflow(wf['id'])['nodes'][0]['data']['input']['query']=='documentation'


def test_no_product_active_without_proof(routing):
    rt,wf,ids=candidate(routing)
    with pytest.raises(RoutingDenied):config(rt,wf,ids,'active',canary_percent=100)
    with pytest.raises(ValueError):rt.products.publish(wf['id'],0,lambda:True)


def test_normal_only_and_forged_outage_cannot_qualify(routing):
    rt,wf,ids=candidate(routing)
    normal=wait(rt,rt.submit(wf));config(rt,wf,ids,'canary')
    with pytest.raises(ValueError):rt.products.accept(wf['id'],normal['run_id'],[normal['run_id']],0,lambda:True)
    with pytest.raises(ValueError):rt.products.accept(wf['id'],normal['run_id'],['forged'],0,lambda:True)
    assert rt.products.get(wf['id'])['stage']=='candidate'


@pytest.mark.parametrize('value',[{'bad':1},{'query':'https://example.com'},{'query':'a@private.example'},{'query':'{{secret}}'},{'query':'a'},{'query':False}])
def test_public_input_bounds_and_secret_patterns(routing,value):
    rt,wf,_=candidate(routing)
    with pytest.raises(WorkflowError):rt.submit(wf,product_input=value)


def test_public_fault_injection_and_unreviewed_draft_denied(routing):
    rt,wf,ids=candidate(routing)
    with pytest.raises(WorkflowError):rt.submit(wf,source='public',public=True,product_input={})
    with pytest.raises(WorkflowError):rt.submit(wf,source='public',public=True,product_input={},product_drill=ids[0])


def test_graph_change_withdraws_publication(routing):
    rt,wf,_=published(routing)
    changed=copy.deepcopy(wf['nodes']);changed[0]['data']['input']['query']='changed saved query'
    rt.store.update_workflow(wf['id'],{'nodes':changed})
    assert public_template(rt.store.get_workflow(wf['id']),rt) is None


def test_tampered_checkpoint_cannot_be_accepted(routing):
    rt,wf,ids=candidate(routing)
    normal=wait(rt,rt.submit(wf));config(rt,wf,ids,'canary')
    with rt.store.tx() as db:db.execute('UPDATE workflow_checkpoints SET signature=? WHERE run_id=?',('forged',normal['run_id']))
    with pytest.raises(ValueError,match='checkpoint'):rt.products.accept(wf['id'],normal['run_id'],[normal['run_id']],0,lambda:True)


def test_product_public_api_inputs_download_and_forgery_boundaries(routing):
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import Front,create_front_app
    from io import BytesIO
    from zipfile import ZipFile
    rt,wf,ids=published(routing)
    proxy=rt.proxy;front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    with TestClient(create_front_app(front),base_url='https://agentconcierge.biz') as client:
        templates=client.get('/api/workflows/templates').json()['templates']
        product=next(t for t in templates if t['id']==wf['id'])
        body={'template_id':wf['id'],'definition_hash':product['definition_hash'],'input':{'query':'ocean monitoring'},'allow_fallback':True,'fallback_notice':NOTICE}
        for extra in ({'product_drill':ids[0]},{'input':{'resource_id':ids[0]}},{'input':{'query':'Bearer private-value'}},{'input':[]},{'input':None}):
            assert client.post('/api/workflows/run',json={**body,**extra}).status_code==400
        response=client.post('/api/workflows/run',json=body)
        assert response.status_code==202,response.text
        result=wait(front.workflows,response.json())
        assert result['status']=='succeeded',[(n.get('error'),n.get('error_code')) for n in result['node_results']]
        assert result['node_results'][0]['input']['query']=='ocean monitoring'
        assert client.get('/api/workflows/runs/'+response.json()['run_id']).status_code==404
        status=client.get('/api/workflows/runs/'+response.json()['run_id'],headers={'X-Workflow-Key':response.json()['run_key']})
        assert status.status_code==200 and 'product_context' not in status.text
        package=client.get(f"/api/workflows/{wf['id']}/webapp")
        assert package.status_code==200,package.text[:200] if package.status_code!=200 else ''
        with ZipFile(BytesIO(package.content)) as archive:
            assert {'index.html','assets/app.js','assets/style.css','app-manifest.json','README.md'}<=set(archive.namelist())
            html=archive.read('index.html').decode();js=archive.read('assets/app.js').decode()
            assert 'data-input' in html and 'required' in html and 'Content-Security-Policy' in html
            assert '.innerHTML' not in js and 'localStorage' not in js
            assert 'primary.example' not in html+js and 'io_profile' not in html+js


@pytest.mark.parametrize('change',['metadata','signature','expiry','control','capacity'])
def test_product_withdrawal_and_capacity_never_downgrade_to_baseline(routing,change):
    rt,wf,_=published(routing)
    if change=='metadata':rt.store.update_workflow(wf['id'],{'description':'An unreviewed new use case.'})
    elif change=='signature':
        with rt.store.tx() as db:db.execute('UPDATE workflow_product_templates SET signature=? WHERE workflow_id=?',('forged',wf['id']))
    elif change=='expiry':
        with rt.store.tx() as db:db.execute('UPDATE workflow_product_templates SET expires=? WHERE workflow_id=?',(time.time()-1,wf['id']))
    elif change=='control':rt.fallback.set_control({'enabled':False,'revision':rt.fallback.control()['revision']},0)
    elif change=='capacity':
        with rt.store.tx() as db:db.execute('UPDATE workflow_fallback_policies SET admitted=? WHERE workflow_id=?',(20,wf['id']))
    assert public_template(rt.store.get_workflow(wf['id']),rt) is None
    with pytest.raises((WorkflowError,ValueError)):
        rt.submit(rt.store.get_workflow(wf['id']),source='public',public=True,allow_fallback=True,fallback_notice=NOTICE,product_input={})


def test_admin_product_download_requires_staff_and_creates_no_deployment_grant(routing):
    from unittest.mock import Mock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway.dashboard import dashboard_router
    from tests.conftest import STAFF,staff_session
    rt,wf,_=published(routing);staff_session(rt.store)
    app=FastAPI();app.include_router(dashboard_router(rt.store,rt.store._path,'private-machine-token',None,ssl_manager=Mock(get_status=lambda:{})))
    with TestClient(app,base_url='https://admin.test') as client:
        path=f"/admin/api/workflows/{wf['id']}/product-package"
        assert client.post(path,json={}).status_code in (401,403)
        assert client.post(path,json={},headers={'Authorization':'Bearer private-machine-token'}).status_code in (401,403)
        assert client.post(path,json={'issue_grant':True},headers=STAFF).status_code==400
        response=client.post(path,json={},headers=STAFF)
        assert response.status_code==200,response.text[:200]
        assert response.headers['content-type']=='application/zip'
        assert not rt.store.query('SELECT * FROM workflow_apps WHERE workflow_id=?',(wf['id'],))
