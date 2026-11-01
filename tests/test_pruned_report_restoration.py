"""Historical recovery must preserve identity, evidence boundaries and reversibility."""
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from agent_market.concierge.report_evidence import install_report_identity_guards, report_subject_matches
from agent_market.report_creation import install_sqlite_guard, subject
from scripts import restore_pruned_test_reports as recovery


SCHEMA = '''
CREATE TABLE resources(id INTEGER PRIMARY KEY,key TEXT,kind TEXT,name TEXT,url TEXT,
 active INTEGER,health_status TEXT,eval_security TEXT);
CREATE TABLE agent_test_reports(id INTEGER PRIMARY KEY,resource_id INTEGER,title TEXT,slug TEXT UNIQUE,
 kind TEXT,source TEXT,agent_name TEXT,agent_url TEXT,created_at REAL,updated_at REAL,
 content_md TEXT,input_wire TEXT,output_wire TEXT,is_success INTEGER,eval_grade TEXT,
 evidence_scope TEXT,executed_at REAL,execution_finished_at REAL,connection_version_id TEXT,
 creation_subject_key TEXT);
CREATE TABLE connection_versions(id TEXT PRIMARY KEY,resource_id INTEGER);
CREATE TABLE capability_evidence(id TEXT PRIMARY KEY,resource_id INTEGER);
CREATE TABLE test_report_subject_claims(subject_key TEXT PRIMARY KEY,report_id INTEGER REFERENCES agent_test_reports(id));
'''


def report(i, name, endpoint=None, created=10):
    return dict(id=i, resource_id=i, title='Report '+str(i), slug='report-'+str(i),
                kind='mcp', source='retained', agent_name=name,
                agent_url=endpoint or 'https://agentconcierge.biz/api/gateway/mcp/'+str(i),
                created_at=created, updated_at=created, content_md='Historical output',
                input_wire='{"url":"https://agentconcierge.biz/api/gateway/mcp/'+str(i)+'"}',
                output_wire='{"result":"private-retained-fixture"}', is_success=1, eval_grade='A',
                evidence_scope=None, executed_at=None, execution_finished_at=None,
                connection_version_id=None, creation_subject_key=None)


def insert(db, row):
    keys=list(row)
    db.execute('INSERT INTO agent_test_reports ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', list(row.values()))


