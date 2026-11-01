"""Completion regressions for exact source reuse and local operating qualification.

All adapters and claimed approvals below are explicit isolated fixtures. They do
not establish actual independent qualification, real provider acceptance or an
operating deployment.
"""
from copy import deepcopy
from dataclasses import replace
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import digest
from agent_market.reliability_admission import NOTICE as ADMISSION_NOTICE
from agent_market.reliability_control_service import router_for
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_reliability import OPERATING_NOTICE, OperatingEvidenceApproval, ReliabilityEvidence
from tests.test_reliability_admission import pilot, body as admission_body
from tests.test_reliability_controls import controls, private_api
from tests.test_reliability_research import (research_world, configured, manifest, rp, rg)
from tests.test_reliability_circuit import circuit, config as circuit_config, command as circuit_command, opened, bind
from tests.test_reliability_evaluation_worker import worker_world
from tests.test_workspace_reliability import (reliability, setup, sample, trusted, report, erase)


def assess(w):
    w.plane.evaluator = trusted
    result = report(w)
    assert result.status_code == 200, result.text
    return result.json()['result']


def approval(w, binding):
    assert not w.store._db.in_transaction
    return OperatingEvidenceApproval(digest(binding), '6'*64, '7'*64,
                                     min(time.time()+120, binding['expires']))


def operation(w, revision=0):
    return {'resource_id': w.rid, 'revision': revision, 'authorized': True, 'notice': OPERATING_NOTICE}


def test_analysis_requires_exact_active_manifest_corpus_id_and_hash(research_world):
    w = research_world; original = configured(w)
    second = rp(w, '/manifests', manifest(w, manifest_id='rrm_'+'9'*32)).json()['result']
    assert original['corpus_hash'] == second['corpus_hash']
    assert original['corpus_id'] != second['corpus_id']
    assert rg(w, '/manifests/'+second['id']+'/analyze').status_code == 409
    assert rg(w, '/manifests/'+original['id']+'/analyze').status_code == 200
    assert not w.calls


def test_retained_admission_review_returns_original_exact_preview_without_new_authority(pilot):
    w = pilot; prepared = w.admission.prepare(w.ws['id'], admission_body(w), w.actor)
    before = {table: w.store.query('SELECT COUNT(*) FROM '+table)[0][0] for table in
              ('workspace_private_tickets', 'reliability_admissions', 'reliability_route_decisions', 'workspace_versions')}
    response = w.pilot_client.get(w.pilot_base+'/'+prepared['id']+'/review', headers=w.headers['owner'])
    assert response.status_code == 200, response.text
    value = response.json()['result']
    assert value['current'] and value['requires_run_confirmation']
    assert value['preview'] == prepared['preview'] and value['notice'] == ADMISSION_NOTICE
    assert value['provider_calls'] == value['tickets_created'] == 0
    assert 'ticket_id' not in response.text and 'source_hash' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    for table, count in before.items():
        assert w.store.query('SELECT COUNT(*) FROM '+table)[0][0] == count
    assert not w.calls
    assert w.pilot_client.get(w.pilot_base+'/'+prepared['id']+'/review?untrusted=1', headers=w.headers['owner']).status_code == 400
    assert w.pilot_client.get(w.pilot_base+'/'+prepared['id']+'/review').status_code == 401
    assert w.pilot_client.get(w.pilot_base+'/'+prepared['id']+'/review', headers=w.headers['viewer']).status_code == 404
    assert w.pilot_client.get(w.pilot_base+'/'+prepared['id']+'/review', headers=w.headers['owner'] | {'Origin':'https://other.test'}).status_code == 403


@pytest.mark.parametrize('change', ['expired', 'source', 'restored', 'not_selected'])
def test_retained_review_never_resurrects_ineligible_or_terminal_admission(pilot, change):
    w = pilot
    prepared = w.admission.prepare(w.ws['id'], admission_body(w, selected=change != 'not_selected'), w.actor)
    if change == 'expired': w.now = prepared['expires']
    elif change == 'source': w.sources[prepared['resource_id']]['revoked'] = True
    elif change == 'restored':
        with w.store.tx() as db: db.execute('INSERT INTO reliability_admission_restore_blocks VALUES(?)',(prepared['id'],))
    with pytest.raises((WorkspaceConflict, WorkspaceDenied)):
        w.admission.review(w.ws['id'], prepared['id'], w.actor)
    assert not w.calls


def test_report_assessment_runs_outside_transaction_and_projection_is_local_only(reliability):
    w = setup(reliability, environment='approved_external'); sample(w); sample(w)
    calls=[]
    def local_assessor(binding,bundle):
        assert not w.store._db.in_transaction
        calls.append(digest(binding)); return trusted(binding,bundle)
    w.plane.evaluator=local_assessor
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    assert calls == []
    assert report(w).status_code == 200 and len(calls)==2
    with w.plane.access._tx(w.actor) as (db,_):
        current=w.plane.current_projection_in_transaction(db,w.ws['id'],w.rid,w.actor)
        assert current['independent_qualified']
    assert report(w).status_code == 200 and len(calls)==2
    assert w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    assert len(calls)==2
    w.plane.evaluator=local_assessor
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    assert len(calls)==2


