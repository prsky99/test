"""Shared public discovery and private fixed-default copies retain admission gates."""
# ruff: noqa: F401,F811
import copy
import json
import secrets
from io import BytesIO
from zipfile import ZipFile

import pytest
from agent_market.concierge.workflow_discovery import published_templates
from agent_market.workflow_templates import agent
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from agent_market.workspace_template_hub import FIXED_RUN_NOTICE, RUN_NOTICE
from tests.test_customer_template_hub import hub_world, customer_flow, typed_release_world, typed_world, routing, saved
from tests.test_workflow_runtime import wait


def ordinary(x, ids, count=1):
    values=[]
    for i in range(count):
        identity=x.w.store.create_workflow(dict(name='Public Documentation '+str(i),description='Search public reference material.',category='dev_tools' if i%2 else 'docs_knowledge',is_template=1,nodes=[dict(id='search',name='Public reference search',type='agent',kind='mcp',resource_id=ids[0],data={'tool':'search_docs','input':{'query':'documentation','language':'en','limit':2}})],edges=[]))
        values.append(x.w.store.get_workflow(identity))
    return values


def prepare_fixed(x,wf,**changes):
    product=next(t for t in x.core.templates.catalog(x.ws,x.actor)['templates'] if t['id']==wf['id'])
    body=dict(template_id=wf['id'],definition_hash=product['definition_hash'],name='My published research',inputs={},draft_id=None,revision=0)
    return x.core.templates.prepare(x.ws,{**body,**changes},x.actor)


def test_shared_catalog_is_identical_not_a_separate_product_subset(hub_world):
    x,rt,wf,ids=hub_world
    ordinary(x,ids,25)
    expected=published_templates(x.w.store)
    actual=x.core.templates.catalog(x.ws,x.actor)['templates']
    assert actual==expected
    assert sum(not t.get('product') and t['execution_availability']['available'] for t in actual)==25
    assert wf['id'] in {t['id'] for t in actual}
    options=x.client.get(x.base+'/typed/options').json()
    assert options['hub']['templates']==actual
    assert all(set(c['fallback_template_ids'])<={wf['id']} for c in options['options']['candidates'])
    private=x.w.store.create_workflow(dict(name='Private workflow',nodes=[],edges=[],is_template=0))
    assert private not in {t['id'] for t in x.core.templates.catalog(x.ws,x.actor)['templates']}


def test_fixed_copy_real_run_private_name_download_pins_definition(hub_world,monkeypatch):
    x,rt,wf,ids=hub_world;fixed=ordinary(x,ids)[0];before=len(x.w.calls)
    draft=saved(x,prepare_fixed(x,fixed))
    assert len(x.w.calls)==before
    assert x.w.store.get_workflow(fixed['id'])==fixed
    body=dict(revision=1,request_id=secrets.token_hex(16),authorized=True,notice=FIXED_RUN_NOTICE)
    with pytest.raises(WorkspaceInvalid):x.core.templates.execute(x.ws,draft['id'],{**body,'notice':RUN_NOTICE},x.actor)
    calls=[];submit=rt.submit
    def admission(*args,**kwargs):calls.append(kwargs);return submit(*args,**kwargs)
    monkeypatch.setattr(rt,'submit',admission)
    run=x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    record=json.loads(x.w.store.query('SELECT payload FROM workspace_template_records WHERE id=?',(run['id'],))[0][0])
    assert wait(rt,{'run_id':record['run_id']})['status']=='succeeded'
    assert calls[0]['allow_fallback'] is False and calls[0]['product_input'] is None
    assert x.w.calls[before:]==['primary.example']
    with pytest.raises(WorkspaceConflict):x.core.templates.execute(x.ws,draft['id'],body,x.actor)
    data,_=x.core.templates.package(x.ws,draft['id'],'1',x.actor)
    with ZipFile(BytesIO(data)) as z:
        html=z.read('index.html').decode()
        assert 'My published research' in html
        assert draft['definition_hash'] in html
        assert 'definitionHash:cfg.definition_hash' in z.read('assets/app.js').decode()
        assert 'primary.example' not in html and 'run_key' not in html
    changed=copy.deepcopy(fixed['nodes']);changed[0]['data']['input']['query']='new defaults'
    x.w.store.update_workflow(fixed['id'],{'nodes':changed})
    with pytest.raises(WorkspaceConflict):x.core.templates.execute(x.ws,draft['id'],{**body,'request_id':secrets.token_hex(16)},x.actor)
    with pytest.raises(WorkspaceConflict):x.core.templates.package(x.ws,draft['id'],'1',x.actor)


def test_fixed_copy_rejects_custom_inputs_unavailable_private_and_withdrawn(hub_world):
    x,rt,wf,ids=hub_world;fixed=ordinary(x,ids)[0]
    with pytest.raises(WorkspaceInvalid):prepare_fixed(x,fixed,inputs={'query':'unreviewed edit'})
    draft=saved(x,prepare_fixed(x,fixed))
    with x.w.store.tx() as db:db.execute("UPDATE resources SET health_status='dead' WHERE id=?",(ids[0],))
    same=next(t for t in x.core.templates.catalog(x.ws,x.actor)['templates'] if t['id']==fixed['id'])
    assert not same['execution_availability']['available']
    with pytest.raises(WorkspaceDenied):prepare_fixed(x,fixed)
    x.w.store.update_workflow(fixed['id'],{'is_template':0})
    assert fixed['id'] not in {t['id'] for t in x.core.templates.catalog(x.ws,x.actor)['templates']}
    with pytest.raises(WorkspaceDenied):x.core.templates.execute(x.ws,draft['id'],dict(revision=1,request_id=secrets.token_hex(16),authorized=True,notice=FIXED_RUN_NOTICE),x.actor)
