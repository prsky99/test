"""Notification Preferences appears in Customer Requests without private transport data."""
import json
import time
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway.dashboard import dashboard_router
from agent_market.concierge.task_updates import MARKETING_NOTICE
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401
from tests.test_task_updates_security import updates  # noqa: F401
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

AUTH = STAFF
BASE = '/admin/api/needs/notifications'


@pytest.fixture
def hub(updates, tmp_path):
    store, front, client, add, headers, courier, data, vid = updates
    app = FastAPI()
    app.include_router(dashboard_router(store,store._path,
        'notification-hub-test',None,front=front,ssl_manager=Mock(get_status=lambda:{})))
    staff_session(store)
    with TestClient(app) as admin:
        yield store, front, client, headers, courier, data, vid, admin


def create(hub, **changes):
    _, _, client, headers, _, data, _, _ = hub
    response = client.post('/api/task-updates',headers=headers,json={**data,**changes})
    assert response.status_code == 201,response.text
    return response.json()['id']


def action(hub, wid, verb, **extra):
    _, _, client, headers, _, _, _, _ = hub
    return client.post('/api/task-updates/'+wid+'/action',headers=headers,json={'action':verb,**extra})


def detail(hub, wid):
    response = hub[-1].get(BASE+'/'+wid,headers=AUTH)
    assert response.status_code == 200,response.text
    return response.json()


def test_each_poll_preference_action_is_visible_with_exact_current_state(hub):
    store, front, _, _, courier, _, _, admin = hub
    wid = create(hub)
    expected = [('pause','paused'),('resume','active'),('renew','active'),('check','active'),('stop','revoked'),('delete','revoked')]
    previous_expiry = detail(hub,wid)['item']['expires']
    for verb,state in expected:
        response = action(hub,wid,verb)
        assert response.status_code == 200,response.text
        result = detail(hub,wid)
        assert result['item']['state'] == state
        assert any(row['action'] == ('checked' if verb == 'check' else verb) for row in result['history'])
        assert result['history'][0]['action'] == ('checked' if verb == 'check' else verb)
        if verb == 'renew':
            assert result['item']['expires'] > previous_expiry
        listed = admin.get(BASE,headers=AUTH,params={'q':wid,'state':state,'channel':'poll'}).json()
        assert listed['summary']['total'] == 1
        assert listed['items'][0]['id'] == wid
    assert result['item']['task'] == '' and result['deliveries'] == []
    assert not courier.events


@pytest.mark.parametrize('channel', ['webhook','a2a'])
def test_endpoint_confirmation_and_independent_marketing_withdrawal(hub, channel):
    store, front, _, headers, courier, _, vid, admin = hub
    wid = create(hub,channel=channel,url='https://inbox.example/private-route-secret',
        marketing=True,marketing_notice_version=MARKETING_NOTICE)
    result = detail(hub,wid)
    assert result['item']['state'] == 'pending_verification'
    assert result['item']['marketing_status'] == 'pending_verification'
    assert action(hub,wid,'verify',code=courier.challenges[-1]['verification_code']).status_code == 200
    result = detail(hub,wid)
    assert result['item']['state'] == 'active' and result['item']['destination_verified']
    assert result['item']['marketing_eligible']
    assert action(hub,wid,'withdraw_marketing').status_code == 200
    result = detail(hub,wid)
    assert result['item']['state'] == 'active' and result['item']['marketing_status'] == 'withdrawn'
    assert result['item']['marketing_withdrawn_at'] and not result['item']['marketing_eligible']
    assert any(r['action'] == 'confirmed' for r in result['history'])
    assert any(r['action'] == 'withdrawn' and r['purpose'] == 'marketing' for r in result['history'])
    assert result['policy']['read_only'] and not result['policy']['advertising_enabled']
    for response in (result, admin.get(BASE,headers=AUTH).json()):
        wire = json.dumps(response)
        for secret in ('private-route-secret',headers['X-Visitor-Token'],'code_hash','sealed','visitor_id','destination_hash','signing_secret'):
            assert secret not in wire
    assert not courier.events


