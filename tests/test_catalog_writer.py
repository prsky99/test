"""Strict registry normalization, portable receipts and conservative ownership."""
from dataclasses import replace
import json
import sqlite3
import pytest
from agent_market.catalog_writer import CatalogWriter, RegistryUpsert, WriterError, PROFILE
from agent_market.catalog_writer_fixtures import seed, command, operation, MODEL_HASH, seed_history, history_state
from agent_market.catalog_repository import CatalogRepository
from agent_market.storage_adapter import SQLiteAdapter


@pytest.fixture
def database():
    db=sqlite3.connect(':memory:');adapter=SQLiteAdapter(db);seed(adapter)
    try:yield db,adapter,CatalogWriter(adapter,model_hash=MODEL_HASH)
    finally:db.close()


def write(writer,number=1,revision=0,at=0.,**changes):
    return writer.upsert(command(**changes),operation_id=operation(number),expected_revision=revision,observed_at=at)


def fixed(code,action):
    with pytest.raises(WriterError) as caught:action()
    assert str(caught.value)==caught.value.code==code


@pytest.mark.parametrize('changes',[
    {'key':''},{'source':' '},{'kind':'MCP'},{'url':'file:///private/secret'},{'url':'https://host.invalid:invalid/path'},
    {'url':'https://host.invalid/\nprivate'},{'name':'x'*201},{'description':'x'*2001},
    {'name':'\ud800'},{'description':'\0private'},{'networks':['base']},{'networks':('base,evil',)},
    {'networks':tuple(str(i) for i in range(33))},{'price_usdc':True},{'price_usdc':-1},{'price_usdc':2**63},
    {'calls_30d':1.0},{'payers_30d':'1'},{'last_called':float('nan')},{'last_called':2**10000},
    {'auth_declared':True},{'auth_declared':2},{'regions':'x'*1025},{'details_json':'[]'},
    {'details_json':'{"token":NaN}'},{'details_json':'{"a":Infinity}'},{'details_json':'{"a":-Infinity}'},
    {'details_json':'{"a":1,"a":2}'},{'details_json':'{"a":{"b":1,"b":2}}'},
    {'details_json':'{"a":9223372036854775808}'},{'details_json':'{"a":1e999}'},
    {'details_json':'{"a":'+('['*14)+'0'+(']'*14)+'}'},
    {'details_json':'{"a":['+','.join('0' for _ in range(1024))+']}'},
    {'details_json':'{"a":"'+('x'*12288)+'"}'},
])
def test_strict_command_refusal_never_truncates_or_coerces(changes):
    fixed('invalid_command',lambda:command(**changes))


@pytest.mark.parametrize('kwargs',[{'operation_id':'private-secret'}, {'operation_id':'co_'+'A'*32},
    {'expected_revision':True},{'expected_revision':-1},{'expected_revision':2**63-1},
    {'observed_at':float('inf')},{'observed_at':True},{'observed_at':-1}])
def test_metadata_refusal_precedes_mutation(database,kwargs):
    db,_adapter,writer=database;before=db.total_changes
    parameters={'operation_id':operation(1),'expected_revision':0,'observed_at':0.};parameters.update(kwargs)
    fixed('invalid_command',lambda:writer.upsert(command(),**parameters))
    assert db.total_changes==before and db.execute('SELECT COUNT(*) FROM resources').fetchone()[0]==0


def test_new_equal_changed_and_counter_only_have_stable_identity_and_revision(database):
    db,adapter,writer=database
    first=write(writer);seed_history(adapter,first.resource_id);history=history_state(adapter)
    db.execute('UPDATE resources SET health_status=?,last_check_at=?,last_ok_at=?,auth_observed=?,usage_full_tools=?,cap_checked_at=?,eval_at=?,eval_grade=? WHERE id=?',
               ('healthy',12.,11.,1,'[]',12.,12.,'A',first.resource_id));db.commit()
    same=write(writer,2,1,1.)
    assert (first.status,first.change,first.revision)==('committed','new',1)
    assert (same.resource_id,same.change,same.revision)==(first.resource_id,'unchanged',2)
    assert db.execute('SELECT first_seen,last_seen,health_status,cap_checked_at,eval_at FROM resources').fetchone()==(0.,1.,'healthy',12.,12.)
    assert db.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0]==0 and history_state(adapter)==history
    changed=write(writer,3,2,2.,calls_30d=0)
    assert (changed.resource_id,changed.change,changed.revision)==(first.resource_id,'changed',3)
    row=CatalogRepository(adapter).get(first.resource_id).as_private_dict()
    assert row['health_status']=='healthy' and row['auth_observed']==1 and row['usage_full_tools']=='[]'
    assert row['last_check_at']==12. and row['last_ok_at']==11. and row['eval_grade']=='A' and row['eval_at'] is None
    assert db.execute('SELECT cap_checked_at FROM resources').fetchone()[0] is None
    assert history_state(adapter)==history
    assert db.execute('SELECT COUNT(*) FROM catalog_write_operations').fetchone()[0]==3
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0]==3


