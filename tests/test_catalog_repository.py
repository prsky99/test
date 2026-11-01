"""Catalog domain failures stay fixed and do not initialize application state."""
import sqlite3
import pytest
from agent_market.catalog_repository import COLUMNS, CatalogError, CatalogFilter, CatalogRepository
from agent_market.storage_adapter import SQLiteAdapter


@pytest.fixture
def catalog():
    db=sqlite3.connect(':memory:')
    numbers={'id':'INTEGER PRIMARY KEY','active':'INTEGER','auth_declared':'INTEGER','auth_observed':'INTEGER',
             'first_seen':'REAL','last_seen':'REAL','last_check_at':'REAL','last_ok_at':'REAL','eval_at':'REAL','eval_score':'REAL'}
    db.execute('CREATE TABLE resources ('+','.join(name+' '+numbers.get(name,'TEXT') for name in COLUMNS)+')')
    data=dict.fromkeys(COLUMNS)
    data.update(id=1,key='synthetic:key',source='synthetic',kind='a2a',url='https://provider.invalid/rpc',name='Synthetic agent',
                description='Synthetic source',category='news',active=1,first_seen=1.,last_seen=2.,health_status='unknown',details='{}')
    db.execute('INSERT INTO resources VALUES ('+','.join('?' for _ in COLUMNS)+')',tuple(data.values()));db.commit()
    try:yield CatalogRepository(SQLiteAdapter(db)),db
    finally:db.close()


def assert_code(code,action):
    with pytest.raises(CatalogError) as caught:action()
    assert caught.value.code==code and str(caught.value)==code


@pytest.mark.parametrize('field,value',[
    ('kind','unsupported'),('active',2),('active',None),('health_status','probably'),
    ('first_seen',-1),('last_seen',None),('last_ok_at',-1),('eval_score',101),('eval_score',-1),
    ('auth_observed',2),('auth_declared',-1),('key',None),('name',None),
    ('key','x'*513),('source','x'*257),('url','x'*4097),('name','x'*1025),('description','x'*8193),
    ('category','x'*257),('auth_info','x'*16385),('details','x'*16385),('usage_tools','x'*16385),
    ('usage_full_tools','x'*16385),('usage_guide','x'*16385),('content_hash','x'*257),
    ('usage_full_hash','x'*257),('usage_tools_hash','x'*257),('eval_grade','x'*65),('eval_security','x'*65),
    ('key','synthetic\0private'),('details','synthetic\0private'),('url','synthetic\0private'),
])
def test_malformed_private_record_is_explicit_and_not_partially_projected(catalog,field,value):
    repository,db=catalog
    db.execute('UPDATE resources SET '+field+'=? WHERE id=1',(value,));db.commit()
    before=db.total_changes
    assert_code('invalid_record',lambda:repository.get(1))
    assert db.total_changes==before


@pytest.mark.parametrize('value',[True,False,0,-1,2**63,'1',1.,None,[],{}])
def test_identity_types_are_exact_and_errors_never_echo_input(catalog,value):
    repository,_=catalog
    assert_code('invalid_request',lambda:repository.get(value))
    assert_code('invalid_request',lambda:repository.batch((value,)))


@pytest.mark.parametrize('value',[True,-1,float('nan'),float('inf'),2**53,2**10000,'synthetic-private-time'])
def test_timestamp_filter_rejects_nonfinite_huge_and_ambiguous_values(value):
    assert_code('invalid_request',lambda:CatalogFilter(min_last_seen=value))


@pytest.mark.parametrize('value',[True,0,-1,51,1.,'1',None])
def test_page_bounds_are_explicit(catalog,value):
    repository,_=catalog
    assert_code('invalid_request',lambda:repository.list(limit=value))


@pytest.mark.parametrize('kwargs',[{'kind':'MCP'},{'kind':[]},{'active':1},{'active':'false'},
    {'health_status':'Healthy'},{'category':'x'*257},{'source':'\ud800'}])
def test_filter_validation_stays_bounded(kwargs):
    assert_code('invalid_request',lambda:CatalogFilter(**kwargs))


def test_nullable_unknown_json_and_evidence_are_not_coerced_or_certified(catalog):
    repository,db=catalog
    db.execute("UPDATE resources SET health_status=NULL,auth_declared=NULL,auth_observed=0,usage_full_tools='',usage_tools='[]',details='not-json',content_hash='legacy-text'");db.commit()
    row=repository.get(1).as_private_dict()
    assert row['health_status'] is None and row['auth_declared'] is None and row['auth_observed']==0
    assert row['usage_full_tools']=='' and row['usage_tools']=='[]' and row['details']=='not-json'
    assert repository.count(CatalogFilter(health_status='unknown'))==0
    assert repository.count()==1
    assert_code('stale_resource',lambda:repository.get(1,expected_hash='a'*64))
    assert 'verified_callable' not in row and 'connection_available' not in row


def test_repository_constructor_never_accepts_paths_dsn_store_or_raw_connection(catalog):
    _,db=catalog
    for value in (db,':memory:','postgresql://synthetic:private@invalid/db',None,object()):
        assert_code('invalid_request',lambda:CatalogRepository(value))
