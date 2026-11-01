"""FTS-first Explore counts preserve filters and the explicit native adapter."""
import ast
import json
from pathlib import Path
import sqlite3

import pytest

from agent_market.application_store_postgres import (ApplicationStoreError,
    PostgresApplicationStore, _normalized)
from agent_market.concierge.front import LIVE_COND, VERIFIED_EXECUTION_COND
from scripts.build_application_store_postgres_catalog import build_catalog, source_constant


@pytest.fixture(scope='module')
def corpus():
    db=sqlite3.connect(':memory:')
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,active INTEGER,
        health_status TEXT,eval_security TEXT,category TEXT,auth_observed INTEGER,
        auth_declared INTEGER,first_seen REAL)''')
    db.execute('CREATE INDEX resources_active ON resources(active,health_status,kind,first_seen)')
    db.execute('CREATE VIRTUAL TABLE resources_fts USING fts5(name,description)')
    records=[];documents=[]
    for identity in range(1,20001):
        kind=('mcp','a2a','x402')[identity%3]
        record=(identity,kind,int(identity%11!=0),'down'if identity%13==0 else'healthy',
                'quarantine'if identity%17==0 else None,'science'if identity%2 else'dev_tools',
                1 if identity%5==0 else None,int(identity%7==0),float(identity))
        records.append(record)
        documents.append((identity,'needle'if identity%211==0 else'record',
                          'camera'if identity%127==0 else'ordinary public documentation'))
    db.executemany('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?)',records)
    db.executemany('INSERT INTO resources_fts(rowid,name,description)VALUES(?,?,?)',documents)
    db.commit();db.execute('PRAGMA query_only=ON')
    try:yield db,records,documents
    finally:db.close()


@pytest.fixture(scope='module')
def model():
    # Catalog construction parses an owned in-memory schema; no configured
    # bootstrap account, database path or native connection may be consulted.
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA
    original=store_module.init_admin_auth_db
    store_module.init_admin_auth_db=lambda db:db.executescript(ADMIN_SCHEMA)
    try:return build_catalog()
    finally:store_module.init_admin_auth_db=original


def query(kind=None,category=None,no_auth=False):
    clauses=[LIVE_COND];parameters=['"needle" OR "camera"']
    if category is not None:clauses.append('r.category=?');parameters.append(category)
    if no_auth:clauses.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')")
    if kind is not None:clauses.append('r.kind=?');parameters.append(kind)
    where=' AND '.join(clauses)
    sql='SELECT COUNT(*) AS c FROM resources_fts f CROSS JOIN resources r WHERE r.id=f.rowid AND resources_fts MATCH ? AND '+where
    return sql,tuple(parameters)


@pytest.mark.parametrize('kind',[None,'mcp','x402'])
@pytest.mark.parametrize('category',[None,'science'])
@pytest.mark.parametrize('no_auth',[False,True])
def test_fts_is_outer_loop_and_full_filter_counts_are_exact(corpus,kind,category,no_auth):
    db,records,documents=corpus;sql,parameters=query(kind,category,no_auth)
    matching={row[0]for row in documents if row[1]=='needle'or row[2]=='camera'}
    expected=sum(1 for row in records if row[0]in matching and row[2]==1 and row[3]=='healthy'
        and row[4]!='quarantine'and(kind is None or row[1]==kind)
        and(category is None or row[5]==category)
        and(not no_auth or(row[6]if row[6]is not None else row[7])==0 or row[1]=='x402'))
    before=db.total_changes
    assert db.execute(sql,parameters).fetchone()[0]==expected
    plan=[row[3]for row in db.execute('EXPLAIN QUERY PLAN '+sql,parameters)]
    assert plan[0].startswith('SCAN f VIRTUAL TABLE INDEX'),plan
    assert any('SEARCH r USING INTEGER PRIMARY KEY' in item for item in plan[1:]),plan
    assert db.total_changes==before


def test_cross_join_count_matches_previous_inner_join_semantics(corpus):
    db,_,_=corpus;sql,parameters=query(category='science',no_auth=True)
    previous=sql.replace('CROSS JOIN resources r WHERE r.id=f.rowid AND',
                         'JOIN resources r ON r.id=f.rowid WHERE')
    assert db.execute(sql,parameters).fetchone()==db.execute(previous,parameters).fetchone()


def test_filter_values_remain_bound_data_and_reads_cannot_mutate_catalog(corpus):
    db,_,_=corpus;sql,parameters=query(category="science' OR 1=1 --")
    before=db.total_changes
    assert db.execute(sql,parameters).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM resources').fetchone()[0]==20000
    assert db.total_changes==before
    with pytest.raises(sqlite3.OperationalError,match='readonly'):
        db.execute('DELETE FROM resources')


def test_normal_counts_register_cross_join_while_report_counts_keep_their_plan(model):
    normal=[entry for entry in model['statements']if entry['name']=='front.explore.fts.count']
    reports=[entry for entry in model['statements']if entry['name']=='front.explore.report.fts.count']
    assert len(normal)==len(reports)==16
    for entry in normal:
        assert 'FROM resources_fts f CROSS JOIN resources r WHERE r.id=f.rowid AND resources_fts MATCH ?'in entry['sqlite']
        assert entry['readonly']is True and entry['generated_id']is None
        assert entry['adapter']=='explore-fts5-count-v1'
        assert entry['parameter_count']==entry['sqlite'].count('?')==entry['postgres'].count('%s')
        assert 'FROM resources r JOIN matches m ON r.id=m.id WHERE'in entry['postgres']
    for entry in reports:
        assert 'FROM resources_fts f JOIN resources r ON r.id=f.rowid WHERE resources_fts MATCH ?'in entry['sqlite']
        assert entry['adapter']=='explore-fts5-count-v1'and entry['readonly']is True
    assert any(VERIFIED_EXECUTION_COND in entry['sqlite']for entry in normal)


def test_both_actual_nonreport_query_builders_match_only_registered_sql(model):
    tree=ast.parse(Path('agent_market/concierge/front.py').read_text())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef)and node.name=='get_front_explore')
    builders=[node for node in ast.walk(function)if isinstance(node,ast.JoinedStr)
        and any(isinstance(item,ast.Constant)and isinstance(item.value,str)
                and item.value.startswith('SELECT COUNT(*) AS c FROM resources_fts')for item in node.values)]
    assert len(builders)==2
    entries={_normalized(entry['sqlite']):entry for entry in model['statements']}
    for kind in(None,'mcp'):
        expected,parameters=query(kind,category='science',no_auth=True)
        where=expected.split('AND '+LIVE_COND,1)[1]
        predicate=LIVE_COND+where
        for builder in builders:
            sql=source_constant(builder,{'where':predicate,'where_all':predicate})
            entry=entries[_normalized(sql)]
            assert entry['adapter']=='explore-fts5-count-v1'and entry['parameter_count']==len(parameters)
        assert _normalized(expected+' OR 1=1')not in entries


def test_native_adapter_keeps_fts_projection_and_all_bound_filter_parameters(model):
    sql,parameters=query('mcp',"science' OR 1=1 --")
    entry=next(item for item in model['statements']if _normalized(item['sqlite'])==_normalized(sql))
    db=sqlite3.connect(':memory:');db.execute('CREATE VIRTUAL TABLE documents USING fts5(name,description)')
    db.executemany('INSERT INTO documents(rowid,name,description)VALUES(?,?,?)',[(7,'needle','public'),(8,'other','camera'),(9,'irrelevant','public')])
    db.commit();db.execute('PRAGMA query_only=ON');native=PostgresApplicationStore.__new__(PostgresApplicationStore)
    native._fts=lambda:db;observed=[];sentinel=object()
    def execute(statement,values):observed.append((statement,values));return sentinel
    native._execute=execute
    try:
        assert native._legacy_fts_select(entry,parameters)is sentinel
        statement,values=observed[0]
        assert statement==entry['postgres']and values[1:]==parameters[1:]
        assert {item[0]for item in json.loads(values[0])}=={7,8}
        assert parameters[1]not in statement
        with pytest.raises(ApplicationStoreError,match='invalid_parameters'):
            native._legacy_fts_select(entry,parameters+('unexpected',))
        assert len(observed)==1
    finally:db.close()
