"""Independent writer-race, rollback and authenticated creation guard regressions."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from agent_market.gateway.store import Store
from agent_market.report_creation import ReportAlreadyExists
from tests.test_admin_report_creation_guard import _draft, _headers
from tests.test_admin_test_reports_and_workflows import client  # noqa: F401

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def test_two_store_writers_cannot_create_same_subject_with_distinct_slugs(tmp_path):
    path=tmp_path/'independent-writers.sqlite3';stores=[Store(str(path)),Store(str(path))]
    barrier=threading.Barrier(2)
    def create(index):
        barrier.wait(timeout=5)
        try:return 'created',stores[index].create_test_report(_draft(slug='writer-'+str(index)))
        except ReportAlreadyExists as exc:return 'existing',exc.report_id
    try:
        with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(create,range(2)))
        assert sorted(result[0]for result in results)==['created','existing']
        assert results[0][1]==results[1][1]
        assert stores[0].query('SELECT count(*) FROM agent_test_reports')[0][0]==1
        assert stores[0].query('SELECT count(*) FROM test_report_subject_claims')[0][0]==1
        assert stores[0].find_existing_test_report(kind='mcp',agent_url='https://canonical.example/mcp')==results[0][1]
    finally:
        for store in stores:store._db.close()


def test_failed_insert_rolls_back_reservation_and_allows_a_correct_retry(tmp_path):
    store=Store(str(tmp_path/'rollback.sqlite3'))
    try:
        with store.tx()as db:
            db.execute("CREATE TRIGGER refuse_document BEFORE INSERT ON agent_test_reports BEGIN SELECT RAISE(ABORT,'isolated insertion refusal'); END")
        with pytest.raises(sqlite3.IntegrityError):store.create_test_report(_draft())
        assert store.query('SELECT count(*) FROM test_report_subject_claims')[0][0]==0
        assert store.find_existing_test_report(kind='mcp',agent_url='https://canonical.example/mcp')is None
        with store.tx()as db:db.execute('DROP TRIGGER refuse_document')
        identity=store.create_test_report(_draft())
        assert store.find_existing_test_report(kind='mcp',agent_url='https://canonical.example/mcp')==identity
    finally:store._db.close()


def test_complete_query_and_protocol_are_not_broadened_to_a_shared_host(tmp_path):
    store=Store(str(tmp_path/'subjects.sqlite3'))
    try:
        one=store.create_test_report(_draft(agent_url='https://canonical.example/mcp?tenant=one'))
        two=store.create_test_report(_draft(slug='another-subject',agent_url='https://canonical.example/mcp?tenant=two'))
        three=store.create_test_report(_draft(slug='another-protocol',kind='a2a',agent_url='https://canonical.example/mcp?tenant=one'))
        assert len({one,two,three})==3
        with pytest.raises(ReportAlreadyExists):
            store.create_test_report(_draft(slug='same-canonical-endpoint',agent_url='https://CANONICAL.example:443/mcp?tenant=one'))
        assert store.find_existing_test_report(kind='mcp',agent_url='https://canonical.example/mcp?tenant=two')==two
    finally:store._db.close()


@pytest.mark.parametrize('endpoint',[
    'https://user:private-value@canonical.example/mcp',
    'https://canonical.example:invalid/mcp',
    'https://canonical.example/mcp#private-value',
    'file:///private-value',
])
def test_invalid_subject_errors_do_not_echo_endpoint_or_credentials(client,endpoint):
    headers=_headers(client)
    check=client.get('/admin/api/test-reports/existing',params={'kind':'mcp','agent_url':endpoint},headers=headers)
    create=client.post('/admin/api/test-reports',json=_draft(agent_url=endpoint),headers=headers)
    assert check.status_code==create.status_code==400
    for response in(check,create):
        assert 'private-value'not in response.text and 'traceback'not in response.text.lower()
        assert endpoint not in response.text


def test_subject_lookup_and_creation_reject_missing_dashboard_marker(client):
    headers=_headers(client);headers.pop('X-Dashboard')
    assert client.get('/admin/api/test-reports/existing',params={'kind':'mcp','agent_url':'https://canonical.example/mcp'},headers=headers).status_code==403
    assert client.post('/admin/api/test-reports',json=_draft(),headers=headers).status_code==403


def test_untrusted_sql_text_remains_a_literal_subject_and_report(client):
    headers=_headers(client)
    endpoint="https://canonical.example/mcp?literal=';DROP_TABLE_resources;--"
    result=client.post('/admin/api/test-reports',json=_draft(agent_url=endpoint,title="Literal ' SQL text"),headers=headers)
    assert result.status_code==200
    existing=client.get('/admin/api/test-reports/existing',params={'kind':'mcp','agent_url':endpoint},headers=headers)
    assert existing.status_code==200 and existing.json()['existing_report_id']==result.json()['id']
    assert client.get('/admin/api/agents',headers=headers).status_code==200
