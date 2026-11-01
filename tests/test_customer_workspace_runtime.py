"""Customer read/execute adapters preserve independent customer identity."""
import json

import pytest

from agent_market.customer_identity import CustomerIdentity
from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess, CustomerRuntimeActor
from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_execution import WorkspaceExecution, NOTICE
from tests.test_customer_identity import customer_world, login
from tests.test_workspace_execution import execution_world


@pytest.fixture
def customer_run():
    source=execution_world();oidc=customer_world()
    store,access,staff,_,proxy,ws,draft,version=source
    identity=CustomerIdentity(store,b'synthetic-customer-key-32bytes!!!',oidc.config,oidc.http)
    oidc.core=identity
    auth=login(oidc)
    identity.set_link(access,ws,{'customer_id':auth['customer_id'],'role':'runner','active':True,'revision':0},staff[1])
    adapter=CustomerWorkspaceAccess(access,identity)
    session=identity.actor(auth['session_token'])
    with identity.tx() as db:scope=identity.authorize(db,session,ws,'execute')
    actor=adapter.from_scope(scope)
    executor=WorkspaceExecution(adapter,proxy)
    try:yield source,oidc,identity,adapter,actor,executor,auth
    finally:store._db.close();oidc.http.close();oidc.store._db.close()


def test_customer_one_call_uses_separate_attribution_and_cannot_enter_staff_runner(customer_run):
    source,_,identity,adapter,actor,executor,_=customer_run
    store,_,staff,staff_executor,proxy,ws,draft,version=source
    assert isinstance(actor,CustomerRuntimeActor) and actor.user_id.startswith('cu_')
    plan=executor.prepare(ws,draft,version,{'snapshot_revision':1},actor)
    with pytest.raises(WorkspaceDenied):
        staff_executor.execute(ws,draft,version,{'ticket_id':plan['ticket_id'],'authorized':True,'notice':NOTICE},staff[1])
    run=executor.execute(ws,draft,version,{'ticket_id':plan['ticket_id'],'authorized':True,'notice':NOTICE},actor)
    assert run['status']=='succeeded' and proxy.calls==1
    payload=json.loads(store._db.execute('SELECT payload FROM workspace_private_tickets WHERE id=?',(plan['ticket_id'],)).fetchone()[0])
    assert payload['actor_kind']=='customer' and payload['actor_user_id']==actor.customer_id
    assert executor.run(ws,draft,version,run['id'],actor)['output']==run['output']
    assert not hasattr(adapter,'save_draft') and not hasattr(adapter,'set_member')
    assert not store._db.execute("SELECT name FROM sqlite_schema WHERE name='workflow_runs'").fetchall()


@pytest.mark.parametrize('fault',['link','session','workspace'])
def test_customer_current_authority_stops_business_dispatch(customer_run,fault):
    source,_,identity,_,actor,executor,auth=customer_run
    store,access,staff,_,proxy,ws,draft,version=source
    plan=executor.prepare(ws,draft,version,{'snapshot_revision':1},actor)
    def revoke():
        assert not store._db.in_transaction
        if fault=='session':identity.logout(auth['session_token'])
        elif fault=='link':identity.set_link(access,ws,{'customer_id':actor.customer_id,'role':'viewer','active':False,'revision':1},staff[1])
        else:access.set_active(ws,{'active':False,'revision':access.workspace(ws,staff[1])['revision']},staff[1])
    proxy.before=revoke
    run=executor.execute(ws,draft,version,{'ticket_id':plan['ticket_id'],'authorized':True,'notice':NOTICE},actor)
    assert run['status']=='denied' and run['output'] is None and proxy.calls==0


def test_customer_bff_reference_reconstructed_at_dispatch_and_independent_read_scope(customer_run):
    source,_,identity,adapter,_,executor,auth=customer_run
    store,_,_,_,proxy,ws,draft,version=source
    capability=identity.issue_token(auth['session_token'],ws,'execute')
    actor=adapter.from_scope(identity.validate_token(capability['access_token'],ws,'execute'))
    plan=executor.prepare(ws,draft,version,{'snapshot_revision':1},actor)
    def withdraw():
        with identity.tx() as db:db.execute('UPDATE customer_bff_tokens SET revoked=1 WHERE id=?',(actor.token_ref,))
    proxy.before=withdraw
    run=executor.execute(ws,draft,version,{'ticket_id':plan['ticket_id'],'authorized':True,'notice':NOTICE},actor)
    assert run['status']=='denied' and proxy.calls==0
    read=identity.issue_token(auth['session_token'],ws,'read')
    reader=adapter.from_scope(identity.validate_token(read['access_token'],ws,'read'))
    assert executor.run(ws,draft,version,run['id'],reader)['status']=='denied'
    with pytest.raises(WorkspaceDenied):executor.prepare(ws,draft,version,{'snapshot_revision':1},reader)
