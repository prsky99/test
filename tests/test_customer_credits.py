"""Isolated nonmonetary credits and customer/staff authority regressions."""
from concurrent.futures import ThreadPoolExecutor
import secrets
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.customer_credits import CustomerCredits, CreditRequired, VERSION, DIGEST, WELCOME_CREDITS
from agent_market.customer_credit_service import router_for
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_access import WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict
from tests.test_customer_organizations import orgs  # noqa: F401


def acceptance():
    return dict(version=VERSION,digest=DIGEST,terms_accepted=True,privacy_acknowledged=True,adult_authority=True)

@pytest.fixture
def credits(orgs):
    w=orgs;w.credits=CustomerCredits(w.core);return w


def test_enrollment_is_exact_once_and_records_separate_choices(credits):
    w=credits;c=w.credits;a=w.customers[0]
    assert c.status(a)['balance']==0
    for key in acceptance():
        invalid=acceptance();invalid.pop(key)
        with pytest.raises(WorkspaceInvalid):c.enroll(invalid,a)
    invalid=acceptance();invalid['privacy_acknowledged']=False
    with pytest.raises(WorkspaceInvalid):c.enroll(invalid,a)
    c.enroll(acceptance(),a);c.enroll(acceptance(),a)
    assert c.status(a)['balance']==WELCOME_CREDITS
    with w.core.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM customer_credit_acceptances').fetchone()[0]==1
    current=c.status(a);c.close({'revision':current['revision'],'confirm':'CLOSE'},a)
    c.enroll(acceptance(),a)
    assert c.status(a)['balance']==WELCOME_CREDITS and len(c.status(a)['history'])==3


def test_previous_three_credit_enrollment_stays_active_without_regrant(credits,monkeypatch):
    from agent_market import customer_credits as module
    w=credits;c=w.credits;a=w.customers[0]
    old_version='workspace-free-2026-10-20-v1'
    old_digest='c42935fbe9c8e31e48654c25c27deb4f0bd7a9ecf0bebb9bb464ed39386a449d'
    old_body=dict(acceptance(),version=old_version,digest=old_digest)
    with monkeypatch.context() as legacy:
        legacy.setattr(module,'VERSION',old_version)
        legacy.setattr(module,'DIGEST',old_digest)
        legacy.setattr(module,'TERMS',module.TERMS.replace('100 credits','3 credits'))
        legacy.setattr(module,'WELCOME_CREDITS',3)
        c.enroll(old_body,a)
    # Existing use and signed evidence survive the new signup policy.
    with w.core.tx() as db:c.saved(db,w.organization['id'],'legacy-workflow',1,a)
    state=c.status(a)
    assert state['enrolled'] and state['balance']==2 and state['welcome_credits']==100
    assert c.enroll(acceptance(),a)['replayed']
    c.close({'revision':state['revision'],'confirm':'CLOSE'},a)
    c.enroll(acceptance(),a)
    assert c.status(a)['enrolled'] and c.status(a)['balance']==2
    with pytest.raises(WorkspaceInvalid):c.enroll(old_body,w.customers[1])
    c.enroll(acceptance(),w.customers[1])
    assert c.status(w.customers[1])['balance']==100


def test_create_predownload_edits_repeat_download_and_postdownload_edit(credits):
    w=credits;c=w.credits;a=w.customers[0];ws=w.organization['id'];c.enroll(acceptance(),a)
    with w.core.tx() as db:c.saved(db,ws,'workflow-one',1,a)
    with w.core.tx() as db:c.saved(db,ws,'workflow-two',1,a,parent='workflow-one')
    assert c.status(a)['balance']==WELCOME_CREDITS-1
    c.downloaded(ws,'workflow-two',1,a);c.downloaded(ws,'workflow-two',1,a)
    assert c.status(a)['balance']==WELCOME_CREDITS-1 and c.quote(ws,'workflow-one',a)==1
    with w.core.tx() as db:c.saved(db,ws,'workflow-three',1,a,parent='workflow-one')
    assert c.status(a)['balance']==WELCOME_CREDITS-2
    with w.core.tx() as db:c.saved(db,ws,'workflow-four',1,a,parent='workflow-three')
    assert c.status(a)['balance']==WELCOME_CREDITS-2


def test_atomic_rollback_insufficient_balance_concurrency_and_scope(credits):
    w=credits;c=w.credits;a=w.customers[0];ws=w.organization['id'];c.enroll(acceptance(),a)
    c.admin_change(w.access,a.customer_id,dict(revision=1,delta=3-WELCOME_CREDITS,status='active',reason='Synthetic three-credit concurrency budget',request_id=secrets.token_hex(16)),w.staff[1])
    with pytest.raises(RuntimeError):
        with w.core.tx() as db:
            c.saved(db,ws,'rolled-back',1,a)
            raise RuntimeError()
    assert c.status(a)['balance']==3
    def save(i):
        try:
            with w.core.tx() as db:c.saved(db,ws,'parallel-'+str(i),1,a)
            return True
        except CreditRequired:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(save,range(8)))==3
    assert c.status(a)['balance']==0
    with pytest.raises(CreditRequired):c.downloaded(ws,'unpaid',1,a)
    assert c.status(w.customers[1])['balance']==0