@pytest.fixture
def fixture(tmp_path):
    current, old = tmp_path/'current.db', tmp_path/'original.db'
    scripts=tmp_path/'scripts';scripts.mkdir()
    deleted=[report(i,name) for i,name in enumerate(['Old Alpha','Beta','Existing','No proof','Static only','Ambiguous','Query','Conflict','Explicit','Citation'],1)]
    deleted[1]['created_at']=30
    deleted[8]['content_md']='| **Endpoint URL** | `https://explicit.example/mcp` |'
    deleted[9]['content_md']='Useful source: https://citation.example/mcp'
    kept=[report(100,'Existing','https://existing.example/mcp',created=40),
          report(101,'Beta','https://beta.example/mcp',created=20),
          report(102,'Untouched','https://untouched.example/mcp',created=50)]
    resources=[(11,'a','mcp','Renamed Alpha','https://alpha.example/mcp',1,'healthy','safe'),
               (12,'b','mcp','Beta','https://beta.example/mcp',1,'healthy','safe'),
               (13,'c','mcp','Existing','https://existing.example/mcp',1,'healthy','safe'),
               (15,'e','mcp','Static only','https://static.example/mcp',1,'healthy','safe'),
               (16,'f','mcp','Ambiguous','https://ambiguous.example/mcp',1,'healthy','safe'),
               (116,'f2','mcp','Other','https://ambiguous.example/mcp',1,'healthy','safe'),
               (17,'g','mcp','Query','https://query.example/mcp?scope=other',1,'healthy','safe'),
               (18,'h','mcp','Conflict','https://conflict.example/mcp',1,'healthy','safe'),
               (19,'i','mcp','Explicit','https://explicit.example/mcp',1,'healthy','safe'),
               (20,'j','mcp','Citation','https://citation.example/mcp',1,'healthy','safe')]
    endpoints={1:'alpha',2:'beta',3:'existing',6:'ambiguous',7:'query',8:'conflict'}
    with sqlite3.connect(old) as db:
        db.executescript(SCHEMA)
        for row in deleted:
            if row['id'] in endpoints:
                insert(db,{**row,'agent_url':'https://'+endpoints[row['id']]+'.example/mcp'})
    with sqlite3.connect(current) as db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?)',resources)
        for row in kept:insert(db,row)
        db.execute("INSERT INTO capability_evidence VALUES('existing-evidence',11)")
        install_report_identity_guards(db);install_sqlite_guard(db)
    metadata={key:deleted[4][key] for key in recovery.FIELDS}
    metadata['agent_url']='https://static.example/mcp'
    conflict={key:deleted[7][key] for key in recovery.FIELDS}
    conflict['agent_url']='https://different.example/mcp'
    # Reading source literals must never execute even an obvious side effect.
    (scripts/'seed_fixture_reports.py').write_text('from pathlib import Path\nPath('+repr(str(tmp_path/'executed'))+').write_text("bad")\nREPORTS = '+repr([metadata,conflict]))
    all_rows=sorted(deleted+kept,key=lambda row:row['id'])
    backup=tmp_path/'backup.json';backup.write_text(json.dumps({'format':'report-subject-pruning-backup-v1',
        'reports':all_rows,'reports_sha256':recovery._signature(all_rows),
        'plan':{'delete_ids':[row['id']for row in deleted],'keep_ids':[row['id']for row in kept]}}))
    return dict(backup=backup,source_db=old,db_path=current,scripts_dir=scripts,
                expected_deleted=len(deleted),backup_dir=tmp_path/'private')


def read(path, table='agent_test_reports'):
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')]


def test_dry_run_uses_exact_provenance_without_executing_sources_or_disclosing_content(fixture,capsys):
    files={p:p.read_bytes() for p in (fixture['backup'],fixture['source_db'],fixture['db_path'])}
    result=recovery.restore(**fixture)
    assert result['eligible_restorations']==4 and result['eligible_replacements']==1
    assert result['skipped']['ambiguous_catalog_endpoint']==1
    assert result['skipped']['provider_not_in_current_catalog']==1
    assert result['skipped']['conflicting_original_endpoints']==1
    assert result['skipped']['no_independent_original_endpoint']==2
    assert result['skipped']['newer_report_already_present']==1
    assert not (fixture['scripts_dir'].parent/'executed').exists()
    assert not fixture['backup_dir'].exists()
    assert all(p.read_bytes()==raw for p,raw in files.items())
    args=['--backup',str(fixture['backup']),'--source-db',str(fixture['source_db']),
          '--db',str(fixture['db_path']),'--scripts-dir',str(fixture['scripts_dir']),
          '--expected-deleted','10']
    assert recovery.main(args)==0
    output=capsys.readouterr().out
    for value in ['private-retained-fixture','alpha.example','Old Alpha',str(fixture['db_path'])]:assert value not in output


