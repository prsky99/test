"""An explicit private backup and independent endpoint proof precede repair."""
import hashlib
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from agent_market.concierge.report_evidence import (
    install_report_identity_guards, measured_report, report_subject_matches,
)
from scripts import repair_report_bindings as repair


SCHEMA = '''
CREATE TABLE resources(id INTEGER PRIMARY KEY,key TEXT UNIQUE,kind TEXT,name TEXT,url TEXT);
CREATE TABLE agent_test_reports(id INTEGER PRIMARY KEY,resource_id INTEGER,title TEXT,slug TEXT,
 kind TEXT,agent_name TEXT,agent_url TEXT,is_success INTEGER,eval_grade TEXT,created_at REAL,
 updated_at REAL,content_md TEXT,input_wire TEXT,output_wire TEXT);
CREATE TABLE connection_versions(id TEXT PRIMARY KEY,resource_id INTEGER);
'''
SECRET = 'private-original-wire-fixture'


def write(path, sql, parameters=()):
    with sqlite3.connect(path) as con:
        con.execute(sql, parameters)


def row(path, table='agent_test_reports', row_id=3):
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute('SELECT * FROM '+table+' WHERE id=?', (row_id,)).fetchone())


@pytest.fixture
def databases(tmp_path):
    source, destination = tmp_path/'source.sqlite3', tmp_path/'destination.sqlite3'
    for path in (source, destination):
        with sqlite3.connect(path) as con:
            con.executescript(SCHEMA)
            if path == destination:
                for column, declaration in (('evidence_scope','TEXT'),('executed_at','REAL'),
                        ('execution_finished_at','REAL'),('connection_version_id','TEXT')):
                    con.execute('ALTER TABLE agent_test_reports ADD COLUMN '+column+' '+declaration)
            con.execute('INSERT INTO agent_test_reports(id,resource_id,title,slug,kind,agent_name,agent_url,is_success,eval_grade,created_at,updated_at,content_md,input_wire,output_wire) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (99 if path == source else 3, 7, 'Historical Weather', 'weather-report', 'mcp', 'Weather',
                 'https://agentconcierge.biz/api/gateway/mcp/7', 1, 'A', 123.5, 124.5, SECRET, SECRET, SECRET))
    write(source, 'INSERT INTO resources VALUES(?,?,?,?,?)',
          (7,'stable-weather','mcp','Weather','https://weather.example/mcp?region=global'))
    write(destination, 'INSERT INTO resources VALUES(?,?,?,?,?)',
          (7,'unrelated','a2a','Other Subject','https://other.example/agent'))
    write(destination, 'INSERT INTO resources VALUES(?,?,?,?,?)',
          (42,'stable-weather','mcp','Weather','https://weather.example/mcp?region=global'))
    with sqlite3.connect(destination) as con:
        install_report_identity_guards(con)
    return source, destination, tmp_path/'private-backups'


def unguarded(path, sql, parameters=()):
    with sqlite3.connect(path) as con:
        con.execute('DROP TRIGGER report_subject_update')
        con.execute(sql, parameters)
        install_report_identity_guards(con)


