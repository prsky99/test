"""Fixed recent-query indexes preserve results and install atomically in SQLite."""
import json
import sqlite3

import pytest

from agent_market.catalog_query_indexes import (
    INDEX_DEFINITIONS,LIVE_PREDICATE,IndexSetupError,
    inspect_front_query_indexes,ensure_front_query_indexes,
)
from scripts.ensure_front_query_indexes import main


@pytest.fixture
def catalog_db(tmp_path):
    path = tmp_path/'catalog.sqlite3'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,active INTEGER,health_status TEXT,eval_security TEXT,first_seen REAL,auth_observed INTEGER,category TEXT,auth_declared INTEGER,eval_score REAL)')
    db.execute('CREATE INDEX old_status ON resources(active,health_status,kind,first_seen)')
    db.execute('CREATE TABLE agent_test_reports(resource_id INTEGER,kind TEXT)')
    db.execute('CREATE INDEX report_subject ON agent_test_reports(resource_id,kind)')
    db.executemany('INSERT INTO resources(id,kind,active,health_status,eval_security,first_seen,auth_observed) VALUES (?,?,?,?,?,?,?)',[
        (1,'mcp',1,'healthy',None,None,0),(2,'mcp',1,'reachable','',0,1),
        (3,'mcp',1,'healthy','',7,0),(4,'x402',1,'healthy','',7,0),
        (5,'a2a',1,'healthy','',7,0),(6,'mcp',1,'reachable','',10,0),
        (7,'mcp',0,'healthy','',100,0),(8,'mcp',1,'failing','',100,0),
        (9,'mcp',1,'healthy','quarantine',100,0),(10,'mcp',1,'healthy','',-1,0),
    ])
    db.executemany('INSERT INTO agent_test_reports VALUES (?,?)',[(1,'mcp'),(3,'mcp'),(4,'x402')])
    db.commit()
    yield db,path
    db.close()


def test_partial_indexes_remove_recent_query_sort_without_changing_visibility_or_null_order(catalog_db):
    db,_ = catalog_db
    queries = [
        ('SELECT id,auth_observed FROM resources WHERE '+LIVE_PREDICATE+' ORDER BY COALESCE(first_seen,0) DESC,id DESC LIMIT ?', (50,)),
        ('SELECT id,auth_observed FROM resources WHERE '+LIVE_PREDICATE+' AND kind=? ORDER BY COALESCE(first_seen,0) DESC,id DESC LIMIT ?',('mcp',50)),
    ]
    original = [db.execute(sql,params).fetchall() for sql,params in queries]
    changes = db.total_changes
    assert ensure_front_query_indexes(db) == {'created':4,'existing':0}
    assert db.total_changes == changes
    for (sql,params),before in zip(queries,original):
        assert db.execute(sql,params).fetchall() == before
        plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,params)]
        assert not any('TEMP B-TREE' in step for step in plan),plan
        assert any('resources_live_recent' in step for step in plan),plan
    assert [row[0] for row in original[1]] == [6,3,2,1,10]
    assert (2,1) in original[1]
    assert ensure_front_query_indexes(db) == {'created':0,'existing':4}


def test_global_report_recent_index_avoids_sort_and_keeps_exact_protocol_binding(catalog_db):
    db,_ = catalog_db
    query = ('SELECT r.id FROM resources r WHERE '+LIVE_PREDICATE+
        ' AND EXISTS(SELECT 1 FROM agent_test_reports tr WHERE tr.resource_id=r.id AND tr.kind=r.kind)'
        ' ORDER BY COALESCE(r.first_seen,0) DESC,r.id DESC LIMIT ? OFFSET ?')
    before = db.execute(query,(2,0)).fetchall()
    ensure_front_query_indexes(db)
    assert db.execute(query,(2,0)).fetchall() == before == [(4,),(3,)]
    assert db.execute(query,(2,2)).fetchall() == [(1,)]
    plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '+query,(2,0))]
    assert not any('TEMP B-TREE' in step for step in plan),plan
    assert any('resources_live_recent' in step for step in plan),plan


def test_live_counts_use_covering_index_with_protocol_category_and_auth_filters(catalog_db):
    db,_ = catalog_db
    db.execute("UPDATE resources SET category='dev_tools'")
    queries = [
        ('SELECT COUNT(*) FROM resources r WHERE '+LIVE_PREDICATE, (), 7),
        ('SELECT COUNT(*) FROM resources r WHERE '+LIVE_PREDICATE+' AND r.kind=?', ('mcp',), 5),
        ('SELECT COUNT(*) FROM resources r WHERE '+LIVE_PREDICATE+
         " AND r.category=? AND (COALESCE(r.auth_observed,r.auth_declared,0)=0 OR r.kind='x402')",
         ('dev_tools',), 6),
    ]
    before = [db.execute(sql,params).fetchone()[0] for sql,params,_ in queries]
    changes = db.total_changes
    ensure_front_query_indexes(db)
    assert db.total_changes == changes
    for (sql,params,expected),original in zip(queries,before):
        assert db.execute(sql,params).fetchone()[0] == original == expected
        plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,params)]
        assert any('COVERING INDEX resources_front_count' in step for step in plan),plan
        assert not any('SCAN r' in step or 'TEMP B-TREE' in step for step in plan),plan


