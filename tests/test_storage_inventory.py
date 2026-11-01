"""Storage inventory is bounded source analysis, never a database or SQL executor."""
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest

from agent_market import storage_inventory as inventory


def categories(source):
    result = inventory.analyze_source(source)
    assert not result['issues']
    return Counter(row['category'] for row in result['findings'])


def source_tree(tmp_path, monkeypatch, files=None):
    root = tmp_path / 'agent_market'; root.mkdir()
    for name, content in (files or {'sample.py': 'db.execute("SELECT value FROM samples WHERE id=?", (1,))\n'}).items():
        path = root / name; path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    monkeypatch.setattr(inventory, '_source_root', lambda: root)
    return root


def test_actual_store_definitions_private_attributes_and_dbapi_calls_are_locations_only():
    result = inventory.analyze_source('''import sqlite3 as sql
class Store:
    def tx(self):
        with self._lock:
            with self._db:
                self._db.commit()
    def query(self, text):
        return self._db.execute(text).fetchall()
    def unrelated(self):
        def query(): return None
connection = sql.connect("not-a-real-database")
connection.row_factory = sql.Row
cur = connection.execute("INSERT INTO sample(value) VALUES (?)", (1,))
identity = cur.lastrowid
count = cur.rowcount
connection.rollback()
''')
    found = Counter(row['category'] for row in result['findings'])
    assert found['definition.store_tx'] == found['definition.store_query'] == 1
    for category in ('attribute.private_db', 'attribute.private_lock', 'call.commit', 'call.rollback',
                     'sqlite.connect', 'sqlite.row_mapping', 'sqlite.row_factory', 'sqlite.lastrowid', 'dbapi.rowcount'):
        assert found[category] >= 1
    assert all(set(row) == {'file', 'line', 'column', 'category'} and row['line'] > 0 and row['column'] > 0 for row in result['findings'])


def test_nested_transaction_and_commit_warnings_are_not_self_nesting_false_positives():
    found = categories('''with store.tx() as db:
    db.execute("SELECT value FROM data")
    with store.tx() as other:
        other.commit()
    def later():
        store.tx()
''')
    assert found['call.tx'] == 3
    assert found['context.transaction'] == 2
    assert found['transaction.nested_tx_with'] == found['transaction.tx_call_inside_tx_with'] == 1
    assert found['transaction.explicit_commit_in_tx_with'] == 1


def test_same_line_occurrences_have_distinct_columns_and_are_not_lost():
    result = inventory.analyze_source('store.query("SELECT 1"); store.query("SELECT 2")')
    calls = [row for row in result['findings'] if row['category'] == 'call.query']
    assert len(calls) == 2 and calls[0]['line'] == calls[1]['line'] and calls[0]['column'] != calls[1]['column']


def test_sql_dialect_features_are_bounded_lexical_indicators_without_sql_output():
    source = '''SCHEMA = """CREATE VIRTUAL TABLE things_fts USING fts5(value);
CREATE TABLE sample(id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT COLLATE NOCASE);
PRAGMA journal_mode=WAL;
SELECT rowid,json_extract(body,'$.CANARY'),strftime('%s','now') FROM sample WHERE sample MATCH ? AND item=:name;
INSERT OR REPLACE INTO sample(value) VALUES (?1);
INSERT OR IGNORE INTO sample(value) VALUES ($1);
INSERT INTO sample(value) VALUES (%s) ON CONFLICT(id) DO UPDATE SET value=excluded.value RETURNING id;
SELECT value FROM sample WHERE value GLOB ?;
BEGIN IMMEDIATE;
"""
db.executescript(SCHEMA)
'''
    result = inventory.analyze_source(source); found = {row['category'] for row in result['findings']}
    for category in ('pragma', 'fts', 'json', 'rowid', 'autoincrement', 'on_conflict', 'insert_or_replace',
                     'insert_or_ignore', 'sqlite_function', 'placeholder_qmark', 'placeholder_numbered',
                     'placeholder_named', 'placeholder_pyformat', 'schema_statement', 'collation', 'glob',
                     'returning', 'transaction_statement'):
        assert 'sql.' + category in found
    rendered = json.dumps(result)
    for private in ('CANARY', 'CREATE VIRTUAL', 'things_fts', 'SELECT rowid', 'excluded.value'):
        assert private not in rendered


