"""Isolated retention preserves replay barriers and protected private work."""
import json

import pytest

from agent_market.application_control_retention import ControlRetention, DAYS
from agent_market.reliability_circuit import SCHEMA as CIRCUIT_SCHEMA
from agent_market.reliability_research import SCHEMA as RESEARCH_SCHEMA
from agent_market.workspace_access import WorkspaceConflict, _canonical
from tests.test_reliability_admission import pilot, body
from tests.test_reliability_controls import controls
from tests.test_workspace_execution_api import private_api


def test_expired_unselected_admission_is_compacted_but_never_becomes_a_new_logical_request(pilot):
    w=pilot; ws=w.ws['id']; command=body(w,selected=False)
    unselected=w.admission.prepare(ws,command,w.actor)
    selected=w.admission.prepare(ws,body(w,selected=True),w.actor)
    retention=ControlRetention(w.access)
    with w.store.tx() as db:
        db.execute('BEGIN IMMEDIATE')
        result=retention.run(db,ws,now=w.now+(DAYS+1)*86400)
    assert result['never_ticketed_admissions_compacted']==1
    assert w.store.query('SELECT 1 FROM reliability_admissions WHERE id=?',(selected['id'],))
    assert not w.store.query('SELECT 1 FROM reliability_admissions WHERE id=?',(unselected['id'],))
    with pytest.raises(WorkspaceConflict):
        w.admission.prepare(ws,command,w.actor)
    assert not w.calls


def _seed(w):
    retention=ControlRetention(w.access);ws=w.ws['id']
    with w.store.tx() as db:
        for sql in (*CIRCUIT_SCHEMA,*RESEARCH_SCHEMA):
            db.execute(sql)
    def claim(ref,outcome,*,signature=None):
        value={'workspace_id':ws,'resource_id':w.rids[0],'source_ref':ref,
               'outcome':outcome,'observed_at':w.now-100*86400,'kind':'observation'}
        signer=retention._signer('configured-read-circuit-v1')
        with w.store.tx() as db:
            db.execute('INSERT INTO reliability_circuit_claims VALUES(?,?,?,?,?)',
                (ws,ref,w.rids[0],_canonical(value),signature or signer.sign(value)))
    def manifest(identity):
        value={'id':identity,'workspace_id':ws,'corpus_id':'synthetic-corpus','created':w.now-100*86400,
               'expires':w.now-99*86400,'episodes':[{'query':'private retained body'}]}
        signer=retention._signer('bounded-reliability-research-v1')
        with w.store.tx() as db:
            db.execute('INSERT INTO reliability_research_manifests VALUES(?,?,?,?,?,?)',
                (identity,ws,value['corpus_id'],value['created'],_canonical(value),signer.sign(value)))
    return retention,claim,manifest


def test_terminal_controls_drop_bodies_while_unknown_and_tampered_evidence_remain(controls):
    w=controls;ws=w.ws['id'];retention,claim,manifest=_seed(w)
    claim('rej_'+'1'*32,'completed')
    claim('rej_'+'2'*32,'unknown')
    claim('rej_'+'3'*32,'failed',signature='0'*64)
    manifest('rrm_'+'4'*32)
    with w.store.tx() as db:
        db.execute('BEGIN IMMEDIATE')
        result=retention.run(db,ws,now=w.now)
    assert result['research_bodies_compacted']==result['circuit_claims_compacted']==1
    assert result['held_invalid_evidence']==1
    assert len(w.store.query('SELECT * FROM reliability_circuit_claims'))==2
    assert w.store.query('SELECT 1 FROM reliability_circuit_restore_blocks WHERE authority_id=?',
        ('source:'+ws+':rej_'+'1'*32,))
    archives=w.store.query('SELECT payload,signature FROM application_control_archives')
    assert len(archives)==2
    assert 'private retained body' not in json.dumps([tuple(row) for row in archives])
    for row in archives:
        assert retention.signer.verify(json.loads(row['payload']),row['signature'])


def test_unresolved_evaluation_preserves_research_and_retention_batch_is_bounded(controls):
    w=controls;ws=w.ws['id'];retention,claim,manifest=_seed(w)
    manifest('rrm_'+'5'*32)
    with w.store.tx() as db:
        db.execute('INSERT INTO reliability_eval_jobs VALUES(?,?,?,?,?,?,?,?,?)',
            ('rej_'+'f'*32,ws,'synthetic-unknown','unknown','synthetic-host',w.now-1,w.now+1,'{}','fixture'))
        result=retention.run(db,ws,now=w.now)
    assert result['research_bodies_compacted']==0
    assert w.store.query('SELECT 1 FROM reliability_research_manifests')
    claim('rej_'+'6'*32,'completed');claim('rej_'+'7'*32,'failed')
    with w.store.tx() as db:
        db.execute('BEGIN IMMEDIATE')
        result=retention.run(db,ws,limit=1,now=w.now)
    assert result['circuit_claims_compacted']==1
    assert len(w.store.query('SELECT * FROM reliability_circuit_claims'))==1


def test_control_retention_requires_the_callers_active_transaction(controls):
    w=controls;retention=ControlRetention(w.access)
    with pytest.raises(WorkspaceConflict):
        retention.run(w.store._db,w.ws['id'])


def test_tampering_an_unknown_jobs_state_locator_cannot_release_research_body_retention(controls):
    w=controls;ws=w.ws['id'];retention,_,manifest=_seed(w)
    manifest('rrm_'+'8'*32)
    value={'id':'rej_'+'9'*32,'workspace_id':ws,'state':'unknown'}
    signer=retention._signer('bounded-continuous-evaluation-v1')
    with w.store.tx() as db:
        db.execute('INSERT INTO reliability_eval_jobs VALUES(?,?,?,?,?,?,?,?,?)',
            (value['id'],ws,'synthetic-tampered-job','completed','synthetic-host',w.now-1,w.now+1,
             _canonical(value),signer.sign(value)))
        result=retention.run(db,ws,now=w.now)
    assert result['research_bodies_compacted']==0 and result['held_invalid_evidence']==1
    assert w.store.query('SELECT 1 FROM reliability_research_manifests')
