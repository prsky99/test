"""Collector entrypoints retain their pre-work snapshot through real fake HTTP.

All sources and responses are synthetic. No provider, production database,
bootstrap credential or project server is used.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time

import httpx
import pytest

from agent_market.collector.a2a import AgentProber
from agent_market.collector.auth_discovery import AuthDiscoverer
from agent_market.collector.capabilities import CapabilityProber
from agent_market.collector.health import CheckResult, HealthChecker
from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
from agent_market.gateway.store import Store


def registration(kind='mcp', **changes):
    return {'key': 'synthetic:collector-guard:' + kind, 'source': 'synthetic-collector', 'kind': kind,
        'url': 'https://old.example/' + kind, 'name': 'Synthetic reference reader',
        'description': 'Research documentation search', 'category': 'research', 'networks': [],
        'price_usdc': 0, 'details': {}} | changes


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'collector-fixture.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(ADMIN_SCHEMA)
        create_admin_user(db, 'sadmin', 'Synthetic-collector-guard-password-42', 'Synthetic administrator', 'superadmin')
    value = Store(str(path))
    try: yield value
    finally: value._db.close()


def add(store, kind='mcp'):
    rid = store.upsert_resource(registration(kind), now=10)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
    return rid


def rebind(store, kind='mcp'):
    return store.upsert_resource(registration(kind, url='https://new.example/' + kind), now=20)


def tools(name='search_reference'):
    return [{'name': name, 'description': 'Search public documentation references',
        'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
        'annotations': {'readOnlyHint': True, 'destructiveHint': False}}]


def mcp_response(request, *, tool_name='search_reference'):
    body = json.loads(request.content or b'{}')
    method = body.get('method')
    result = ({'protocolVersion': '2026-07-28', 'serverInfo': {'name': 'synthetic', 'version': '1'}}
              if method in ('server/discover', 'initialize') else {'tools': tools(tool_name)}
              if method == 'tools/list' else {'content': [{'type': 'text', 'text': 'Synthetic reference result'}]})
    return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body.get('id', 1), 'result': result})


def card():
    return {'name': 'Synthetic documentation agent', 'description': 'Documentation reference lookup',
        'url': 'https://old.example/a2a', 'protocolVersion': '0.3.0', 'preferredTransport': 'JSONRPC',
        'capabilities': {}, 'defaultInputModes': ['text/plain'], 'defaultOutputModes': ['text/plain'],
        'skills': [{'id': 'reference', 'name': 'Reference', 'description': 'Search documentation reference',
                    'tags': ['docs'], 'examples': ['What documentation is available?']}],
        'additionalInterfaces': [{'transport': 'MCP', 'url': 'https://discovered.example/mcp'}]}


def a2a_response(request):
    if request.method == 'GET': return httpx.Response(200, json=card())
    body = json.loads(request.content or b'{}')
    if body.get('method') in ('tasks/get', 'GetTask'):
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body.get('id', 1),
            'error': {'code': -32001, 'message': 'Task not found'}})
    return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body.get('id', 1),
        'result': {'kind': 'message', 'role': 'agent', 'parts': [{'kind': 'text', 'text': 'Synthetic documentation answer'}], 'messageId': 'synthetic'}})


def assert_no_probe_result(store, rid):
    row = store.resource(rid)
    assert row['cap_checked_at'] is None and row['usage_tools'] is None and row['eval_at'] is None
    assert row['auth_checked_at'] is None and row['trial_info'] is None
    assert not store.query('SELECT 1 FROM capability_evidence')
    return row


def test_health_actual_http_rebinding_discards_result_and_reports_stale(store):
    rid = add(store)
    calls = []
    def response(request):
        calls.append(str(request.url))
        rebind(store)
        return mcp_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        state = HealthChecker(store, http=client, allow_private=True).check_and_record(store.resource(rid))
    assert calls == ['https://old.example/mcp']
    assert state['stale'] is True and state['accepted'] is False and state['status'] is None
    assert store.resource(rid)['last_check_at'] is None and not store.health_history(rid)


def test_stale_due_snapshot_is_rejected_before_any_external_call(store):
    rid = add(store)
    original = store.resource(rid)
    rebind(store)
    def forbidden(_request): pytest.fail('No HTTP for an already stale input snapshot')
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        result = HealthChecker(store, http=client, allow_private=True).check_and_record(original)
    assert result['stale'] is True and result['accepted'] is False


def test_local_health_postpone_cannot_overwrite_changed_target_schedule(store, monkeypatch):
    rid = add(store)
    checker = HealthChecker(store, allow_private=True)
    def delayed(_resource):
        rebind(store)
        store.postpone([rid], 1234567890)
        return CheckResult('fail', error='local', local=True)
    monkeypatch.setattr(checker, 'check', delayed)
    result = checker.check_and_record(store.resource(rid))
    assert result['stale'] is True and result['accepted'] is False
    assert store.resource(rid)['next_check_at'] == 1234567890 and not store.health_history(rid)


def test_local_health_postpone_does_not_claim_an_accepted_health_result(store, monkeypatch):
    rid = add(store)
    checker = HealthChecker(store, allow_private=True)
    monkeypatch.setattr(checker, 'check', lambda _resource: CheckResult('fail', error='local', local=True))
    state = checker.check_and_record(store.resource(rid))
    assert state['postponed'] is True and state['accepted'] is False and not state.get('stale')
    assert store.resource(rid)['next_check_at'] > time.time() and not store.health_history(rid)


def test_health_batch_does_not_count_stale_success(store):
    rid = add(store)
    def response(request):
        rebind(store)
        return mcp_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = HealthChecker(store, http=client, allow_private=True, per_host_delay=0).run_due()
    assert result['checked'] == result['stale'] == 1 and result['accepted'] == 0
    assert result.get('healthy', 0) == result.get('recovered', 0) == 0
    assert store.resource(rid)['last_check_at'] is None and not store.health_history(rid)


def test_retired_scavenge_rebinding_does_not_record_failure_or_delay(store, monkeypatch):
    rid = add(store)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired',consecutive_failures=4,failing_since=1,next_check_at=0 WHERE id=?", (rid,))
    checker = HealthChecker(store, allow_private=True)
    def delayed(_resource, _http):
        rebind(store)
        store.postpone([rid], 1234567890)
        return False, 500, 'synthetic failure'
    monkeypatch.setattr(checker, 'probe_lightweight', delayed)
    result = checker.scavenge_retired()
    assert result['scavenged'] == result['stale'] == 1 and result['accepted'] == result['still_dead'] == result['revived'] == 0
    assert store.resource(rid)['next_check_at'] == 1234567890 and not store.health_history(rid)


def test_mcp_probe_rebinding_prevents_usage_evaluation_and_execution_evidence(store):
    rid = add(store)
    methods = []
    def response(request):
        method = json.loads(request.content).get('method')
        methods.append(method)
        if len(methods) == 1: rebind(store)
        return mcp_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = CapabilityProber(store, http=client, allow_private=True, per_host_delay=0).run_due()
    assert methods[:2] == ['server/discover', 'tools/list']
    assert result['stale'] == 1 and result['accepted'] == result.get('ok', 0) == result.get('trial_ok', 0) == 0
    assert_no_probe_result(store, rid)


def test_mcp_accepted_bundle_records_tools_grade_and_real_fake_trial_together(store):
    rid = add(store)
    methods = []
    def response(request):
        methods.append(json.loads(request.content).get('method'))
        return mcp_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = CapabilityProber(store, http=client, allow_private=True, per_host_delay=0).run_due()
    row = store.resource(rid)
    assert result['accepted'] == result['ok'] == 1 and result['stale'] == 0
    assert row['cap_checked_at'] and row['usage_full_tools'] and row['eval_at']
    assert 'tools/call' in methods and row['trial_ok'] == 1
    assert len(store.query("SELECT 1 FROM capability_evidence WHERE scope='execution' AND outcome='succeeded'")) == 1


def test_nul_in_provider_tool_metadata_is_only_normalized_in_search_projection():
    from agent_market.gateway.store import extract_tool_search_text
    original = [{'name': 'reference\0search', 'description': 'Public\0documentation',
                 'tags': ['battery\0research', 'science']}]
    encoded = json.dumps(original)
    assert extract_tool_search_text(encoded) == 'reference search Public documentation battery research science'
    assert json.loads(encoded) == original


def test_newer_started_mcp_probe_wins_when_older_response_arrives_last(store):
    rid = add(store)
    entered, release = threading.Event(), threading.Event()
    def old_response(request):
        if json.loads(request.content).get('method') == 'tools/list':
            entered.set()
            assert release.wait(5)
        return mcp_response(request, tool_name='old_reference')
    with httpx.Client(transport=httpx.MockTransport(old_response)) as old_client, httpx.Client(
            transport=httpx.MockTransport(lambda request: mcp_response(request, tool_name='new_reference'))) as new_client:
        first = CapabilityProber(store, http=old_client, allow_private=True, per_host_delay=0, trials=False)
        second = CapabilityProber(store, http=new_client, allow_private=True, per_host_delay=0, trials=False)
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(first.run_due)
            try:
                assert entered.wait(5)
                newer = second.run_due()
            finally: release.set()
            older = old.result(timeout=5)
    assert newer['accepted'] == 1 and newer['stale'] == 0
    assert older['stale'] == 1 and older['accepted'] == older.get('ok', 0) == 0
    assert json.loads(store.resource(rid)['usage_full_tools'])[0]['name'] == 'new_reference'


def test_a2a_stale_card_cannot_register_related_mcp_or_auth_or_grade(store):
    rid = add(store, 'a2a')
    calls = []
    def response(request):
        calls.append(str(request.url))
        if len(calls) == 1: rebind(store, 'a2a')
        return a2a_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = AgentProber(store, http=client, allow_private=True, per_host_delay=0).run_due()
    assert calls and result['stale'] == 1 and result['accepted'] == result.get('ok', 0) == 0
    assert_no_probe_result(store, rid)
    assert not store.query("SELECT 1 FROM resources WHERE source='a2a-card'")


def test_a2a_accepted_bundle_can_change_its_own_category_auth_and_usage(store):
    rid = add(store, 'a2a')
    with httpx.Client(transport=httpx.MockTransport(a2a_response)) as client:
        result = AgentProber(store, http=client, allow_private=True, per_host_delay=0).run_due()
    row = store.resource(rid)
    assert result['accepted'] == result['ok'] == 1 and result['stale'] == 0
    assert row['cap_checked_at'] and row['auth_checked_at'] and row['usage_tools'] and row['eval_at']
    assert len(store.query("SELECT 1 FROM resources WHERE source='a2a-card' AND kind='mcp'")) == 1


def test_auth_discovery_rebinding_does_not_attach_old_method_to_new_endpoint(store):
    rid = add(store)
    store.set_auth_observed(rid, True)
    calls = []
    def response(request):
        calls.append(str(request.url))
        rebind(store)
        return mcp_response(request)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = AuthDiscoverer(store, http=client, allow_private=True, per_host_delay=0).run_due()
    assert calls == ['https://old.example/mcp']
    assert result['stale'] == 1 and result['accepted'] == result.get('none', 0) == 0
    assert store.resource(rid)['auth_checked_at'] is None and store.resource(rid)['auth_method'] is None


def test_static_evaluation_rebinding_is_not_counted_as_accepted(store, monkeypatch):
    from agent_market.collector import evaluation
    rid = add(store)
    store.set_auth_observed(rid, True)
    original = evaluation.evaluate_static
    def calculate(resource):
        rebind(store)
        return original(resource)
    monkeypatch.setattr(evaluation, 'evaluate_static', calculate)
    assert CapabilityProber(store).evaluate_static_due() == 0
    assert store.resource(rid)['eval_at'] is None


@pytest.mark.parametrize('kind', ['mcp', 'a2a'])
def test_late_evaluation_sql_failure_rolls_back_whole_collector_bundle(store, monkeypatch, kind):
    rid = add(store, kind)
    before = store.resource(rid)
    original = store.record_evaluation
    reached = []
    def accepted_then_failed(resource_id, value):
        original(resource_id, value)
        assert store.resource(resource_id)['eval_at'] is not None
        reached.append(resource_id)
        raise RuntimeError('Synthetic failure after accepted evaluation SQL')
    monkeypatch.setattr(store, 'record_evaluation', accepted_then_failed)
    response = mcp_response if kind == 'mcp' else a2a_response
    prober_type = CapabilityProber if kind == 'mcp' else AgentProber
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = prober_type(store, http=client, allow_private=True, per_host_delay=0).run_due()
    assert reached == [rid] and result['record_error'] == 1
    assert result['accepted'] == result.get('ok', 0) == result.get('trial_ok', 0) == 0
    current = assert_no_probe_result(store, rid)
    assert current == before
    assert not store.query("SELECT 1 FROM resources WHERE source='a2a-card'")


def test_pure_evaluation_failure_preserves_survey_without_refreshing_previous_grade(store, monkeypatch, caplog):
    from agent_market.capability_registry import Registry
    from agent_market.collector import evaluation
    rid = add(store)
    store.record_evaluation(rid, {'score': 91, 'grade': 'A', 'security': 'ok',
        'coverage': 'synthetic-fixture', 'at': time.time()-10})
    previous = store.resource(rid)
    registry = Registry(store)
    version = registry.current(previous)
    registry.record(version, scope='execution', outcome='unknown', started=10, finished=11,
                    dataset='synthetic-expired-fixture')
    history = [tuple(row) for row in store.query('SELECT * FROM capability_evidence ORDER BY id')]
    assert len(history) == 1
    with store.tx() as db:
        db.execute('INSERT OR REPLACE INTO capability_eligibility VALUES (?,?,?,?,?)',
                   (rid, version['id'], 'succeeded', time.time(), time.time()+60))
    assert len(store.query('SELECT 1 FROM capability_eligibility WHERE resource_id=?', (rid,))) == 1
    def unavailable(*_args, **_kwargs):
        raise RuntimeError('synthetic-private-calculation-detail')
    monkeypatch.setattr(evaluation, 'evaluate', unavailable)
    with httpx.Client(transport=httpx.MockTransport(mcp_response)) as client:
        result = CapabilityProber(store, http=client, allow_private=True, per_host_delay=0, trials=False).run_due()
    current = store.resource(rid)
    assert result['accepted'] == result['ok'] == result['evaluation_unavailable'] == 1
    assert result['stale'] == result.get('record_error', 0) == result.get('quarantined', 0) == 0
    assert not any(key.startswith('grade_') for key in result)
    assert current['cap_checked_at'] and current['usage_guide'] and current['usage_full_tools']
    assert current['eval_at'] is None
    assert current['eval_security'] == 'review'
    assert all(current[key] == previous[key] for key in ('eval_grade', 'eval_score', 'eval_info'))
    assert [tuple(row) for row in store.query('SELECT * FROM capability_evidence ORDER BY id')] == history
    assert not store.query('SELECT 1 FROM capability_eligibility WHERE resource_id=?', (rid,))
    assert 'capability evaluation calculation unavailable' in caplog.text
    assert 'synthetic-private-calculation-detail' not in caplog.text