def test_apply_keeps_latest_identity_guards_original_outcome_and_no_fabricated_execution(fixture):
    source=fixture['source_db'].read_bytes()
    untouched=next(row for row in read(fixture['db_path'])if row['id']==102)
    evidence=read(fixture['db_path'],'capability_evidence')
    resources=read(fixture['db_path'],'resources')
    result=recovery.restore(**fixture,apply=True)
    assert result['restored']==4 and result['replaced_older_reports']==1 and result['reports_after']==6
    rows={row['id']:row for row in read(fixture['db_path'])}
    assert set(rows)=={1,2,5,9,100,102} and rows[102]==untouched
    assert rows[1]['agent_name']=='Renamed Alpha' and rows[1]['resource_id']==11
    assert rows[1]['created_at']==10 and rows[2]['created_at']==30
    assert rows[1]['is_success']==1 and rows[1]['eval_grade']=='A'
    assert rows[1]['output_wire']=='{"result":"private-retained-fixture"}'
    assert '[Retired gateway reference]'in rows[1]['input_wire']
    assert 'agentconcierge.biz/api/gateway/mcp/1'not in rows[1]['input_wire']
    assert rows[1]['content_md'].startswith(recovery.NOTICE)
    for i in [1,2,5,9]:
        assert rows[i]['evidence_scope']=='legacy'
        assert all(rows[i][key]is None for key in recovery.EXECUTION)
        resource=next(r for r in resources if r['id']==rows[i]['resource_id'])
        assert report_subject_matches(rows[i],resource)
        assert rows[i]['creation_subject_key']==subject(None,kind='mcp',agent_url=resource['url'])[0]
    assert fixture['source_db'].read_bytes()==source
    assert read(fixture['db_path'],'resources')==resources
    assert read(fixture['db_path'],'capability_evidence')==evidence
    with sqlite3.connect(fixture['db_path']) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='agent_test_reports'").fetchone()[0]==3
        assert db.execute('SELECT count(*) FROM test_report_subject_claims WHERE report_id IS NULL').fetchone()[0]==0
        with pytest.raises(sqlite3.IntegrityError,match='report_creation_reservation_required'):
            insert(db,report(200,'Renamed Alpha','https://alpha.example/mcp'))
    saved=list(fixture['backup_dir'].glob('*.json'))
    assert len(saved)==1
    assert stat.S_IMODE(saved[0].stat().st_mode)==0o600
    assert stat.S_IMODE(fixture['backup_dir'].stat().st_mode)==0o700
    assert {r['id']for r in json.loads(saved[0].read_text())['reports']}=={100,101,102}
    again=recovery.restore(**fixture,apply=True)
    assert again['restored']==0 and len(list(fixture['backup_dir'].glob('*.json')))==1


def test_bad_backup_counts_and_integrity_are_rejected(fixture):
    with pytest.raises(recovery.RestoreError,match='scope_mismatch'):
        recovery.restore(**{**fixture,'expected_deleted':9})
    b=json.loads(fixture['backup'].read_text());b['reports'][0]['content_md']='changed'
    fixture['backup'].write_text(json.dumps(b))
    with pytest.raises(recovery.RestoreError,match='integrity_mismatch'):recovery.restore(**fixture)


def test_failed_private_backup_rolls_back_without_writing(fixture,monkeypatch):
    before=read(fixture['db_path'])
    def fail(*args,**kwargs):raise OSError('test-backup-failed')
    monkeypatch.setattr(recovery,'_private_backup',fail)
    with pytest.raises(OSError):recovery.restore(**fixture,apply=True)
    assert read(fixture['db_path'])==before
    assert read(fixture['db_path'],'test_report_subject_claims')==[]


def test_retired_writer_fence_prevents_recovery(fixture):
    with sqlite3.connect(fixture['db_path'])as db:db.execute('CREATE TABLE application_source_writer_fence(id INTEGER)')
    with pytest.raises(sqlite3.OperationalError,match='application_source_writer_retired'):
        recovery.restore(**fixture,apply=True)
    assert len(read(fixture['db_path']))==3


def test_reservation_conflict_rolls_back_all_report_writes(fixture):
    with sqlite3.connect(fixture['db_path'])as db:
        db.execute('INSERT INTO test_report_subject_claims VALUES(?,NULL)',(subject(None,kind='mcp',agent_url='https://beta.example/mcp')[0],))
    before=read(fixture['db_path'])
    with pytest.raises(recovery.RestoreError,match='subject_reservation_conflict'):
        recovery.restore(**fixture,apply=True)
    assert read(fixture['db_path'])==before
