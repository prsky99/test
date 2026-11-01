"""Pruning follows public subject identity and atomically preserves reviewed rows."""
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from agent_market.concierge.report_evidence import current_version_id
from agent_market.report_creation import install_sqlite_guard
from scripts import prune_unconfirmed_test_reports as script


@pytest.fixture
def records(tmp_path):
    path = tmp_path / 'isolated.sqlite3'
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,name TEXT,url TEXT,
            active INTEGER,health_status TEXT,eval_security TEXT,usage_full_tools TEXT);
        CREATE TABLE agent_test_reports(id INTEGER PRIMARY KEY,resource_id INTEGER,kind TEXT,
            agent_name TEXT,agent_url TEXT,connection_version_id TEXT,creation_subject_key TEXT,
            title TEXT,content_md TEXT,created_at REAL);
        CREATE TABLE test_report_subject_claims(subject_key TEXT PRIMARY KEY,
            report_id INTEGER REFERENCES agent_test_reports(id));
        INSERT INTO resources VALUES(7,'mcp','Weather','https://weather.example/api',1,'healthy','', '[]');
        INSERT INTO resources VALUES(8,'a2a','History','https://history.example/api',0,'down','', '[]');
        INSERT INTO agent_test_reports VALUES(1,7,'mcp','Weather','https://weather.example/api',NULL,NULL,'One','Original one',10);
        INSERT INTO agent_test_reports VALUES(2,8,'a2a','History','https://history.example/api',NULL,NULL,'Two','Original two',20);
        INSERT INTO agent_test_reports VALUES(3,7,'mcp','Wrong name','https://weather.example/api',NULL,NULL,'Three','Original three',30);
        INSERT INTO agent_test_reports VALUES(4,7,'mcp','Weather','https://agentconcierge.biz/api/gateway/mcp/7',NULL,NULL,'Four','Original four',40);
        INSERT INTO agent_test_reports VALUES(5,7,'a2a','Weather','https://weather.example/api',NULL,NULL,'Five','Original five',50);
    ''')
    db.commit()
    yield path, db
    db.close()


def run(path, tmp_path, **changes):
    return script.cleanup(path, **{'expected_kept': 2, 'expected_deleted': 3,
        'apply': True, 'backup_dir': tmp_path/'private', **changes})


def test_preserves_exact_valid_and_historical_rows_full_private_backup_and_guards(records, tmp_path):
    path, db = records
    install_sqlite_guard(db)
    db.execute("INSERT INTO test_report_subject_claims VALUES ('retained-claim',1)")
    db.commit()
    before = script._rows(db)
    triggers = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
    dry = run(path, tmp_path, apply=False)
    assert dry['kept'] == 2 and dry['deleted'] == 0 and script._rows(db) == before
    result = run(path, tmp_path, expected_kept_sha256=dry['kept_ids_sha256'])
    assert result['deleted'] == 3 and result['reports_after'] == 2
    assert script._rows(db) == before[:2]
    assert db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall() == triggers
    assert db.execute('SELECT report_id FROM test_report_subject_claims').fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match='report_creation_reservation_required'):
        db.execute("INSERT INTO agent_test_reports(id,kind) VALUES (99,'mcp')")
    db.rollback()
    backup = Path(result['backup_file'])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    saved = json.loads(backup.read_text())
    assert saved['reports'] == before and saved['claims'] == [{'subject_key':'retained-claim','report_id':1}]
    assert saved['plan']['keep_ids'] == [1,2] and saved['plan']['delete_ids'] == [3,4,5]
    assert run(path, tmp_path, expected_deleted=0)['deleted'] == 0


@pytest.mark.parametrize('changes', [
    {'expected_kept':3}, {'expected_deleted':4}, {'expected_kept_sha256':'unreviewed'},
    {'expected_kept':0}, {'backup_dir':None},
])
def test_explicit_scope_and_backup_are_required_before_any_deletion(records, tmp_path, changes):
    path, db = records
    before = script._rows(db)
    with pytest.raises(script.CleanupError): run(path,tmp_path,**changes)
    assert script._rows(db) == before and not (tmp_path/'private').exists()


def test_gateway_version_uses_full_resource_schema(records, tmp_path):
    path, db = records
    resource = dict(db.execute('SELECT * FROM resources WHERE id=7').fetchone())
    db.execute('UPDATE agent_test_reports SET connection_version_id=? WHERE id=4',
               (current_version_id(resource),))
    db.commit()
    result = run(path,tmp_path,expected_kept=3,expected_deleted=2)
    assert result['kept'] == 3 and [row['id'] for row in script._rows(db)] == [1,2,4]


@pytest.mark.parametrize('change',[
    "UPDATE resources SET eval_security='quarantine' WHERE id=7",
    "UPDATE resources SET health_status='quarantined' WHERE id=7",
    "UPDATE resources SET url='https://weather.example/different-path' WHERE id=7",
    "DELETE FROM resources WHERE id=7",
])
def test_public_identity_and_quarantine_gates_match_explore(records, tmp_path, change):
    path, db = records
    db.execute(change); db.commit()
    result = run(path,tmp_path,expected_kept=1,expected_deleted=4)
    assert result['kept'] == 1 and [row['id'] for row in script._rows(db)] == [2]


def test_reservation_for_deleted_row_refuses_without_repointing_to_unrelated_subject(records,tmp_path):
    path, db = records
    db.execute("INSERT INTO test_report_subject_claims VALUES ('old-subject',3)"); db.commit()
    with pytest.raises(script.CleanupError,match='unconfirmed_report_has_subject_reservation'):
        run(path,tmp_path)
    assert len(script._rows(db)) == 5
    assert db.execute('SELECT report_id FROM test_report_subject_claims').fetchone()[0] == 3


@pytest.mark.parametrize('change', ['report','subject'])
def test_concurrent_changes_abort_instead_of_widening_deletion(records,tmp_path,monkeypatch,change):
    path, db = records
    original = script.plan
    calls = []
    def changed(conn,rows):
        result = original(conn,rows)
        if not calls:
            calls.append(True)
            if change == 'report': db.execute("UPDATE agent_test_reports SET title='Concurrent edit' WHERE id=3")
            else: db.execute("UPDATE resources SET name='Changed provider' WHERE id=7")
            db.commit()
        return result
    monkeypatch.setattr(script,'plan',changed)
    with pytest.raises(script.CleanupError,match='changed_since_preflight'): run(path,tmp_path)
    assert len(script._rows(db)) == 5 and not (tmp_path/'private').exists()


def test_trigger_side_effects_and_retired_writers_are_refused(records,tmp_path):
    path, db = records
    db.execute("CREATE TRIGGER side_effect AFTER DELETE ON agent_test_reports BEGIN UPDATE resources SET name='Wrong'; END")
    db.commit()
    with pytest.raises(script.CleanupError,match='unreviewed_report_delete_trigger'): run(path,tmp_path)
    db.execute('DROP TRIGGER side_effect')
    db.execute('CREATE TABLE application_source_writer_fence(id INTEGER)'); db.commit()
    with pytest.raises(sqlite3.OperationalError,match='application_source_writer_retired'): run(path,tmp_path)
    assert len(script._rows(db)) == 5


def test_backup_failure_rolls_back_and_cli_does_not_leak_private_data(records,tmp_path,capsys):
    path, db = records
    directory = tmp_path/'public'; directory.mkdir(mode=0o755); directory.chmod(0o755)
    assert script.main(['--db',str(path),'--expected-kept','2','--expected-deleted','3',
                        '--apply','--backup-dir',str(directory)]) == 1
    response = capsys.readouterr().out
    assert json.loads(response)['error'] == 'backup_directory_not_private'
    assert 'Original' not in response and str(path) not in response
    assert len(script._rows(db)) == 5
