"""Report cleanup keeps the true newest subject and rolls back unsafe changes."""
import datetime
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from agent_market.report_creation import install_sqlite_guard, find_existing, subject
from scripts import deduplicate_test_reports as script


@pytest.fixture
def reports(tmp_path):
    path = tmp_path / 'reports.sqlite3'
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE agent_test_reports (
            id INTEGER PRIMARY KEY,resource_id INTEGER,kind TEXT,agent_name TEXT,agent_url TEXT,
            created_at REAL,updated_at REAL,creation_subject_key TEXT UNIQUE,
            title TEXT,content_md TEXT);
        CREATE TABLE test_report_subject_claims(
            subject_key TEXT PRIMARY KEY,report_id INTEGER REFERENCES agent_test_reports(id));
    ''')
    def add(rid, date, *, name='Weather', url='https://weather.example/api', kind='mcp',
            resource_id=7, key=None, updated=None):
        db.execute('INSERT INTO agent_test_reports VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (rid,resource_id,kind,name,url,date,updated or date,key,'Report '+str(rid),'Original '+str(rid)))
        db.commit()
    add(1,datetime.datetime(2026,10,15,tzinfo=datetime.timezone.utc).timestamp())
    add(2,'2026-10-17 09:47:00')
    add(3,'2026-10-16 00:00:00',name='Other',url='https://other.example/api')
    yield path,db,add
    db.close()


def ids(db):
    return [row[0] for row in db.execute('SELECT id FROM agent_test_reports ORDER BY id')]


def test_dry_run_then_apply_keeps_real_newest_with_private_full_backup_and_is_idempotent(reports,tmp_path):
    path,db,_ = reports
    before = db.execute('SELECT * FROM agent_test_reports ORDER BY id').fetchall()
    dry = script.cleanup(path)
    assert dry['eligible_deletions'] == 1 and dry['deleted'] == 0 and ids(db) == [1,2,3]
    result = script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert result['deleted'] == 1 and result['reports_after'] == 2 and ids(db) == [2,3]
    assert db.execute('SELECT * FROM agent_test_reports ORDER BY id').fetchall() == before[1:]
    backup = Path(result['backup_file'])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    saved = json.loads(backup.read_text())
    assert [row['id'] for row in saved['reports']] == [1,2,3]
    assert saved['keep_delete_mapping'] == [{'keep_id':2,'delete_ids':[1]}]
    assert script.cleanup(path,apply=True,backup_dir=tmp_path/'private')['deleted'] == 0


def test_local_id_collisions_and_gateway_name_differences_are_separate_subjects(reports,tmp_path):
    path,db,add = reports
    url = 'https://agentconcierge.biz/api/gateway/mcp/7'
    add(4,'2026-10-18 01:00:00',url=url,name='First original subject')
    add(5,'2026-10-18 02:00:00',url=url,name='Different original subject')
    add(6,'2026-10-18 03:00:00',url=url,name=' first ORIGINAL subject ')
    result = script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert result['deleted'] == 2
    assert ids(db) == [2,3,5,6]


def test_provider_aliases_share_complete_endpoint_but_paths_and_protocols_do_not(reports,tmp_path):
    path,db,add = reports
    add(4,'2026-10-18 01:00:00',url='https://WEATHER.example:443/api',name='Renamed agent')
    add(5,'2026-10-18 01:00:00',url='https://weather.example/other')
    add(6,'2026-10-18 01:00:00',url='https://weather.example/api',kind='a2a')
    result = script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert result['deleted'] == 2
    assert ids(db) == [3,4,5,6]


def test_creation_time_wins_over_edits_and_equal_creation_uses_highest_id(reports,tmp_path):
    path,db,add = reports
    db.execute('UPDATE agent_test_reports SET updated_at=? WHERE id=1',(9e9,));db.commit()
    add(4,'2026-10-17T18:47:00+09:00')
    script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert ids(db) == [3,4]


def test_unknown_dates_are_preserved_instead_of_guessing_newest(reports,tmp_path):
    path,db,add = reports
    add(4,'unknown')
    result = script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert result['deleted'] == 0 and result['unorderable_groups'] == 1
    assert ids(db) == [1,2,3,4]


def test_subject_claim_follows_retained_report_and_raw_creation_stays_blocked(reports,tmp_path):
    path,db,_ = reports
    key,kind,endpoint = subject(None,None,'mcp','https://weather.example/api')
    db.execute('UPDATE agent_test_reports SET creation_subject_key=? WHERE id=1',(key,))
    db.execute('INSERT INTO test_report_subject_claims VALUES (?,1)',(key,))
    install_sqlite_guard(db);db.commit()
    script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert db.execute('SELECT report_id FROM test_report_subject_claims').fetchone()[0] == 2
    assert db.execute('SELECT creation_subject_key FROM agent_test_reports WHERE id=2').fetchone()[0] == key
    class Reader:
        def query(self,sql,params=()):
            db.row_factory=sqlite3.Row
            return db.execute(sql,params).fetchall()
    assert find_existing(Reader(),(key,kind,endpoint)) == 2
    with pytest.raises(sqlite3.IntegrityError,match='report_creation_reservation_required'):
        db.execute('INSERT INTO agent_test_reports(id,kind) VALUES (99,\'mcp\')')


def test_nonprivate_or_symlink_backup_directory_refuses_all_deletion(reports,tmp_path):
    path,db,_ = reports
    directory=tmp_path/'public';directory.mkdir(mode=0o755);directory.chmod(0o755)
    with pytest.raises(script.CleanupError,match='backup_directory_not_private'):
        script.cleanup(path,apply=True,backup_dir=directory)
    assert ids(db) == [1,2,3]
    private=tmp_path/'private';private.mkdir(mode=0o700)
    link=tmp_path/'link';link.symlink_to(private,target_is_directory=True)
    with pytest.raises(script.CleanupError,match='backup_directory_not_private'):
        script.cleanup(path,apply=True,backup_dir=link)
    assert ids(db) == [1,2,3]


def test_delete_trigger_side_effect_rolls_back_every_change(reports,tmp_path):
    path,db,_ = reports
    db.execute('''CREATE TRIGGER mutate_survivor AFTER DELETE ON agent_test_reports
                  BEGIN UPDATE agent_test_reports SET title='Unexpected change' WHERE id=3; END''');db.commit()
    with pytest.raises(script.CleanupError,match='unexpected_surviving_report_change'):
        script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert ids(db) == [1,2,3]
    assert db.execute('SELECT title FROM agent_test_reports WHERE id=3').fetchone()[0] == 'Report 3'


def test_unreviewed_foreign_reference_and_retired_writer_refuse_cleanup(reports,tmp_path):
    path,db,_ = reports
    db.execute('CREATE TABLE other_report_reference(id INTEGER REFERENCES agent_test_reports(id))');db.commit()
    with pytest.raises(script.CleanupError,match='unsupported_report_reference'):script.cleanup(path)
    db.execute('DROP TABLE other_report_reference');db.execute('CREATE TABLE application_source_writer_fence(id INTEGER)');db.commit()
    with pytest.raises(sqlite3.OperationalError,match='application_source_writer_retired'):
        script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert ids(db) == [1,2,3]


def test_concurrent_report_change_is_detected_before_backup_or_delete(reports,tmp_path,monkeypatch):
    path,db,_ = reports
    original=script.plan
    def changed(rows):
        result=original(rows)
        db.execute("UPDATE agent_test_reports SET title='Concurrent edit' WHERE id=1");db.commit()
        return result
    monkeypatch.setattr(script,'plan',changed)
    with pytest.raises(script.CleanupError,match='reports_changed_since_preflight'):
        script.cleanup(path,apply=True,backup_dir=tmp_path/'private')
    assert ids(db) == [1,2,3] and not (tmp_path/'private').exists()


def test_cli_refuses_missing_backup_or_symlink_database_without_private_output(reports,tmp_path,capsys):
    path,db,_ = reports
    assert script.main(['--db',str(path),'--apply']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'private_backup_directory_required'
    link=tmp_path/'linked.sqlite3';link.symlink_to(path)
    assert script.main(['--db',str(link)]) == 1
    assert str(path) not in capsys.readouterr().out
    assert ids(db) == [1,2,3]
