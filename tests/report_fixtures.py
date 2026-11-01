"""Measured report fixtures backed by actual isolated registry records."""
from datetime import datetime, timezone
import json
import sqlite3
import time
import uuid

from agent_market.capability_registry import Registry
from agent_market.report_creation import ReportAlreadyExists


def legacy_report_fixture(store, data):
    """Seed preserved pre-guard history only in an isolated SQLite test store."""
    if not isinstance(store._db, sqlite3.Connection):
        raise TypeError('Historical fixture seeding requires an isolated SQLite store.')
    resource = store.resource(data.get('resource_id')) if data.get('resource_id') else {}
    resource = resource or {}
    now = time.time()
    report = {'resource_id':None,'title':'Historical fixture','slug':'history-'+uuid.uuid4().hex,
        'kind':resource.get('kind','mcp'),'source':'isolated-history-fixture',
        'agent_name':resource.get('name',''),'agent_url':resource.get('url',''),
        'category':'other','eval_grade':None,'eval_score':None,'status_code':200,
        'latency_ms':0.0,'is_success':1,'test_method':'','tool_name':None,
        'input_wire':{},'output_wire':{},'summary':'','content_md':'','pros':[],'cons':[],
        'workflow_recommendation':'','tags':'','author':'Historical fixture',
        'created_at':now,'updated_at':now,'executed_at':None,'execution_finished_at':None,
        'connection_version_id':None,'evidence_scope':'legacy','creation_subject_key':None}
    report.update({key:value for key,value in data.items() if key in report and key != 'creation_subject_key'})
    for field in ('input_wire','output_wire','pros','cons'):
        report[field] = json.dumps(report[field])
    with store.tx() as db:
        guard = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='report_creation_insert'").fetchone()
        db.execute('DROP TRIGGER IF EXISTS report_creation_insert')
        try:
            columns = ','.join(report)
            cursor = db.execute('INSERT INTO agent_test_reports ('+columns+') VALUES ('+
                                ','.join('?' for _ in report)+')',tuple(report.values()))
            return cursor.lastrowid
        finally:
            if guard:db.execute(guard['sql'])


def execution_report(store, rid, at, **fields):
    if isinstance(at, str):
        at = datetime.fromisoformat(at).replace(tzinfo=timezone.utc).timestamp()
    resource = store.resource(rid)
    version = Registry(store).current(resource)
    success = fields.get('is_success', 1)
    Registry(store).record(version, scope='execution', outcome='succeeded' if success else 'failed',
                           started=at, finished=at)
    report = {'resource_id': rid, 'kind': resource['kind'], 'agent_name': resource['name'],
              'agent_url': resource['url'], 'executed_at': at, 'execution_finished_at': at,
              'connection_version_id': version['id'], 'evidence_scope': 'execution',
              'is_success': success, **fields}
    try:return store.create_test_report(report)
    except ReportAlreadyExists:return legacy_report_fixture(store,report)