def test_conflicting_name_is_refused_before_any_index_is_created(catalog_db):
    db,_ = catalog_db
    db.execute('CREATE INDEX resources_live_recent ON resources(id)')
    with pytest.raises(IndexSetupError,match='index_name_conflict'):
        ensure_front_query_indexes(db)
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='resources_live_recent_kind'").fetchone()
    assert db.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 10


def test_shared_evaluation_count_is_covering_without_changing_its_population(catalog_db):
    db,_ = catalog_db
    db.execute('UPDATE resources SET eval_score=id*10')
    sql = ('SELECT COUNT(*) AS n,SUM(eval_score < ?) AS lower FROM resources '
           'WHERE active=1 AND kind=? AND eval_score IS NOT NULL')
    original = db.execute(sql,(80,'mcp')).fetchone()
    changes = db.total_changes
    ensure_front_query_indexes(db)
    assert db.total_changes == changes
    assert db.execute(sql,(80,'mcp')).fetchone() == original == (7,4)
    plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,(80,'mcp'))]
    assert any('COVERING INDEX resources_evaluation_count' in step for step in plan),plan


def test_second_index_failure_rolls_back_first_index(catalog_db):
    db,_ = catalog_db
    def deny_second(action,name,*_):
        return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_CREATE_INDEX and name==INDEX_DEFINITIONS[1][0] else sqlite3.SQLITE_OK
    db.set_authorizer(deny_second)
    with pytest.raises(sqlite3.DatabaseError):ensure_front_query_indexes(db)
    db.set_authorizer(None)
    assert inspect_front_query_indexes(db)['missing'] == [name for name,_ in INDEX_DEFINITIONS]
    assert not db.in_transaction


def test_helper_never_commits_an_existing_callers_transaction(catalog_db):
    db,_ = catalog_db
    db.execute("INSERT INTO resources(id,kind,active,health_status,eval_security,first_seen,auth_observed) VALUES (99,'mcp',1,'healthy','',20,0)")
    ensure_front_query_indexes(db)
    assert db.in_transaction
    db.rollback()
    assert not db.execute('SELECT 1 FROM resources WHERE id=99').fetchone()
    assert len(inspect_front_query_indexes(db)['missing']) == 4


def test_existing_equivalent_whitespace_is_allowed_but_literal_changes_are_not(catalog_db):
    db,_ = catalog_db
    for _,sql in INDEX_DEFINITIONS:db.execute(sql.replace('CREATE INDEX','create  index'))
    assert ensure_front_query_indexes(db) == {'created':0,'existing':4}
    db.execute('DROP INDEX resources_live_recent')
    db.execute(INDEX_DEFINITIONS[1][1].replace("'quarantine'","'Quarantine'"))
    with pytest.raises(IndexSetupError,match='index_name_conflict'):inspect_front_query_indexes(db)


def test_cli_is_read_only_by_default_and_apply_is_idempotent(catalog_db,capsys,monkeypatch):
    db,path = catalog_db
    import scripts.ensure_front_query_indexes as script
    original_connect = sqlite3.connect
    observed = []
    def connect(database,**kwargs):
        observed.append(database)
        return original_connect(database,**kwargs)
    monkeypatch.setattr(script.sqlite3,'connect',connect)
    assert main(['--db',str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {'ok':True,'applied':False,'row_changes':0,'created':0,'existing':0,'missing':4}
    assert observed[-1].endswith('?mode=ro')
    assert len(inspect_front_query_indexes(db)['missing']) == 4
    assert main(['--db',str(path),'--apply']) == 0
    assert json.loads(capsys.readouterr().out)['created'] == 4
    assert observed[-1].endswith('?mode=rw')
    assert main(['--db',str(path),'--apply']) == 0
    assert json.loads(capsys.readouterr().out)['created'] == 0
    assert db.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 10


def test_cli_refuses_missing_symlink_and_conflicting_objects_without_private_output(catalog_db,tmp_path,capsys):
    db,path = catalog_db
    missing = tmp_path/'private-absent.sqlite3'
    assert main(['--db',str(missing),'--apply']) == 1 and not missing.exists()
    assert str(missing) not in capsys.readouterr().out
    link = tmp_path/'catalog-link.sqlite3';link.symlink_to(path)
    assert main(['--db',str(link),'--apply']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'regular_owned_database_required'
    db.execute('CREATE TABLE resources_live_recent_kind(private_value TEXT)');db.commit()
    assert main(['--db',str(path),'--apply']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['error'] == 'index_name_conflict' and result['row_changes'] == 0
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='resources_live_recent'").fetchone()


def test_only_sqlite_handles_are_accepted_and_store_initialization_installs_indexes(tmp_path):
    with pytest.raises(IndexSetupError,match='sqlite_required'):ensure_front_query_indexes(object())
    from agent_market.gateway.store import Store
    store = Store(str(tmp_path/'initialized.sqlite3'))
    try:assert inspect_front_query_indexes(store._db)['missing'] == []
    finally:store._db.close()
