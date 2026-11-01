"""Readiness evidence must distinguish missing code from operating approval."""
import json
import sqlite3

import pytest

from agent_market import storage_inventory
from agent_market.storage_adapter import SQLiteAdapter
from agent_market.store_migration_readiness import audit_sources, capture_schema, main, owner, LIMITS


def sources(tmp_path,monkeypatch,text):
    root=tmp_path/'agent_market';root.mkdir();(root/'source.py').write_text(text)
    monkeypatch.setattr(storage_inventory,'_source_root',lambda:root)
    return root


def test_source_inventory_reuses_existing_scanner_and_never_executes_source(tmp_path,monkeypatch):
    sources(tmp_path,monkeypatch,"raise RuntimeError('must never run')\nSCHEMA=\"CREATE TABLE customer_sessions(id TEXT, private_value TEXT DEFAULT 'NEVER_REPORT_PRIVATE_LITERAL')\"\n")
    value=audit_sources();encoded=json.dumps(value)
    assert value['counts']['static_table_names']==1
    assert value['tables'][0]['owner']=='customer_identity_private_authorization'
    assert value['tables'][0]['application_postgres_repository']=='not_integrated'
    assert value['source_scan_complete'] and value['declaration_scan_complete']
    assert not value['schema_coverage_complete'] and not value['operating_ready'] and not value['application_postgres_enabled']
    assert 'NEVER_REPORT_PRIVATE_LITERAL' not in encoded and str(tmp_path) not in encoded and 'CREATE TABLE' not in encoded


def test_unresolved_dynamic_schema_and_partial_files_cannot_be_reported_as_zero(tmp_path,monkeypatch):
    root=sources(tmp_path,monkeypatch,"sql='CREATE TABLE '+name+'(id INTEGER)'\ndb.execute(sql)\n")
    value=audit_sources()
    assert not value['declaration_scan_complete'] and not value['schema_coverage_complete']
    assert 'dynamic_or_partial_table_declaration' in value['issues']
    (root/'broken.py').write_text('not valid python ???')
    value=audit_sources()
    assert not value['source_scan_complete'] and 'bounded_source_evidence_incomplete' in value['blockers']


def test_source_changes_between_scan_and_declaration_capture_refused(tmp_path,monkeypatch):
    root=sources(tmp_path,monkeypatch,"SCHEMA='CREATE TABLE resources(id INTEGER)'\n")
    original=storage_inventory.scan
    def changed():
        value=original();(root/'source.py').write_text("SCHEMA='CREATE TABLE admin_sessions(id TEXT)'\n");return value
    monkeypatch.setattr(storage_inventory,'scan',changed)
    value=audit_sources()
    assert not value['declaration_scan_complete'] and value['counts']['static_table_names']==0
    assert 'source_or_declaration_incomplete' in value['issues']


@pytest.mark.parametrize('name,expected',[('resources','catalog_observation_search_vector'),
    ('workspace_private_runs','workspace_private_data_execution_deployment'),('admin_sessions','staff_authentication_security'),
    ('provider_control_claims','provider_control_proofs'),('workflow_run_authority','workflow_authority_queue_delivery'),
    ('clearinghouse_ledger','accounting_commerce'),('unknown_table','unclassified_owner_required')])
def test_owner_mapping_has_no_silent_fallback_to_verified(name,expected):
    assert owner(name)==expected


def test_native_fixture_schema_capture_is_readonly_and_omits_defaults_data():
    db=sqlite3.connect(':memory:');db.execute("CREATE TABLE customer_sessions(id TEXT PRIMARY KEY, secret TEXT DEFAULT 'NEVER_COPY_DEFAULT')")
    db.execute("INSERT INTO customer_sessions VALUES('private-session','NEVER_COPY_ROW')");db.commit()
    adapter=SQLiteAdapter(db);before=db.total_changes
    result=capture_schema(adapter)
    assert result['complete'] and result['native_readonly'] and not result['repository_parity_verified']
    assert db.total_changes==before and db.execute('PRAGMA query_only').fetchone()[0]==0
    encoded=json.dumps(result)
    assert all(value not in encoded for value in ('NEVER_COPY_DEFAULT','NEVER_COPY_ROW','private-session'))
    assert [column['name'] for column in result['tables'][0]['columns']]==['id','secret']
    db.close()


@pytest.mark.parametrize('fault',['temporary','relaxed','identifier','column_limit'])
def test_native_capture_incomplete_never_returns_partial_schema(fault,monkeypatch):
    db=sqlite3.connect(':memory:')
    if fault=='temporary':db.execute('CREATE TEMP TABLE shadow(id INTEGER)')
    elif fault=='relaxed':db.execute('PRAGMA read_uncommitted=ON')
    elif fault=='identifier':db.execute('CREATE TABLE "private-secret@example.invalid"(id TEXT)')
    else:
        db.execute('CREATE TABLE many(a TEXT,b TEXT)');monkeypatch.setitem(LIMITS,'columns_per_table',1)
    db.commit();value=capture_schema(SQLiteAdapter(db))
    assert not value['complete'] and value['tables'] is None and not value['operating_ready']
    assert 'private-secret' not in json.dumps(value)
    db.close()


@pytest.mark.parametrize('args',[[],['--db','private.sqlite3'],['--scan','--scan'],['--root','/'],['--sc']])
def test_cli_has_no_operating_database_path_or_unbounded_source_inputs(args,capsys):
    assert main(args)==2
    value=json.loads(capsys.readouterr().out)
    assert value['error']=='invalid_arguments' and not value['operating_ready']


def test_cli_scan_success_does_not_mean_migration_ready(tmp_path,monkeypatch,capsys):
    sources(tmp_path,monkeypatch,"SCHEMA='CREATE TABLE workflow_runs(id TEXT)'\n")
    assert main(['--scan'])==0
    value=json.loads(capsys.readouterr().out)
    assert value['status']=='application_mapping_incomplete' and not value['operating_ready']
    assert 'live_application_repository_bindings_not_implemented' in value['blockers']