def test_declined_unverified_request_is_removed_without_new_retained_profile(hub):
    store, _, _, _, _, _, _, admin = hub
    wid = create(hub,channel='webhook',url='https://inbox.example/private-pending')
    assert detail(hub,wid)['item']['state'] == 'pending_verification'
    assert action(hub,wid,'decline').status_code == 200
    assert admin.get(BASE+'/'+wid,headers=AUTH).status_code == 404
    assert admin.get(BASE,headers=AUTH).json()['summary']['total'] == 0
    for table in ('agent_task_watches','agent_task_permissions','agent_task_destination_checks','agent_task_events','agent_marketing_permissions'):
        column = 'id' if table == 'agent_task_watches' else 'watch_id'
        assert not store.query(f'SELECT 1 FROM {table} WHERE {column}=?',(wid,))


def test_auth_validation_and_no_admin_preference_mutation(hub):
    _, _, client, headers, _, _, _, admin = hub
    wid = create(hub)
    for path in (BASE,BASE+'/'+wid):
        assert admin.get(path).status_code in (401,403)
        assert admin.post(path,headers=AUTH,json={'action':'resume'}).status_code in (404,405)
    for params in ({'limit':101},{'limit':0},{'offset':-1},{'state':"active' OR 1=1"},{'channel':'ftp'},{'q':'x'*161}):
        assert admin.get(BASE,headers=AUTH,params=params).status_code == 422
    assert admin.get(BASE,headers=AUTH,params={'q':"' OR 1=1 --"}).json()['items'] == []
    assert admin.get(BASE+'/bad-id',headers=AUTH).status_code == 404
    other = ask(client,'hello')['visitor']['token']
    assert client.post('/api/task-updates/'+wid+'/action',headers={'X-Visitor-Token':other},json={'action':'check'}).status_code == 400
    assert action(hub,wid,'pause').status_code == 200
    assert action(hub,wid,'check').status_code == 400
    assert not any(r['action']=='checked' for r in detail(hub,wid)['history'])


def test_pagination_literal_wildcard_search_and_latest_activity_order(hub):
    store, _, _, _, _, _, vid, admin = hub
    first = create(hub)
    now = time.time()
    with store.tx() as db:
        for number in range(55):
            db.execute('''INSERT INTO agent_task_watches (id,visitor_id,task,protocol,channel,state,created,expires,notice_version,authority)
                SELECT ?,visitor_id,?,protocol,channel,state,?,?,notice_version,authority FROM agent_task_watches WHERE id=?''',
                ('tw_'+f'{number:032x}',f'Synthetic task {number}',now+number,now+10000,first))
    result = admin.get(BASE,headers=AUTH).json()
    assert result['summary']['total'] == 56 and len(result['items']) == 50
    assert result['pagination']['has_more']
    second = admin.get(BASE,headers=AUTH,params={'offset':50}).json()
    assert len(second['items']) == 6 and not second['pagination']['has_more']
    assert not set(r['id'] for r in result['items']) & set(r['id'] for r in second['items'])
    assert admin.get(BASE,headers=AUTH,params={'q':'%'}).json()['summary']['total'] == 0
    with store.tx() as db:
        db.execute("INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,'renew','task_updates','test',?)",(first,vid,now+100))
    assert admin.get(BASE,headers=AUTH).json()['items'][0]['id'] == first


def test_expired_requests_and_bounded_history_are_truthful(hub):
    store, _, _, _, _, _, vid, admin = hub
    wid = create(hub)
    with store.tx() as db:
        db.execute('UPDATE agent_task_watches SET expires=? WHERE id=?',(time.time()-1,wid))
        db.executemany("INSERT INTO agent_task_permissions (watch_id,visitor_id,action,purpose,notice_version,at) VALUES (?,?,'renew','task_updates','test',?)",[(wid,vid,time.time()+i) for i in range(105)])
    result = detail(hub,wid)
    assert result['item']['state'] == 'expired' and not result['item']['permission_current']
    assert len(result['history']) == 100 and result['history_total'] == 106
    assert admin.get(BASE,headers=AUTH,params={'state':'expired'}).json()['summary']['stopped'] == 1
