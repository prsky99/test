"""Owner clocks, typed observations and explicit private schema over SQLite."""
import json
import sqlite3

import pytest

from agent_market.catalog_observations import (
    OBSERVATION_SCHEMA, CatalogObservations, ObservationError,
    HealthObservation, SurveyObservation, EvaluationObservation,
)
from agent_market.catalog_index_fixtures import seed
from agent_market.catalog_index import MODEL_HASH
from agent_market.catalog_writer import CatalogWriter
from agent_market.catalog_writer_fixtures import command, operation
from agent_market.storage_adapter import SQLiteAdapter


def op(number):return 'ob_'+format(number,'032x')


@pytest.fixture
def system():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    adapter=SQLiteAdapter(db);seed(adapter)
    with adapter.transaction()as session:
        for stmt in OBSERVATION_SCHEMA:session.execute(stmt)
    written=CatalogWriter(adapter,model_hash=MODEL_HASH).upsert(command(),operation_id=operation(1),expected_revision=0,observed_at=0)
    try:yield db,adapter,CatalogObservations(adapter),written.resource_id
    finally:db.close()


def test_health_failure_streak_reset_and_owned_rolling_history(system):
    db,_adapter,observations,rid=system
    for number,outcome in enumerate(('healthy','fail','fail','fail','reachable'),1):
        result=observations.record(rid,HealthObservation(outcome,next_check_at=number+1),operation_id=op(number),expected_revision=number,observed_at=number)
        row=dict(db.execute('SELECT * FROM resources').fetchone())
        assert result.status=='committed' and result.revision==number+1
        assert row['health_status']==('healthy','failing','failing','down','reachable')[number-1]
        assert row['last_ok_at']==(1 if number<5 else 5)
        assert row['health_n_24h']==number and row['health_ok_24h']==(1 if number<5 else 2)
        assert row['failing_since']==(2 if 1<number<5 else None)
    result=observations.record(rid,HealthObservation('fail'),operation_id=op(6),expected_revision=6,observed_at=90000)
    row=db.execute('SELECT health_n_24h,health_ok_24h,last_ok_at,consecutive_failures FROM resources').fetchone()
    assert tuple(row)==(1,0,5,1) and result.revision==7


def test_repeated_op_and_durable_conflict_receipts_do_not_advance_clock(system):
    db,_adapter,observations,rid=system
    first=observations.record(rid,HealthObservation('healthy'),operation_id=op(1),expected_revision=1,observed_at=1)
    replay=observations.record(rid,HealthObservation('healthy'),operation_id=op(1),expected_revision=1,observed_at=1)
    assert replay.replayed and replay.revision==first.revision
    conflict=observations.record(rid,EvaluationObservation(90,'A','ok'),operation_id=op(2),expected_revision=1,observed_at=2)
    assert conflict.status=='conflict' and conflict.revision==2
    assert observations.current(rid,'evaluation')is None
    assert observations.reconcile(op(2))==conflict and observations.reconcile(op(99))is None
    with pytest.raises(ObservationError,match='operation_conflict'):
        observations.record(rid,HealthObservation('fail'),operation_id=op(1),expected_revision=1,observed_at=1)
    assert db.execute('SELECT COUNT(*) FROM catalog_observation_operations').fetchone()[0]==2


@pytest.mark.parametrize('factory',[
    lambda:HealthObservation('down'),lambda:HealthObservation(True),lambda:HealthObservation('fail',True),
    lambda:HealthObservation('healthy',float('nan')),
    lambda:EvaluationObservation(True,'A','ok'),lambda:EvaluationObservation(-1,'A','ok'),
    lambda:EvaluationObservation(101,'A','ok'),lambda:EvaluationObservation(float('inf'),'A','ok'),
    lambda:EvaluationObservation(90,'S','ok'),lambda:EvaluationObservation(90,'A','passed'),
    lambda:SurveyObservation(tools_json='{}'),lambda:SurveyObservation(guide_json='[]'),
    lambda:SurveyObservation(tools_json='[{"name":"a"},{"name":"a"}]'),
    lambda:SurveyObservation(tools_json='[{"name":"a","name":"b"}]'),
    lambda:SurveyObservation(guide_json='{"token":"a","token":"b"}'),
    lambda:SurveyObservation(guide_json='{"number":NaN}'),
    lambda:SurveyObservation(error_code='private error from provider'),
    lambda:SurveyObservation(tools_json='[{"name":"a"}]',error_code='survey_failed'),
    lambda:SurveyObservation(tools_json='[{"name":"a"}]',full_tools_json='[]'),
    lambda:SurveyObservation(full_tools_json='[{"name":"a","inputSchema":{}}]'),
    lambda:SurveyObservation(tools_json='[{"name":"a"}]',full_tools_json='[{"name":"a","inputSchema":{},"private_unknown":1}]'),
    lambda:SurveyObservation(guide_json='{"private":"'+'x'*12288+'"}'),
    lambda:SurveyObservation(guide_json='{"x":"\\ud800"}'),
])
def test_invalid_commands_are_fixed_errors_without_database_io(factory):
    with pytest.raises(ObservationError)as caught:factory()
    assert str(caught.value)=='invalid_command'