def test_staff_adjustment_cas_idempotency_no_fabricated_enrollment(credits):
    w=credits;c=w.credits;a=w.customers[0];c.enroll(acceptance(),a)
    command=dict(revision=1,delta=100000-WELCOME_CREDITS,status='active',reason='Authorized test credit allocation',request_id=secrets.token_hex(16))
    with pytest.raises(WorkspaceDenied):c.admin_change(w.access,w.customers[1].customer_id,command,w.staff[1])
    result=c.admin_change(w.access,a.customer_id,command,w.staff[1])
    assert result['balance']==100000
    assert c.admin_change(w.access,a.customer_id,command,w.staff[1])['balance']==100000
    with pytest.raises(WorkspaceConflict):c.admin_change(w.access,a.customer_id,dict(command,delta=2),w.staff[1])
    with pytest.raises(WorkspaceInvalid):c.admin_change(w.access,a.customer_id,dict(command,delta=True),w.staff[1])
    with pytest.raises(WorkspaceConflict):c.admin_change(w.access,a.customer_id,dict(command,request_id=secrets.token_hex(16)),w.staff[1])


def test_transport_csrf_idor_recharge_absence_and_content(credits):
    w=credits;app=FastAPI();app.include_router(router_for(w.core,w.access))
    with TestClient(app,base_url='https://customer.test') as client:
        assert client.get('/api/customer-credits').status_code==401
        client.cookies.set(COOKIE,w.auths[0]['session_token'])
        assert client.post('/api/customer-credits/enroll',json=acceptance()).status_code==403
        headers={'Origin':'https://customer.test','X-Customer-CSRF':w.core.csrf(w.auths[0]['session_token'])}
        assert client.post('/api/customer-credits/enroll',json=acceptance(),headers=headers).status_code==200
        assert client.post('/api/customer-credits/top-up',json={},headers=headers).status_code==404
        assert client.get('/api/customer-credits?customer_id='+w.customers[1].customer_id).json()['credits']['balance']==WELCOME_CREDITS
        assert client.post('/api/customer-credits/close',json={'revision':1,'confirm':'CLOSE'},headers=dict(headers,Origin='https://evil.test')).status_code==403
        page=client.get('/customer/plan');assert 'Coming soon' in page.text
        assert "default-src 'none'" in page.headers['Content-Security-Policy']
        w.core.logout(w.auths[0]['session_token'])
        assert client.get('/api/customer-credits').status_code==401


def test_signed_state_and_history_tamper_rejected(credits):
    w=credits;c=w.credits;a=w.customers[0];c.enroll(acceptance(),a)
    with w.core.tx() as db:db.execute('UPDATE customer_credit_accounts SET balance=100000')
    with pytest.raises(WorkspaceConflict):c.status(a)


def test_admin_transport_rbac_csrf_audit_and_signed_history(credits):
    w=credits;c=w.credits;a=w.customers[0];c.enroll(acceptance(),a)
    app=FastAPI();app.include_router(router_for(w.core,w.access,admin=True))
    with TestClient(app,base_url='https://admin.test') as client:
        path='/admin/api/customer-credits/'+a.customer_id
        assert client.get('/admin/api/customer-credits').status_code==401
        headers={'Authorization':'Bearer '+w.raw_staff,'X-Dashboard':'1','Origin':'https://admin.test'}
        assert client.get('/admin/api/customer-credits',headers=headers).status_code==200
        change=dict(revision=1,delta=20,status='active',reason='Synthetic support correction',request_id=secrets.token_hex(16))
        assert client.post(path,json=change,headers=dict(headers,Origin='https://evil.test')).status_code==403
        assert client.post(path,json=change,headers=headers).status_code==200
        history=client.get(path+'/history',headers=headers);assert history.status_code==200
        assert 'session_ref' not in history.text and 'Synthetic support correction' in history.text
        with w.core.tx() as db:db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
        assert client.post(path,json=change,headers=headers).status_code==403


def test_restore_does_not_revive_historical_spendable_balance(credits):
    w=credits;c=w.credits;a=w.customers[0];c.enroll(acceptance(),a)
    with w.core.tx() as db:db.execute('INSERT INTO customer_credit_restore_blocks VALUES(?)',(a.customer_id,))
    assert c.status(a)['status']=='review_required' and not c.status(a)['enrolled']
    with pytest.raises(WorkspaceDenied):c.enroll(acceptance(),a)
    with pytest.raises(WorkspaceDenied):c.admin_change(w.access,a.customer_id,dict(revision=1,delta=0,status='active',reason='Restore approval attempt',request_id=secrets.token_hex(16)),w.staff[1])
    with pytest.raises(CreditRequired):
        with w.core.tx() as db:c.saved(db,w.organization['id'],'restored-artifact',1,a)


def test_numeric_consent_does_not_count_as_explicit_boolean_choice(credits):
    w=credits;body=acceptance();body['terms_accepted']=1
    with pytest.raises(WorkspaceInvalid):w.credits.enroll(body,w.customers[0])


def test_deleted_account_credit_evidence_removed_after_retention(credits):
    import time
    w=credits;c=w.credits;a=w.customers[0];c.enroll(acceptance(),a)
    with w.core.tx() as db:
        db.execute('INSERT INTO customer_account_deletions VALUES(?,1,?,?,?)',(a.customer_id,time.time()-91*86400,'{}','test-only'))
        db.execute('UPDATE customer_identities SET active=0 WHERE id=?',(a.customer_id,))
    assert c.prune()==1
    assert w.store._db.execute('SELECT COUNT(*) FROM customer_credit_accounts').fetchone()[0]==0
    assert w.store._db.execute('SELECT COUNT(*) FROM customer_credit_events').fetchone()[0]==0
