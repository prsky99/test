"""Current catalog alignment and optional diagnostic failure containment."""
import sqlite3
import time
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.capability_registry import Registry
from agent_market.concierge.pearl_view import _catalog_status
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store

HEADERS = {'X-Dashboard': '1', 'Authorization': 'Bearer synthetic-admin-test'}


@pytest.fixture
def aligned(tmp_path):
    store = Store(str(tmp_path / 'isolated.sqlite3'))
    for i, (kind, status, active) in enumerate((('a2a', 'healthy', 1), ('mcp', 'retired', 1),
            ('x402', 'unknown', 1), ('a2a', 'healthy', 0))):
        identity = store.upsert_resource({'key': 'alignment-'+str(i), 'kind': kind, 'source': 'fixture',
            'url': 'https://fixture-'+str(i)+'.example/agent', 'name': 'Fixture '+str(i),
            'description': 'Public fixture', 'category': 'docs_knowledge'})
        with store.tx() as db:
            db.execute('UPDATE resources SET active=?,health_status=?,last_check_at=?,trial_ok=1 WHERE id=?',
                       (active, status, None if i == 2 else time.time(), identity))
    registry = Registry(store)
    version = registry.current(1)
    now = time.time()
    for scope, outcome, age in (('execution', 'succeeded', 60), ('execution', 'unknown', 120),
                                ('transport', 'succeeded', 60), ('execution', 'succeeded', 90000)):
        registry.record(version, scope=scope, outcome=outcome, started=now-age-1, finished=now-age)
    app = FastAPI()
    app.include_router(dashboard_router(store, store._path, 'synthetic-admin-test', None,
                                      ssl_manager=Mock(get_status=lambda: {})))
    from agent_market.gateway import admin_auth
    with store.tx() as db:
        user = admin_auth.create_admin_user(db, 'alignment-fixture', 'Alignment-fixture-password', 'Fixture', 'superadmin')
        token = admin_auth.create_session(db, user['id'], user['username'], user['role'], user['name'])
    HEADERS['Authorization'] = 'Bearer ' + token
    with TestClient(app) as client:
        yield store, client
    store._db.close()


def test_overview_uses_current_public_catalog_and_execution_contract(aligned):
    store, client = aligned
    response = client.get('/admin/api/overview', headers=HEADERS)
    assert response.status_code == 200
    actual = response.json()['public_catalog']
    public = _catalog_status(store)
    for field in ('cataloged', 'reachable', 'with_status_check', 'by_protocol', 'categories'):
        assert actual[field] == public[field]
    assert actual['cataloged'] == 3 and actual['reachable'] == 1
    assert actual['with_status_check'] == 2
    evidence = actual['execution_24h']
    assert evidence['completed'] == 2 and evidence['succeeded'] == 1
    assert evidence['unknown'] == 1 and evidence['successful_resources'] == 1
    assert 'no-store' in response.headers['cache-control']


def test_optional_vector_timeout_cannot_abort_other_dashboard_data(aligned, monkeypatch):
    store, client = aligned
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic private database diagnostic')
    monkeypatch.setattr(store, 'vec_stats', unavailable)
    response = client.get('/admin/api/overview', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['public_catalog']['cataloged'] == 3
    assert response.json()['rag']['available'] is False
    assert response.json()['rag']['pct'] is None
    assert 'private database diagnostic' not in response.text
    response = client.get('/admin/api/rag/stats', headers=HEADERS)
    assert response.status_code == 503 and response.headers['retry-after'] == '5'
    assert 'private database diagnostic' not in response.text
    assert client.get('/admin/api/agents', headers=HEADERS).status_code == 200


def test_vector_projection_is_cached_and_truthful_about_storage(aligned, monkeypatch):
    store, client = aligned
    original = store.vec_stats
    calls = []
    def observed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, 'vec_stats', observed)
    assert client.get('/admin/api/overview', headers=HEADERS).status_code == 200
    stats = client.get('/admin/api/rag/stats', headers=HEADERS).json()
    assert len(calls) == 1 and stats['available'] is True
    assert stats['_cache']['status'] == 'hit'
    assert stats['engine'].startswith('sqlite-vec')
    assert 'Apple Silicon' not in stats['engine']


def test_overview_metrics_are_not_disclosed_without_authorization(aligned):
    _, client = aligned
    assert client.get('/admin/api/overview').status_code == 403
    response = client.get('/admin/api/overview', headers={**HEADERS, 'Origin': 'https://outside.example'})
    assert response.status_code == 403