@pytest.mark.parametrize('kwargs',[
    {'observed_at':True},{'observed_at':float('inf')},{'observed_at':-1},
    {'expected_revision':0},{'expected_revision':True},{'expected_revision':2**63-1},
    {'operation_id':'co_'+'0'*32},{'operation_id':'ob_'+'A'*32},
])
def test_record_envelope_refuses_before_io(system,kwargs):
    db,_adapter,observations,rid=system
    args={'operation_id':op(1),'expected_revision':1,'observed_at':1};args.update(kwargs)
    calls=[];db.set_trace_callback(calls.append)
    with pytest.raises(ObservationError):observations.record(rid,HealthObservation('healthy'),**args)
    assert calls==[]


def test_survey_empty_success_is_explicit_and_failed_attempt_does_not_erase_payload(system):
    db,_adapter,observations,rid=system
    tools='[{"name":"news","description":"Public"}]'
    full='[{"name":"news","inputSchema":{"type":"object","properties":{"query":{"type":"string"}}}}]'
    observations.record(rid,SurveyObservation(tools_json=tools,full_tools_json=full),operation_id=op(1),expected_revision=1,observed_at=1)
    assert json.loads(db.execute('SELECT usage_full_tools FROM resources').fetchone()[0])[0]['inputSchema']['properties']['query']=={'type':'string'}
    observations.record(rid,SurveyObservation(error_code='survey_failed'),operation_id=op(2),expected_revision=2,observed_at=2)
    row=db.execute('SELECT usage_full_tools,cap_checked_at FROM resources').fetchone()
    assert row[0]is not None and row[1]is None and observations.current(rid,'survey').outcome=='failed'
    observations.record(rid,SurveyObservation(),operation_id=op(3),expected_revision=3,observed_at=3)
    assert tuple(db.execute('SELECT usage_tools,usage_full_tools,usage_full_hash,cap_checked_at FROM resources').fetchone())==('[]',None,None,3)


def test_owner_clock_cannot_be_reset_by_cleared_legacy_stamp(system):
    db,_adapter,observations,rid=system
    observations.record(rid,SurveyObservation(),operation_id=op(1),expected_revision=1,observed_at=100)
    observations.record(rid,SurveyObservation(error_code='survey_failed'),operation_id=op(2),expected_revision=2,observed_at=200)
    assert db.execute('SELECT cap_checked_at FROM resources').fetchone()[0]is None
    with pytest.raises(ObservationError,match='stale_observation'):
        observations.record(rid,SurveyObservation(),operation_id=op(3),expected_revision=3,observed_at=150)
    assert observations.current(rid,'survey').observed_at==200


def test_private_results_and_input_reprs_never_render_payload(system):
    _db,_adapter,observations,rid=system
    command=SurveyObservation(guide_json='{"token":"synthetic-private-token"}')
    result=observations.record(rid,command,operation_id=op(1),expected_revision=1,observed_at=1)
    assert repr(command)=='<SurveyObservation private>' and repr(result)=='<ObservationResult private>'
    assert repr(observations.current(rid,'survey'))=='<ObservationHead private>'


def test_evaluation_cannot_predate_retained_survey_stamp_without_new_owner_head(system):
    db,_adapter,observations,rid=system
    db.execute('UPDATE resources SET cap_checked_at=50');db.commit()
    with pytest.raises(ObservationError,match='stale_observation'):
        observations.record(rid,EvaluationObservation(90,'A','ok'),operation_id=op(1),expected_revision=1,observed_at=40)
    assert observations.current(rid,'evaluation')is None