def test_dry_run_is_readonly_and_cli_discloses_only_aggregate_counts(databases, capsys):
    source, destination, backup = databases
    before = [p.read_bytes() for p in (source,destination)]
    assert repair.main(['--source-db',str(source),'--db',str(destination)]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['eligible'] == 1 and result['changed'] == 0 and result['mode'] == 'dry_run'
    assert result['protocols'] == {'mcp':1}
    assert not output.err and not backup.exists()
    assert [p.read_bytes() for p in (source,destination)] == before
    for private in (SECRET,'weather.example','Weather','stable-weather',str(destination)):
        assert private not in output.out


def test_cross_database_id_repair_preserves_history_and_cannot_assert_execution(databases):
    source, destination, backup = databases
    original, source_bytes = row(destination), source.read_bytes()
    result = repair.repair(source,destination,apply=True,backup_dir=backup)
    assert result['changed'] == 1 and result['backup_created']
    expected = {**original,'resource_id':42,'agent_name':'Weather',
                'agent_url':'https://weather.example/mcp?region=global','evidence_scope':'legacy'}
    updated = row(destination)
    assert updated == expected and source.read_bytes() == source_bytes
    resource = row(destination,'resources',42)
    assert report_subject_matches(updated,resource)
    assert measured_report(updated,resource,object(),9999) is False
    assert all(updated[key] is None for key in ('executed_at','execution_finished_at','connection_version_id'))
    with sqlite3.connect(destination) as con:
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0] == 2
    files = list(backup.glob('*.json'))
    assert len(files) == 1 and stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    saved = json.loads(files[0].read_text())['rows'][0]
    assert saved['before'] == original and saved['source_resource']['key'] == 'stable-weather'
    assert saved['source_resource']['url'] == expected['agent_url']
    assert saved['destination_report_digest'] == hashlib.sha256(repair._packed(original)).hexdigest()
    repeated = repair.repair(source,destination,apply=True,backup_dir=backup)
    assert repeated['eligible'] == repeated['changed'] == 0
    assert repeated['skipped'] == {'already_bound':1} and len(list(backup.glob('*.json'))) == 1


@pytest.mark.parametrize('side,sql,reason', [
    ('source',"UPDATE agent_test_reports SET agent_name='Wrong'",'source_report_mismatch'),
    ('destination',"UPDATE agent_test_reports SET agent_name='Wrong'",'source_report_mismatch'),
    ('source',"UPDATE agent_test_reports SET kind='a2a'",'source_report_mismatch'),
    ('source',"UPDATE agent_test_reports SET title='Different'",'source_report_mismatch'),
    ('source',"UPDATE agent_test_reports SET agent_url='https://agentconcierge.biz/api/gateway/mcp/8'",'source_gateway_mismatch'),
    ('destination',"UPDATE agent_test_reports SET agent_url='https://wrong.example/mcp'",'destination_gateway_mismatch'),
    ('source',"UPDATE resources SET name='Wrong'",'source_resource_mismatch'),
    ('source',"UPDATE resources SET kind='a2a'",'source_resource_mismatch'),
    ('source',"UPDATE resources SET url='https://agentconcierge.biz/api/gateway/mcp/88'",'source_endpoint_invalid'),
    ('source',"UPDATE resources SET url='https://weather.example/mcp?region=other'",'destination_subject_changed'),
    ('destination',"UPDATE resources SET name='Wrong' WHERE id=42",'destination_subject_changed'),
    ('destination',"UPDATE resources SET key='different' WHERE id=42",'destination_key_missing_or_ambiguous'),
    ('destination',"INSERT INTO resources VALUES(43,'duplicate','mcp','Weather','https://weather.example/mcp?region=global')",'destination_subject_ambiguous'),
])
def test_mismatches_and_ambiguous_subjects_are_excluded(databases,side,sql,reason):
    source, destination, _ = databases
    if side == 'destination' and 'UPDATE agent_test_reports' in sql:
        unguarded(destination,sql)
    else:
        write(source if side == 'source' else destination,sql)
    result = repair.repair(source,destination)
    assert result['eligible'] == 0 and result['skipped'] == {reason:1}


@pytest.mark.parametrize('column,value', [
    ('evidence_scope','execution'),('executed_at',100),('execution_finished_at',101),
    ('connection_version_id','cv-existing'),('evidence_scope','contract'),
])
def test_current_or_partial_execution_records_are_never_repaired(databases,column,value):
    source, destination, backup = databases
    unguarded(destination,'UPDATE agent_test_reports SET '+column+'=?',(value,))
    original = row(destination)
    result = repair.repair(source,destination,apply=True,backup_dir=backup)
    assert result['eligible'] == result['changed'] == 0
    assert result['skipped'] == {'not_legacy_unexecuted':1}
    assert row(destination) == original and not backup.exists()