def test_local_verdict_cache_signature_expiry_and_source_erasure_fail_closed(reliability):
    w=setup(reliability,environment='approved_external'); source,_,_=sample(w); sample(w); assess(w)
    assert w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    key=next(iter(w.plane._verdict_cache)); original=deepcopy(w.plane._verdict_cache[key])
    w.plane._verdict_cache[key][0]['verdict']['qualification_hash']='8'*64
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    w.plane._verdict_cache[key]=original
    value,_=w.plane._verdict_cache[key]; value['expires']=time.time()-1
    w.plane._verdict_cache[key]=(value,w.plane.sign(value))
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']
    assess(w); erase(w,source['id'])
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']


def test_operating_qualification_requires_existing_independent_external_evidence_and_server_approval(reliability):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    with pytest.raises(WorkspaceDenied): w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    w.plane.operating_qualifier=lambda binding: {'approved':True,'binding_hash':digest(binding)}
    with pytest.raises(WorkspaceDenied): w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    w.plane.operating_qualifier=lambda binding: approval(w,binding)
    value=w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    assert value['qualified_operating_evidence'] and value['revision']==1
    current=w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)
    assert current['environment']=='operating' and current['source_environment']=='approved_external'
    assert current['qualified_operating_evidence'] and not current['public_activation']
    assert current['expires_at']<=value['expires']
    with pytest.raises(WorkspaceConflict): w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    w.plane.withdraw_operating(w.ws['id'],operation(w,1),w.actor)
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['qualified_operating_evidence']
    with pytest.raises(WorkspaceConflict): w.plane.withdraw_operating(w.ws['id'],operation(w,1),w.actor)


@pytest.mark.parametrize('environment',['isolated','synthetic'])
def test_isolated_assessment_cannot_be_promoted_to_operating(reliability,environment):
    w=setup(reliability,environment=environment); sample(w); sample(w); assess(w)
    calls=[]; w.plane.operating_qualifier=lambda binding: calls.append(binding) or approval(w,binding)
    with pytest.raises(WorkspaceConflict): w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    assert not calls and not w.store.query('SELECT * FROM reliability_operating_qualifications')


@pytest.mark.parametrize('change',['erase','withdraw_adapter','membership','failed_observation','restore'])
def test_operating_qualification_drops_after_current_evidence_authority_or_restore_changes(reliability,change):
    w=setup(reliability,environment='approved_external'); source,_,_=sample(w); sample(w); assess(w)
    w.plane.operating_qualifier=lambda binding: approval(w,binding)
    w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    assert w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['qualified_operating_evidence']
    if change=='erase': erase(w,source['id'])
    elif change=='withdraw_adapter': w.plane.operating_qualifier=None
    elif change=='membership':
        with w.store.tx() as db: db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(w.ws['id'],))
    elif change=='failed_observation':
        w.control['mode']='timeout'; sample(w)
    else:
        from agent_market.workflow_backup import quarantine
        with w.store.tx() as db: quarantine(db)
        with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
            w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)
        assert not w.store.query('SELECT * FROM reliability_sources')
        return
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['qualified_operating_evidence']


def test_late_operating_approval_cannot_commit_changed_source_or_leak_binding(reliability):
    w=setup(reliability,environment='approved_external'); source,_,_=sample(w); sample(w); assess(w)
    def qualifier(binding):
        result=approval(w,binding); erase(w,source['id']); return result
    w.plane.operating_qualifier=qualifier
    with pytest.raises(WorkspaceConflict): w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    assert not w.store.query('SELECT * FROM reliability_operating_qualifications')


@pytest.mark.parametrize('bad', ['binding', 'expiry', 'hash', 'too_long'])
def test_operating_approval_binding_expiry_and_provenance_hashes_are_exact(reliability, bad):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    def qualifier(binding):
        value=approval(w,binding)
        if bad=='binding': return replace(value,binding_hash='0'*64)
        if bad=='expiry': return replace(value,expires=time.time()-1)
        if bad=='hash': return replace(value,qualification_hash='client-assertion')
        return replace(value,expires=time.time()+7200)
    w.plane.operating_qualifier=qualifier
    with pytest.raises((WorkspaceDenied,WorkspaceInvalid)):
        w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    assert not w.store.query('SELECT * FROM reliability_operating_qualifications')


def test_rebuilt_evidence_plane_cannot_reactivate_previous_operating_approval(reliability):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    w.plane.operating_qualifier=lambda binding: approval(w,binding)
    w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    rebuilt=ReliabilityEvidence(w.plane.access,w.plane.execution,evaluator=trusted,
                               cipher=w.plane.cipher,operating_qualifier=w.plane.operating_qualifier)
    rebuilt.current_report(w.ws['id'],w.rid,w.actor)
    current=rebuilt.get_agent_projection(w.ws['id'],w.rid,w.actor)
    assert current['independent_qualified'] and not current['qualified_operating_evidence']
    assert current['environment']=='approved_external'


