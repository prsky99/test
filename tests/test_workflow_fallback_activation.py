"""Isolated activation preflight and fail-closed launch boundaries."""
# ruff: noqa: F401,F811
import json
import time

import pytest

from agent_market.workflow_fallback import RoutingDenied
from agent_market.capability_registry import canonical
from tests.test_workflow_fallback import routing, config
from tests.test_workflow_fallback_api import routing_api, H
from tests.test_workflow_runtime import wait


def canary(routing):
    rt,wf,ids,*_=routing
    config(rt,wf,ids)
    assert wait(rt,rt.submit(wf))['status']=='succeeded'
    config(rt,wf,ids,'canary')
    return rt,wf,ids


def test_empty_preflight_does_not_enable_or_create_evidence(routing,monkeypatch):
    rt,*_=routing
    before=rt.store._db.total_changes
    monkeypatch.setattr(rt.proxy,'_client',lambda **kw:pytest.fail('Preflight must never call a provider.'))
    status=rt.fallback.control_status()
    assert status['activation']['reason']=='NO_POLICY'
    assert status['activation']['can_enable'] is False
    assert rt.store._db.total_changes==before
    with pytest.raises(RoutingDenied,match='shadow and canary'):
        rt.fallback.set_control({'enabled':True,'revision':0},1)
    assert rt.fallback.control()['revision']==0
    assert not rt.store.query('SELECT * FROM workflow_fallback_audit')


def test_shadow_success_still_requires_explicit_canary_promotion(routing):
    rt,wf,ids,*_=routing;config(rt,wf,ids)
    assert wait(rt,rt.submit(wf))['status']=='succeeded'
    status=rt.fallback.activation_status()
    assert status['policies']==[{'workflow_id':wf['id'],'eligible':False,'reason':'CANARY_REQUIRED'}]
    with pytest.raises(RoutingDenied):rt.fallback.set_control({'enabled':True,'revision':0},1)


def test_current_canary_can_enable_without_dispatching_during_preflight(routing):
    rt,wf,ids=canary(routing);calls=routing[3];calls.clear()
    before=rt.store._db.total_changes
    status=rt.fallback.activation_status()
    assert status['can_enable'] and status['eligible_policies']==1
    assert status['independence_scope']=='negative_dependency_guards_only'
    assert not calls and rt.store._db.total_changes==before
    assert rt.fallback.set_control({'enabled':True,'revision':0},1)['enabled']
    assert not calls


@pytest.mark.parametrize('change,reason',[
    ('expires','POLICY_EXPIRED'),('exhausted','CANARY_EXHAUSTED'),
    ('graph','DEFINITION_CHANGED'),('signature','PAIR_REVIEW_REQUIRED'),
    ('shadow','SHADOW_REQUIRED'),('evidence','PAIR_REVIEW_REQUIRED'),
    ('binding','PAIR_REVIEW_REQUIRED'),('alias','PAIR_REVIEW_REQUIRED'),
])
def test_drift_blocks_enabling_and_preserves_disable(routing,change,reason):
    rt,wf,ids=canary(routing)
    if change=='expires':
        payload,row=rt.fallback.policy(wf['id']);payload['expires']=time.time()-1
        with rt.store.tx() as db:db.execute('UPDATE workflow_fallback_policies SET payload=?,signature=? WHERE workflow_id=?',
            (canonical(payload),rt.fallback.sign(payload),wf['id']))
    else:
        with rt.store.tx() as db:
            if change=='exhausted':db.execute('UPDATE workflow_fallback_policies SET admitted=100')
            elif change=='graph':db.execute('UPDATE agent_workflows SET is_active=0 WHERE id=?',(wf['id'],))
            elif change=='signature':db.execute("UPDATE workflow_fallback_policies SET signature='invalid'")
            elif change=='shadow':db.execute('DELETE FROM workflow_fallback_shadow')
            elif change=='evidence':db.execute('UPDATE capability_evidence SET expires=0')
            elif change=='binding':db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?",(ids[1],))
            elif change=='alias':db.execute("UPDATE resources SET details=? WHERE id=?",
                (json.dumps({'remotes':[{'url':'https://primary.example/mcp'}]}),ids[1]))
    status=rt.fallback.activation_status()
    assert status['can_enable'] is False and status['policies'][0]['reason']==reason
    with pytest.raises(RoutingDenied):rt.fallback.set_control({'enabled':True,'revision':0},1)
    assert rt.fallback.set_control({'enabled':False,'revision':0},1)['revision']==1


def test_execution_pause_blocks_enable_with_explicit_pause_reason(routing):
    rt,_,_=canary(routing)
    with rt.store.tx() as db:db.execute('UPDATE execution_controls SET invoke_enabled=0')
    status=rt.fallback.activation_status()
    assert not status['can_enable']
    assert status['reason']=='EXECUTION_PAUSED'
    with pytest.raises(RoutingDenied):rt.fallback.set_control({'enabled':True,'revision':0},1)


def test_preflight_is_bounded_and_does_not_certify_unchecked_policies(routing):
    rt,wf,ids,*_=routing;config(rt,wf,ids)
    payload,_=rt.fallback.policy(wf['id'])
    with rt.store.tx() as db:
        for wid in range(1000,1101):
            value={**payload,'workflow_id':wid}
            db.execute('INSERT INTO workflow_fallback_policies VALUES (?,?,?,?,0)',
                (wid,1,canonical(value),rt.fallback.sign(value)))
    status=rt.fallback.activation_status()
    assert status['truncated'] and status['policies_checked']==100 and len(status['policies'])==100
    assert not status['can_enable']


def test_activation_api_is_private_and_gate_applies_to_both_admin_routes(routing_api):
    routing,public,admin=routing_api;rt,*_=routing
    for path in ('/admin/api/fallback-control','/admin/api/v2/gateway/controls'):
        assert public.get(path).status_code==404
        assert admin.get(path).status_code in (401,403)
        assert admin.get(path,headers={**H,'Authorization':'Bearer fallback-test-secret'}).status_code in (401,403)
        response=admin.get(path,headers=H)
        assert response.status_code==200 and 'no-store' in response.headers['cache-control']
        data=response.json();control=data['fallback'] if '/v2/' in path else data
        assert control['activation']['reason']=='NO_POLICY'
        assert 'primary.example' not in response.text and 'signature' not in response.text
    legacy=admin.put('/admin/api/fallback-control',headers=H,json={'enabled':True,'revision':0})
    modern=admin.post('/admin/api/v2/gateway/controls',headers=H,json={
        'target':'fallback','state':{'enabled':True,'revision':0},'reason':'Isolated activation check'})
    assert legacy.status_code==modern.status_code==409
    assert rt.fallback.control()['revision']==0