def test_quoted_data_comments_and_non_sql_product_text_do_not_become_sql_features():
    source = '''description = "PRAGMA secret token=synthetic-private"
html = "<div>SELECT json_extract(secret)</div>"
db.execute("SELECT 'PRAGMA json_extract(?) rowid' AS value -- ON CONFLICT token=synthetic-private\\n")
'''
    found = categories(source)
    assert found['sql.call'] == 1
    assert not any(found[key] for key in ('sql.pragma', 'sql.json', 'sql.rowid', 'sql.on_conflict', 'sql.placeholder_qmark'))


def test_literal_bindings_are_followed_once_but_dynamic_aliases_and_branches_are_visible():
    source = '''SCHEMA = "CREATE TABLE sample(id INTEGER)"
db.executescript(SCHEMA)
db.executescript(SCHEMA)
def read(table, query):
    db.execute("SELECT value FROM " + table + " WHERE id=?", (1,))
    db.execute(query)
    if table:
        sql = "SELECT value FROM sample"
    db.execute(sql)
    proxy.execute(123, "search_docs", {})
'''
    found = categories(source)
    assert found['call.executescript'] == 2 and found['sql.schema_statement'] == 1
    assert found['sql.call_unresolved'] == 3 and found['sql.call_resolved_string'] == 2
    assert found['sql.call'] == 5


def test_sqlite_import_aliases_are_detected_without_importing_the_target_module():
    found = categories('''from sqlite3 import connect as connect_db
connection=connect_db("SENSITIVE_CONFIG_PATH")
''')
    assert found['sqlite.connect'] == 1


def test_function_parameter_shadowing_does_not_reuse_a_module_sql_binding():
    found = categories('''SQL="SELECT value FROM sample WHERE id=?"
def read(SQL):
    return db.execute(SQL)
''')
    assert found['sql.call_unresolved'] == 1 and found['sql.placeholder_qmark'] == 0