def test_restore_marker_blocks_operating_qualification_even_with_retained_current_sources(reliability):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    w.plane.operating_qualifier=lambda binding: approval(w,binding)
    w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    with w.store.tx() as db:
        db.execute('INSERT INTO reliability_restore_blocks VALUES(?)',
                   ('operating:'+w.ws['id']+':'+str(w.rid)+':1',))
    result=w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)
    assert result['independent_qualified'] and not result['qualified_operating_evidence']


def test_tampered_operating_qualification_never_returns_operating_authority(reliability):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    w.plane.operating_qualifier=lambda binding: approval(w,binding)
    w.plane.qualify_operating(w.ws['id'],operation(w),w.actor)
    with w.store.tx() as db:
        db.execute("UPDATE reliability_operating_qualifications SET payload='{}' WHERE workspace_id=?",(w.ws['id'],))
    with pytest.raises(WorkspaceConflict):
        w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)


def test_late_evaluator_reconfiguration_does_not_publish_old_verdict_cache(reliability):
    w=setup(reliability); sample(w); sample(w)
    def stale_adapter(binding,bundle):
        w.plane.evaluator=None
        return trusted(binding,bundle)
    w.plane.evaluator=stale_adapter
    with pytest.raises(WorkspaceConflict): w.plane.current_report(w.ws['id'],w.rid,w.actor)
    assert w.plane._verdict_cache=={}
    assert not w.plane.get_agent_projection(w.ws['id'],w.rid,w.actor)['independent_qualified']


def test_operating_and_circuit_staff_transport_does_not_accept_client_verdicts(reliability):
    w=setup(reliability,environment='approved_external'); sample(w); sample(w); assess(w)
    from agent_market.workflows import runtime_for
    app=FastAPI(); app.include_router(router_for(w.plane.access,runtime_for(w.store,None),evidence=w.plane))
    base=w.rel_base+'/operating'
    with TestClient(app,base_url='https://private.test',raise_server_exceptions=False) as client:
        assert client.get(base+'/'+str(w.rid)).status_code==401
        state=client.get(base+'/'+str(w.rid),headers=w.headers['owner'])
        assert state.status_code==200 and not state.json()['result']['configured']
        assert client.post(base+'/qualify',json=operation(w),headers=w.headers['owner']).status_code==404
        w.plane.operating_qualifier=lambda binding: approval(w,binding)
        assert client.post(base+'/qualify',json=operation(w)|{'approved':True},headers=w.headers['owner']).status_code==400
        assert client.post(base+'/qualify',json=operation(w),headers=w.headers['viewer']).status_code==404
        response=client.post(base+'/qualify',json=operation(w),headers=w.headers['owner'])
        assert response.status_code==200 and response.json()['result']['qualified_operating_evidence']
        assert response.headers['cache-control']=='no-store' and 'approval_hash' not in response.text


def test_circuit_staff_transport_preserves_explicit_authority_and_no_dispatch(circuit):
    w=circuit
    app=FastAPI();app.include_router(router_for(w.access,w.runtime,evaluation=w.evaluation,
                                              trust=w.trust,routing=w.routing,circuit=w.circuit))
    base=w.base+'/circuits/'+str(w.rids[0])
    with TestClient(app,base_url='https://private.test',raise_server_exceptions=False) as client:
        assert client.get(base).status_code==401
        assert client.post(base+'/configure',json=circuit_config(w),headers=w.headers['viewer']).status_code==404
        assert client.post(base+'/configure',json=circuit_config(w),headers=w.headers['owner']|{'Origin':'https://other.test'}).status_code==403
        assert client.post(base+'/configure',json=circuit_config(w,resource_id=w.rids[1]),headers=w.headers['owner']).status_code==400
        response=client.post(base+'/configure',json=circuit_config(w),headers=w.headers['owner'])
        assert response.status_code==200 and response.json()['result']['state']=='closed'
        state=client.get(base,headers=w.headers['owner'])
        assert state.status_code==200 and state.headers['cache-control']=='no-store'
        assert not w.eval_calls and not w.calls
        assert 'session_ref' not in state.text and 'signature' not in state.text


def test_circuit_staff_probe_binding_never_dispatches_or_replays(circuit):
    w=circuit; opened(w); job,value=bind(w); before=len(w.eval_calls)
    app=FastAPI();app.include_router(router_for(w.access,w.runtime,evaluation=w.evaluation,
                                              trust=w.trust,routing=w.routing,circuit=w.circuit))
    base=w.base+'/circuits/'+str(w.rids[0])
    with TestClient(app,base_url='https://private.test',raise_server_exceptions=False) as client:
        response=client.post(base+'/refresh-probe',json=circuit_command(value['revision']),headers=w.headers['owner'])
        assert response.status_code==200 and response.json()['result']['waiting']
        assert len(w.eval_calls)==before
        assert client.post(base+'/dispatch',json=circuit_command(value['revision']),headers=w.headers['owner']).status_code==404
        assert len(w.eval_calls)==before