@pytest.mark.parametrize('side', ['source','destination'])
def test_duplicate_report_slug_is_not_provenance(databases,side):
    source, destination, _ = databases
    path = source if side == 'source' else destination
    with sqlite3.connect(path) as con:
        if side == 'destination':
            con.execute('DROP TRIGGER report_subject_insert')
        columns = [r[1] for r in con.execute('PRAGMA table_info(agent_test_reports)')]
        con.execute('INSERT INTO agent_test_reports SELECT '+','.join('1000' if c=='id' else c for c in columns)+' FROM agent_test_reports')
    result = repair.repair(source,destination)
    assert result['eligible'] == 0 and 'missing_or_ambiguous_slug' in result['skipped']


def test_backup_flush_failure_precedes_every_database_write(databases,monkeypatch):
    source, destination, backup = databases
    original = destination.read_bytes()
    def fail(_):
        raise OSError(SECRET)
    monkeypatch.setattr(repair.os,'fsync',fail)
    with pytest.raises(repair.RepairError,match='backup_failed'):
        repair.repair(source,destination,apply=True,backup_dir=backup)
    assert destination.read_bytes() == original and list(backup.glob('*.json')) == []


@pytest.mark.parametrize('symlink', [False,True])
def test_backup_directory_must_be_owner_only_and_not_a_symlink(databases,tmp_path,symlink):
    source, destination, backup = databases
    if symlink:
        actual = tmp_path/'actual';actual.mkdir(mode=0o700);backup.symlink_to(actual,target_is_directory=True)
    else:
        backup.mkdir(mode=0o755);backup.chmod(0o755)
    original = destination.read_bytes()
    with pytest.raises(repair.RepairError,match='backup_failed'):
        repair.repair(source,destination,apply=True,backup_dir=backup)
    assert destination.read_bytes() == original


def test_fresh_resource_change_aborts_before_backup_or_updates(databases,monkeypatch):
    source, destination, backup = databases
    open_original = repair._open
    def changed(path,*,readonly):
        if not readonly:
            write(destination,"UPDATE resources SET url='https://changed.example/mcp' WHERE id=42")
        return open_original(path,readonly=readonly)
    monkeypatch.setattr(repair,'_open',changed)
    original = row(destination)
    with pytest.raises(repair.RepairError,match='destination_changed_since_preflight'):
        repair.repair(source,destination,apply=True,backup_dir=backup)
    assert row(destination) == original and not backup.exists()


def test_trigger_failure_rolls_back_all_rows_and_cli_redacts_errors(databases,capsys):
    source, destination, backup = databases
    for path in (source,destination):
        with sqlite3.connect(path) as con:
            if path == destination:
                con.execute('DROP TRIGGER report_subject_insert')
            columns = [r[1] for r in con.execute('PRAGMA table_info(agent_test_reports)')]
            select = ['1000' if c=='id' else "'second-report'" if c=='slug' else c for c in columns]
            con.execute('INSERT INTO agent_test_reports SELECT '+','.join(select)+' FROM agent_test_reports')
    write(destination,"CREATE TRIGGER abort_second BEFORE UPDATE ON agent_test_reports WHEN OLD.id=1000 BEGIN SELECT RAISE(ABORT,'"+SECRET+"'); END")
    original = destination.read_bytes()
    assert repair.main(['--source-db',str(source),'--db',str(destination),'--apply','--backup-dir',str(backup)]) == 1
    output = capsys.readouterr()
    assert not output.out and SECRET not in output.err and 'database_or_backup_error' in output.err
    assert destination.read_bytes() == original
    assert len(list(backup.glob('*.json'))) == 1


def test_same_database_and_missing_backup_are_rejected(databases):
    source, destination, _ = databases
    with pytest.raises(repair.RepairError,match='must_differ'):
        repair.repair(source,source)
    with pytest.raises(repair.RepairError,match='backup_directory_required'):
        repair.repair(source,destination,apply=True)
