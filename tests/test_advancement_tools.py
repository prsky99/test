"""Synthetic private accounting/support/readiness; no money, model or network."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import sqlite3
from threading import Barrier, RLock
import time
from types import SimpleNamespace

import pytest

from agent_market.advancement_readiness import AdvancementReadiness, CurrentEvidence, CATEGORIES, NOTICE as READY_NOTICE
from agent_market.shadow_ledger import ShadowLedger, NOTICE as LEDGER_NOTICE
from agent_market.workflow_support import WorkflowSupport, NOTICE as SUPPORT_NOTICE, APPLY_NOTICE
from agent_market.workspace_access import WorkspaceAccess, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_workspace_access import workspace_world, definition, draft_body


@pytest.fixture
def tools(tmp_path):
    store, access, actors = workspace_world(str(tmp_path/'synthetic-advancement.sqlite3'))
    ws = access.provision({'name': 'Synthetic review workspace', 'owner_id': 1}, actors[1])['id']
    access.set_member(ws, {'user_id': 2, 'role': 'editor', 'active': True, 'revision': 0}, actors[1])
    access.set_member(ws, {'user_id': 3, 'role': 'viewer', 'active': True, 'revision': 0}, actors[1])
    draft = access.save_draft(ws, draft_body(definition()), actors[1])
    snapshot = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    value = {'store': store, 'access': access, 'actors': actors, 'ws': ws, 'draft': draft, 'snapshot': snapshot,
             'ledger': ShadowLedger(access), 'support': WorkflowSupport(access), 'readiness': AdvancementReadiness(access)}
    yield value
    store._db.close()


def approve(t, n=1, amount=100, asset='TEST_UNIT'):
    return t['ledger'].approve(t['ws'], {'operation_id':'slop_'+format(n,'032x'), 'asset':asset,
        'units':amount, 'authorized':True, 'notice':LEDGER_NOTICE}, t['actors'][1])


def event(operation, n=1, outcome='completed', amount=100):
    return {'operation_id':operation['id'], 'event_id':'slev_'+format(1000+n,'032x'),
        'revision':operation['revision'], 'outcome':outcome, 'settled_units':amount,
        'authorized':True, 'notice':LEDGER_NOTICE}


def proposal(t, changes=None):
    return t['support'].propose(t['ws'], t['draft']['id'], t['snapshot']['id'],
        {'snapshot_revision':1, 'draft_revision':1, 'changes':changes or {'name':'Reviewed private draft'},
         'documents':['safe-change-review'], 'authorized':True, 'notice':SUPPORT_NOTICE}, t['actors'][1])


def test_completed_partial_unknown_and_full_reversal_are_exact_simulated_entries(tools):
    t=tools; ledger=t['ledger']; actor=t['actors'][1]; ws=t['ws']
    approved=approve(t); command=event(approved)
    posted=ledger.post(ws,command,actor)
    assert posted['status']=='completed' and posted['settled_units']==100 and not posted['actual_money']
    assert ledger.post(ws,command,actor)['replayed']
    reverse={k:command[k] for k in ('operation_id','authorized','notice')}
    reverse.update(event_id='slev_'+'f'*32,revision=posted['revision'])
    assert ledger.reverse(ws,reverse,actor)['status']=='reversed'
    assert ledger.reverse(ws,reverse,actor)['replayed']
    reverse['event_id']='slev_'+'e'*32; reverse['revision']+=1
    with pytest.raises(WorkspaceConflict): ledger.reverse(ws,reverse,actor)
    uncertain=approve(t,2)
    unknown=ledger.post(ws,event(uncertain,2,'unknown',0),actor)
    assert unknown['status']=='unknown'
    settled=ledger.reconcile(ws,event(unknown,3,'partial',31),actor)
    assert settled['status']=='partial' and settled['settled_units']==31
    summary=ledger.summary(ws,actor)
    assert summary['balanced'] and set(summary['asset_balances'].values())=={0}
    assert summary['entries']==6 and not summary['commercial_enabled']
    assert not t['store']._db.execute("SELECT 1 FROM sqlite_schema WHERE name='workflow_runs'").fetchall()


def test_external_event_id_dedup_is_independent_of_logical_operation(tools):
    t=tools; one=approve(t); two=approve(t,2); command=event(one)
    t['ledger'].post(t['ws'],command,t['actors'][1])
    changed={**command,'operation_id':two['id']}
    with pytest.raises(WorkspaceConflict): t['ledger'].post(t['ws'],changed,t['actors'][1])
    assert t['ledger'].summary(t['ws'],t['actors'][1])['entries']==2


@pytest.mark.parametrize('value',[True,False,-1,0,1.1,'12',10**12+1])
def test_accounting_units_are_bounded_exact_integers(tools,value):
    with pytest.raises(WorkspaceInvalid): approve(tools,amount=value)


@pytest.mark.parametrize('actor_id',[2,3,5])
def test_only_a_current_workspace_owner_can_authorize_accounting(tools,actor_id):
    t=tools
    with pytest.raises(WorkspaceDenied): t['ledger'].approve(t['ws'],
        {'operation_id':'slop_'+'d'*32,'asset':'TEST_UNIT','units':1,'authorized':True,'notice':LEDGER_NOTICE},t['actors'][actor_id])


def test_approval_does_not_survive_member_revision_aba_but_unknown_review_uses_current_owner(tools):
    t=tools; op=approve(t); db=t['store']._db
    with db:
        db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=1',(t['ws'],))
    with pytest.raises(WorkspaceConflict): t['ledger'].post(t['ws'],event(op),t['actors'][1])
    fresh=approve(t,2); unknown=t['ledger'].post(t['ws'],event(fresh,2,'unknown',0),t['actors'][1])
    with db: db.execute('UPDATE admin_sessions SET expires_at=0 WHERE user_id=1')
    # A currently authenticated alternative owner may reconcile; no old execution is replayed.
    with db:
        db.execute('INSERT INTO workspace_memberships VALUES(?,?,?,1,1,?)',(t['ws'],4,'owner',time.time()))
    result=t['ledger'].reconcile(t['ws'],event(unknown,3,'not_received',0),t['actors'][4])
    assert result['status']=='not_received'


def test_accepted_accounting_sql_fault_rolls_back_operation_event_and_entries(tools,monkeypatch):
    t=tools; op=approve(t); original=t['access']._audit
    def fail(db,actor,ws,action,*args):
        original(db,actor,ws,action,*args)
        if action=='shadow.post':
            assert db.execute('SELECT COUNT(*) FROM workspace_shadow_entries').fetchone()[0]==2
            raise sqlite3.OperationalError('Synthetic accepted write failure')
    with monkeypatch.context() as patch:
        patch.setattr(t['access'],'_audit',fail)
        with pytest.raises(WorkspaceConflict): t['ledger'].post(t['ws'],event(op),t['actors'][1])
    summary=t['ledger'].summary(t['ws'],t['actors'][1])
    assert summary['entries']==0 and summary['operations'][0]['status']=='approved'
    assert t['ledger'].post(t['ws'],event(op),t['actors'][1])['status']=='completed'


def test_orphan_or_modified_ledger_evidence_fails_closed(tools):
    t=tools; op=approve(t); t['ledger'].post(t['ws'],event(op),t['actors'][1])
    with t['store']._db as db:
        db.execute("INSERT INTO workspace_shadow_entries VALUES(?,0,?,?,?,?)",
            ('slev_'+'c'*32,t['ws'],op['id'],'{}','bad'))
    with pytest.raises(WorkspaceConflict): t['ledger'].summary(t['ws'],t['actors'][1])


def test_reviewed_json_patch_applies_only_a_new_private_revision(tools):
    t=tools; support=t['support']; p=proposal(t,{'name':'Reviewed result',
        'literal_input':{'node_id':'search','input':{'query':'Typed storage research'}}})
    assert [item['path'] for item in p['patch']]==['/name','/definition/nodes/1/data/input']
    assert not p['executed'] and not p['published'] and not p['model_generated']
    result=support.apply(t['ws'],p['id'],{'authorized':True,'notice':APPLY_NOTICE},t['actors'][1])
    assert result['revision']==2 and result['applied'] and not result['executed']
    assert support.apply(t['ws'],p['id'],{'authorized':True,'notice':APPLY_NOTICE},t['actors'][1])['replayed']
    draft=t['access'].draft(t['ws'],t['draft']['id'],t['actors'][1])
    assert draft['name']=='Reviewed result' and draft['definition']['nodes'][1]['data']['input']['query']=='Typed storage research'
    assert t['access'].version(t['ws'],t['draft']['id'],t['snapshot']['id'],t['actors'][1])['snapshot']['name']==t['draft']['name']


@pytest.mark.parametrize('changes',[{'command':'publish now'},{'name':'token=synthetic-secret'},
    {'description':'/private/tmp/internal.txt'},{'literal_input':{'node_id':'search','input':{'query':'{{$prev.output}}'}}}])
def test_support_refuses_unsafe_changes_and_never_interprets_arbitrary_patch(tools,changes):
    with pytest.raises(WorkspaceInvalid): proposal(tools,changes)
    assert tools['access'].draft(tools['ws'],tools['draft']['id'],tools['actors'][1])['revision']==1


def test_support_current_revocation_blocks_detail_and_history_has_no_patch_body(tools):
    t=tools; p=proposal(t,{'description':'Private proposed context'})
    t['access'].revoke_version(t['ws'],t['draft']['id'],t['snapshot']['id'],{'revision':1},t['actors'][1])
    with pytest.raises(WorkspaceDenied): t['support'].proposal(t['ws'],p['id'],t['actors'][1])
    assert 'Private proposed context' not in json.dumps(t['support'].proposals(t['ws'],t['actors'][1]))
    with pytest.raises(WorkspaceDenied): t['support'].apply(t['ws'],p['id'],{'authorized':True,'notice':APPLY_NOTICE},t['actors'][1])


def test_support_applied_sql_then_failure_rolls_back_revision_and_consumption(tools,monkeypatch):
    t=tools; p=proposal(t); original=t['access']._audit
    def fail(db,actor,ws,action,*args):
        original(db,actor,ws,action,*args)
        if action=='support.apply':
            assert db.execute('SELECT revision FROM workspace_drafts').fetchone()[0]==2
            raise sqlite3.OperationalError('Synthetic failure after accepted draft SQL')
    with monkeypatch.context() as patch:
        patch.setattr(t['access'],'_audit',fail)
        with pytest.raises(WorkspaceConflict): t['support'].apply(t['ws'],p['id'],{'authorized':True,'notice':APPLY_NOTICE},t['actors'][1])
    assert t['access'].draft(t['ws'],t['draft']['id'],t['actors'][1])['revision']==1
    assert t['support'].proposal(t['ws'],p['id'],t['actors'][1])['applied_revision'] is None


def test_readiness_declarations_and_isolated_checks_cannot_become_operating_proof(tools):
    t=tools; readiness=t['readiness']; ws=t['ws']; actor=t['actors'][1]
    assert readiness.status(ws,actor)['status']=='not_ready'
    for category in CATEGORIES:
        result=readiness.record(ws,{'category':category,'reference':'synthetic_record',
            'sha256':'a'*64,'expires':time.time()+60,'authorized':True,'notice':READY_NOTICE},actor)
        assert result['verification']=='declared_unverified'
    report=readiness.status(ws,actor)
    assert not report['required_current_evidence_complete'] and not report['commercial_enabled']
    now=time.time()
    sources={category:lambda ws,actor,c=category:CurrentEvidence(ws,c,'synthetic_fixture','b'*64,now,now+60,'isolated') for category in CATEGORIES}
    assert AdvancementReadiness(t['access'],evidence_sources=sources).status(ws,actor)['status']=='not_ready'


def test_only_current_scoped_trusted_evidence_completes_checklist_never_activation(tools):
    t=tools; now=time.time()
    sources={category:lambda ws,actor,c=category:CurrentEvidence(ws,c,'synthetic_adapter','b'*64,now,now+60,'operating','c'*64) for category in CATEGORIES}
    report=AdvancementReadiness(t['access'],evidence_sources=sources).status(t['ws'],t['actors'][1])
    assert report['required_current_evidence_complete'] and not report['commercial_enabled'] and not report['automatic_gate_promotion']
    sources['contract']=lambda ws,actor:CurrentEvidence('ws_'+'f'*32,'contract','synthetic_adapter','b'*64,now,now+60,'operating')
    assert AdvancementReadiness(t['access'],evidence_sources=sources).status(t['ws'],t['actors'][1])['status']=='not_ready'


def test_readiness_source_error_and_authority_change_never_leak_a_verified_report(tools):
    t=tools
    def changed(ws,actor):
        with t['store']._db as db:
            db.execute('UPDATE workspace_memberships SET active=0 WHERE workspace_id=? AND user_id=1',(ws,))
        raise RuntimeError('private synthetic contract text')
    checker=AdvancementReadiness(t['access'],evidence_sources={'contract':changed})
    with pytest.raises(WorkspaceDenied): checker.status(t['ws'],t['actors'][1])


def test_two_native_connections_cannot_post_two_events_for_the_same_logical_revision(tools):
    t=tools; op=approve(t); path=t['store']._db.execute('PRAGMA database_list').fetchone()[2]
    gate=Barrier(2)
    def worker(number):
        db=sqlite3.connect(path,timeout=2,check_same_thread=False);db.row_factory=sqlite3.Row
        try:
            access=WorkspaceAccess(SimpleNamespace(_db=db,_lock=RLock()),b'synthetic-workspace-key-32-bytes!!')
            ledger=ShadowLedger(access);gate.wait(timeout=5)
            try:return ledger.post(t['ws'],event(op,number),t['actors'][1])['status']
            except WorkspaceConflict:return 'conflict'
        finally:db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,(1,2)))
    assert sorted(results)==['completed','conflict']
    assert t['ledger'].summary(t['ws'],t['actors'][1])['entries']==2


def test_commit_accepted_then_response_lost_is_reconciled_by_fresh_read_without_double_post(tools):
    t=tools;op=approve(t);command=event(op);original=t['store']._db
    class AcceptedCommit:
        def __init__(self):self.armed=True
        def __getattr__(self,name):return getattr(original,name)
        def commit(self):
            original.commit()
            if self.armed:
                self.armed=False
                raise sqlite3.OperationalError('Synthetic commit acknowledgement lost')
    path=original.execute('PRAGMA database_list').fetchone()[2]
    t['store']._db=AcceptedCommit()
    try:
        with pytest.raises(WorkspaceConflict):t['ledger'].post(t['ws'],command,t['actors'][1])
    finally:t['store']._db=original
    fresh=sqlite3.connect(path);fresh.row_factory=sqlite3.Row
    try:
        access=WorkspaceAccess(SimpleNamespace(_db=fresh,_lock=RLock()),b'synthetic-workspace-key-32-bytes!!')
        ledger=ShadowLedger(access)
        assert ledger.summary(t['ws'],t['actors'][1])['entries']==2
        assert ledger.post(t['ws'],command,t['actors'][1])['replayed']
        assert ledger.summary(t['ws'],t['actors'][1])['entries']==2
    finally:fresh.close()