def test_normalization_is_versioned_not_legacy_implicit_json_or_network_order(database):
    db,_adapter,writer=database
    one=write(writer,networks=('z','base','base'),pay_to='Synthetic-PAYEE',details_json='{"b":2,"a":1}')
    before=db.execute('SELECT content_hash,networks,pay_to,details FROM resources').fetchone()
    two=write(writer,2,1,1.,networks=('base','z'),pay_to='synthetic-payee',details_json='{ "a": 1, "b": 2 }')
    after=db.execute('SELECT content_hash,networks,pay_to,details FROM resources').fetchone()
    assert one.resource_id==two.resource_id and two.change=='unchanged' and before==after
    assert after[1:]==(',base,z,','synthetic-payee','{"a":1,"b":2}')
    assert db.execute('SELECT hash_profile FROM catalog_resource_revisions').fetchone()[0]==PROFILE


def test_no_two_keys_are_merged_by_shared_url_and_stale_observations_are_refused(database):
    db,_adapter,writer=database
    one=write(writer,at=10.);two=write(writer,2,0,10.,key='synthetic:distinct')
    assert one.resource_id!=two.resource_id
    fixed('stale_observation',lambda:write(writer,3,1,9.))
    assert db.execute('SELECT COUNT(*) FROM catalog_write_operations').fetchone()[0]==2
    assert db.execute('SELECT MAX(revision) FROM catalog_resource_revisions').fetchone()[0]==1


def test_committed_and_conflict_receipts_replay_without_reapplying_later_state(database):
    db,_adapter,writer=database
    first=write(writer,at=1.);conflict=write(writer,2,0,2.)
    second=write(writer,3,1,3.,name='Second')
    before=db.total_changes
    original=write(writer,1,0,1.);stale=write(writer,2,0,2.)
    assert original.replayed and original.revision==first.revision==1
    assert stale.replayed and stale.status==conflict.status=='conflict' and stale.revision==1
    assert db.total_changes==before and db.execute('SELECT name FROM resources').fetchone()[0]=='Second'
    assert writer.reconcile(operation(3)).revision==second.revision==2
    assert writer.reconcile(operation(999)) is None
    fixed('operation_conflict',lambda:write(writer,1,0,2.))


def test_disabled_default_profile_is_not_a_hidden_writer_toggle():
    db=sqlite3.connect(':memory:');adapter=SQLiteAdapter(db);seed(adapter,enabled=False)
    try:
        writer=CatalogWriter(adapter,model_hash=MODEL_HASH)
        fixed('write_disabled',lambda:write(writer))
        assert db.execute('SELECT COUNT(*) FROM resources').fetchone()[0]==0
    finally:db.close()


def test_bound_key_metadata_and_repr_never_become_sql_or_public_payload(database):
    db,adapter,writer=database
    private="synthetic'); DROP TABLE resources; --"
    result=write(writer,key=private,source=private,category=private,details_json=json.dumps({'token':'synthetic-private'}))
    assert CatalogRepository(adapter).get_by_key(private).id==result.resource_id
    assert db.execute('SELECT COUNT(*) FROM resources').fetchone()[0]==1
    for value in (command(key=private),result):
        assert 'DROP' not in repr(value) and 'synthetic-private' not in repr(value)


def test_constructor_does_not_accept_paths_raw_connections_or_synthesize_model(database):
    db,adapter,_writer=database
    for value in (db,':memory:',None):fixed('invalid_command',lambda:CatalogWriter(value,model_hash=MODEL_HASH))
    fixed('invalid_command',lambda:CatalogWriter(adapter,model_hash='private-model'))


@pytest.mark.parametrize('initial_health,changes,expected_health,cleared',[
    ('retired',{},'retired',False),
    ('retired',{'name':'Registry correction'},'unknown',True),
    ('healthy',{'kind':'a2a'},'unknown',True),
])
def test_changed_retired_and_kind_resets_are_explicit_while_equal_retired_is_retained(database,initial_health,changes,expected_health,cleared):
    db,_adapter,writer=database
    first=write(writer)
    db.execute('UPDATE resources SET active=0,health_status=?,consecutive_failures=7,failing_since=1,next_check_at=99,health_ok_24h=2,health_n_24h=9,last_check_at=8,last_ok_at=6 WHERE id=?',(initial_health,first.resource_id));db.commit()
    result=write(writer,2,1,10.,**changes)
    assert result.resource_id==first.resource_id and result.revision==2
    state=db.execute('SELECT active,health_status,consecutive_failures,failing_since,next_check_at,health_ok_24h,health_n_24h,last_check_at,last_ok_at FROM resources').fetchone()
    assert state[:2]==(1,expected_health) and state[-2:]==(8.,6.)
    assert state[2:7]==((0,None,None,0,0) if cleared else (7,1.,99.,2,9))