def test_repeated_sql_alias_expansion_has_a_fixed_analysis_budget(monkeypatch):
    source = "A0='SELECT ?'\n" + ''.join('A' + str(index) + '=A' + str(index - 1) + '+A' + str(index - 1) + '\n' for index in range(1, 41)) + 'db.execute(A40)\n'
    original = inventory.Analyzer.resolve; calls = 0
    def counted(instance, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 10000: raise AssertionError('The test stopped unbounded repeated alias expansion.')
        return original(instance, *args, **kwargs)
    monkeypatch.setattr(inventory.Analyzer, 'resolve', counted)
    result = inventory.analyze_source(source)
    assert 'resolution_limit' in result['issues'] or 'string_work_limit' in result['issues']
    assert calls <= 10000


@pytest.mark.parametrize('text', ['/*' * 20000, '/*' + 'x' * 100000, "'" + 'x' * 100000,
                                 '"' + '""' * 20000, '--comment\n' * 10000 + 'SELECT ?'])
def test_quote_and_comment_mask_consumes_unterminated_or_repeated_prefixes_linearly(text):
    class Counted(str):
        inspected = 0
        def find(self, needle, start=0, end=None):
            result = super().find(needle, start) if end is None else super().find(needle, start, end)
            self.inspected += len(self) - start if result < 0 else result - start + len(needle)
            return result
        def startswith(self, prefix, start=0, end=None):
            self.inspected += len(prefix)
            return super().startswith(prefix, start) if end is None else super().startswith(prefix, start, end)
    value = Counted(text)
    result = inventory.mask_sql(value)
    assert len(result) <= len(value) and value.inspected <= len(value) * 12
    assert 'comment' not in result and 'x' not in result


def test_analysis_string_budget_accounts_for_resolution_and_mask_work(monkeypatch):
    monkeypatch.setitem(inventory.LIMITS, 'analysis_string_bytes', 16)
    result = inventory.analyze_source('db.execute("SELECT ?")')
    assert result['issues'] == ['string_work_limit'] and result['analysis_string_bytes'] <= 16
    assert result['resolution_steps'] <= inventory.LIMITS['resolution_steps']


def test_global_resolution_and_string_work_budgets_make_scan_incomplete(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch, {'a.py': 'db.execute("SELECT ?")', 'b.py': 'db.execute("SELECT ?")'})
    monkeypatch.setitem(inventory.LIMITS, 'total_resolution_steps', 1)
    first = inventory.scan()
    assert not first['complete'] and first['counts']['resolution_steps'] <= 1
    assert any('resolution_limit' in row['issues'] for row in first['files'])
    monkeypatch.setitem(inventory.LIMITS, 'total_resolution_steps', 100000)
    monkeypatch.setitem(inventory.LIMITS, 'total_analysis_string_bytes', 16)
    second = inventory.scan()
    assert not second['complete'] and second['counts']['analysis_string_bytes'] <= 16
    assert any('string_work_limit' in row['issues'] for row in second['files'])


@pytest.mark.parametrize('rebind', ['for SQL in rows:\n        pass', 'with source as SQL:\n        pass',
                                  'import module as SQL', 'del SQL', 'def SQL():\n        pass'])
def test_other_lexical_bindings_are_unresolved_instead_of_borrowing_global_sql(rebind):
    source = 'SQL="SELECT private FROM sqlite_master WHERE id=?"\ndef read():\n    ' + rebind + '\n    return db.execute(SQL)\n'
    found = categories(source)
    assert found['sql.call_unresolved'] == 1 and found['sql.sqlite_catalog'] == 0


def test_scanner_reads_only_fixed_tree_python_and_returns_hashes_not_source(tmp_path, monkeypatch):
    root = source_tree(tmp_path, monkeypatch, {'nested/sample.py': 'db.execute("SELECT token FROM secrets WHERE id=?")\n',
                                               'page.html': 'token=synthetic-private', 'readme.txt': 'CANARY'})
    result = inventory.scan()
    assert result['complete'] and result['counts']['parsed_files'] == result['counts']['discovered_files'] == 1
    assert result['files'][0]['file'] == 'agent_market/nested/sample.py'
    assert result['files'][0]['sha256'] == hashlib.sha256((root / 'nested/sample.py').read_bytes()).hexdigest()
    rendered = json.dumps(result)
    assert str(tmp_path) not in rendered and 'SELECT token' not in rendered and 'CANARY' not in rendered
    assert result['coverage']['all_runtime_storage_access_resolved'] is False
    assert result['coverage']['sql_dialect_compatibility_verified'] is False
    assert result['coverage']['complete_means'] == 'bounded_syntactic_scan_only'


@pytest.mark.parametrize('content,code', [('def invalid(:\n', 'parse_failed'), (b'\xff\xfe', 'encoding_failed')])
def test_invalid_source_is_incomplete_not_a_false_zero_success(tmp_path, monkeypatch, content, code):
    source_tree(tmp_path, monkeypatch, {'broken.py': content})
    result = inventory.scan()
    assert result['ok'] is True and result['complete'] is False
    assert result['counts']['incomplete_files'] == 1 and code in result['files'][0]['issues']
    assert result['counts']['parsed_files'] == 0


@pytest.mark.parametrize('kind', ['file', 'directory', 'hardlink', 'fifo'])
def test_symlinks_shared_files_and_special_sources_are_never_followed(tmp_path, monkeypatch, kind):
    root = source_tree(tmp_path, monkeypatch)
    outside = tmp_path / 'outside.py'; outside.write_text('db.execute("SELECT synthetic_private_data")')
    if kind == 'file': (root / 'linked.py').symlink_to(outside)
    elif kind == 'directory': (root / 'linked').symlink_to(tmp_path, target_is_directory=True)
    elif kind == 'hardlink': os.link(outside, root / 'shared.py')
    else: os.mkfifo(root / 'pipe.py')
    result = inventory.scan()
    assert not result['complete'] and 'synthetic_private_data' not in json.dumps(result)
    assert all('sha256' not in row for row in result['files'] if not row['complete'])
    assert outside.read_text() == 'db.execute("SELECT synthetic_private_data")'


def test_file_and_total_byte_bounds_stop_before_parsing(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch, {'big.py': 'x' * 100})
    monkeypatch.setitem(inventory.LIMITS, 'file_bytes', 20)
    result = inventory.scan()
    assert not result['complete'] and result['files'][0]['issues'] == ['file_byte_limit']
    assert result['counts']['bytes_read'] == 0
    monkeypatch.setitem(inventory.LIMITS, 'file_bytes', 200)
    monkeypatch.setitem(inventory.LIMITS, 'total_bytes', 20)
    assert inventory.scan()['files'][0]['issues'] == ['total_byte_limit']


def test_ast_and_finding_limits_are_reported_without_false_complete(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch)
    monkeypatch.setitem(inventory.LIMITS, 'file_ast_nodes', 2)
    assert inventory.scan()['files'][0]['issues'] == ['ast_node_limit']
    monkeypatch.setitem(inventory.LIMITS, 'file_ast_nodes', 1000)
    monkeypatch.setitem(inventory.LIMITS, 'findings', 1)
    result = inventory.scan()
    assert not result['complete'] and len(result['findings']) == 1 and 'finding_limit' in result['files'][0]['issues']


def test_file_count_and_directory_entry_limits_are_bounded_and_explicit(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch, {'a.py': 'x=1', 'b.py': 'x=2', 'c.py': 'x=3'})
    monkeypatch.setitem(inventory.LIMITS, 'files', 1)
    result = inventory.scan()
    assert not result['complete'] and len(result['files']) == 1 and result['counts']['file_count_exact'] is False
    assert result['issues'] == ['file_limit']
    monkeypatch.setitem(inventory.LIMITS, 'files', 256)
    monkeypatch.setitem(inventory.LIMITS, 'directory_entries', 1)
    assert 'directory_entry_limit' in inventory.scan()['issues']


def test_total_ast_and_depth_budgets_are_explicit(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch, {'a.py': 'x=1', 'nested/b.py': 'x=2'})
    monkeypatch.setitem(inventory.LIMITS, 'total_ast_nodes', 2)
    result = inventory.scan()
    assert not result['complete'] and any('total_ast_node_limit' in row['issues'] for row in result['files'])
    monkeypatch.setitem(inventory.LIMITS, 'total_ast_nodes', 1000000)
    monkeypatch.setitem(inventory.LIMITS, 'depth', 0)
    assert 'directory_limit' in inventory.scan()['issues']


def test_empty_and_unavailable_source_roots_are_not_successful(tmp_path, monkeypatch):
    root = source_tree(tmp_path, monkeypatch); (root / 'sample.py').unlink()
    result = inventory.scan()
    assert not result['complete'] and result['issues'] == ['no_python_source']
    monkeypatch.setattr(inventory, '_source_root', lambda: root / 'missing')
    with pytest.raises(inventory.InventoryError): inventory.scan()


@pytest.mark.parametrize('file', ['/private/secret.py', 'agent_market/../secret.py', 'agent_market/private\nsecret.py', 'other/sample.py'])
def test_analysis_never_accepts_an_absolute_or_unsafe_report_filename(file):
    with pytest.raises(inventory.InventoryError): inventory.analyze_source('pass', file)


def test_scan_does_not_open_sqlite_or_network_or_execute_source(tmp_path, monkeypatch):
    source_tree(tmp_path, monkeypatch, {'sample.py': 'raise RuntimeError("synthetic-private-diagnostic")\nimport sqlite3\nsqlite3.connect("operating.sqlite3")\n'})
    with patch.object(sqlite3, 'connect', side_effect=AssertionError('No DB')):
        result = inventory.scan()
    assert result['complete'] and result['counts']['categories']['sqlite.connect'] == 1
    assert not (tmp_path / 'operating.sqlite3').exists() and 'synthetic-private-diagnostic' not in json.dumps(result)


def test_import_is_inert_even_if_environment_database_and_root_resolution_are_forbidden():
    script = '''import argparse,ast,hashlib,json,os,pathlib,re,sqlite3,stat,socket
from unittest.mock import patch
def forbidden(*args,**kwargs): raise AssertionError("No operational effect")
with patch.object(sqlite3,"connect",forbidden),patch.object(socket,"socket",forbidden),patch.object(os.environ,"get",forbidden),patch.object(pathlib.Path,"resolve",forbidden):
    import agent_market.storage_inventory
'''
    completed = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0 and completed.stdout == completed.stderr == ''


@pytest.mark.parametrize('arguments', [[], ['--db', '/private/secret'], ['--root', '/private/secret'], ['--report', '/private/secret'], ['--sc'], ['--scan', '--scan']])
def test_cli_requires_exact_explicit_scan_without_root_db_report_or_echo(arguments, capsys):
    assert inventory.main(arguments) == 2
    captured = capsys.readouterr(); value = json.loads(captured.out)
    assert value == {'ok': False, 'profile': inventory.PROFILE, 'error': 'invalid_arguments'}
    assert captured.err == '' and '/private/' not in captured.out


def test_cli_fixed_errors_and_incomplete_exit_are_bounded(capsys, monkeypatch):
    monkeypatch.setattr(inventory, 'scan', lambda: {'ok': True, 'profile': inventory.PROFILE, 'complete': False})
    assert inventory.main(['--scan']) == 1 and json.loads(capsys.readouterr().out)['complete'] is False
    def broken(): raise RuntimeError('synthetic-private-diagnostic /private/secret')
    monkeypatch.setattr(inventory, 'scan', broken)
    assert inventory.main(['--scan']) == 1
    captured = capsys.readouterr(); assert 'synthetic-private' not in captured.out + captured.err
    assert json.loads(captured.out)['error'] == 'source_unavailable'


def test_real_repository_cli_is_source_only_and_includes_actual_store_definitions():
    result = subprocess.run([sys.executable, 'scripts/audit_storage_boundary.py', '--scan'], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and result.stderr == ''
    value = json.loads(result.stdout)
    assert value['complete'] and value['counts']['parsed_files'] >= 100
    assert value['counts']['categories']['definition.store_tx'] == value['counts']['categories']['definition.store_query'] == 1
    assert value['counts']['categories']['sql.call_unresolved'] > 0
    assert all(row['file'].startswith('agent_market/') and not row['file'].startswith('/') for row in value['files'])
    assert str(Path.cwd()) not in result.stdout


def test_cli_source_scope_does_not_follow_the_callers_working_directory(tmp_path):
    fake = tmp_path / 'agent_market'; fake.mkdir()
    (fake / 'private.py').write_text('db.execute("SELECT synthetic_cwd_secret")')
    script = Path('scripts/audit_storage_boundary.py').resolve()
    result = subprocess.run([sys.executable, str(script), '--scan'], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and result.stderr == ''
    value = json.loads(result.stdout)
    assert value['complete'] and value['counts']['parsed_files'] >= 100
    assert not any(row['file'] == 'agent_market/private.py' for row in value['files'])
    assert str(tmp_path) not in result.stdout and 'synthetic_cwd_secret' not in result.stdout
