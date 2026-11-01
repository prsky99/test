"""Discovery qualifies bounded candidates without weakening execution evidence."""
import time

import pytest

from agent_market.agent_access.catalog import CANDIDATE_LIMIT
from agent_market.capability_registry import Registry
from agent_market.concierge.discovery_state import execution_state
from tests.test_agent_adoption import adoption  # noqa: F401
from tests.test_workflow_fallback import routing  # noqa: F401


def ranked(core, ids):
    result=[]
    for rid in ids:
        resource=core.front.store.resource(rid)
        state=execution_state(core.front.store,resource)
        result.append({'id':rid,'name':resource['name'],'kind':resource['kind'],
            'url':'https://agentconcierge.biz/api/gateway/mcp/'+str(rid),'grade':'A',
            'capability_contract':{'connection_version_id':state['version_id'],
                'verified_at':state['verified_at'],'expires_at':state['expires_at']}})
    return result


@pytest.mark.parametrize('reason',['failed','expired','schema_changed','missing'])
def test_stale_first_candidate_does_not_hide_verified_alternatives(adoption,monkeypatch,reason):
    core,visitor,ids,calls,*_=adoption
    store=core.front.store;rows=ranked(core,ids);version=rows[0]['capability_contract']['connection_version_id']
    if reason=='failed':
        now=time.time();Registry(store).record(Registry(store).current(store.resource(ids[0])),
            scope='execution',outcome='failed',started=now,finished=now)
    elif reason=='expired':
        with store.tx()as db:db.execute('UPDATE capability_evidence SET expires=0 WHERE version_id=?',(version,))
    elif reason=='missing':
        with store.tx()as db:db.execute('DELETE FROM capability_evidence WHERE version_id=?',(version,))
    else:rows[0]['capability_contract']['connection_version_id']='cv_'+'0'*32
    searched=[]
    def search(task,kind=None,limit=1,**kwargs):
        searched.append((kind,limit));return rows[:limit]
    monkeypatch.setattr(core.front.rec,'search',search)
    value=core.catalog.discover({'task':'public documentation search','protocol':'mcp'})
    assert searched==[('mcp',CANDIDATE_LIMIT)]
    assert [r['id']for r in value['items']]==ids[1:]
    assert value['selected_contract']['resource_id']==ids[1]
    assert value['execution_authorized']is False and not calls


@pytest.mark.parametrize('protocol',['auto','any','mcp','a2a','x402'])
def test_qualification_preserves_protocol_policy_and_bounds(adoption,monkeypatch,protocol):
    core,visitor,ids,calls,*_=adoption
    rows=ranked(core,ids);searched=[]
    def search(task,kind=None,limit=1,**kwargs):
        searched.append((kind,limit))
        # No eligible A2A contract; automatic/Any must continue to MCP.
        return rows[:limit]if kind=='mcp'else []
    monkeypatch.setattr(core.front.rec,'search',search)
    result=core.catalog.discover({'task':'public documentation search','protocol':protocol})
    expected=['a2a','mcp']if protocol in ('auto','any')else[protocol]
    assert searched==[(p,CANDIDATE_LIMIT)for p in expected]
    assert result['status']==('matched'if protocol in ('auto','any','mcp')else'no_match')
    assert len(result['items'])<=3 and not calls
    assert all(item['protocol']=='mcp' and item['execution_authorized']is False for item in result['items'])


def test_no_qualification_without_real_current_evidence(adoption,monkeypatch):
    core,visitor,ids,calls,*_=adoption;rows=ranked(core,ids)
    with core.front.store.tx()as db:db.execute('DELETE FROM capability_evidence')
    monkeypatch.setattr(core.front.rec,'search',lambda *args,**kwargs:rows)
    value=core.catalog.discover({'task':'public documentation search','protocol':'mcp'})
    assert value['status']=='no_match' and value['items']==[]
    assert 'selected_contract'not in value and not calls


def test_current_snapshot_timestamps_replace_cached_candidate_fields(adoption,monkeypatch):
    core,visitor,ids,calls,*_=adoption;rows=ranked(core,ids[:1])
    rows[0]['capability_contract'].update(verified_at=0,expires_at=0)
    monkeypatch.setattr(core.front.rec,'search',lambda *args,**kwargs:rows)
    value=core.catalog.discover({'task':'public documentation search','protocol':'mcp'})
    item=value['items'][0]
    assert item['verified_at']>0 and item['expires_at']>time.time()
    assert item['verified_at']==value['selected_contract']['evidence']['verified_at']
    assert not calls
