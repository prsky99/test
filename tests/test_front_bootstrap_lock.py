"""Bounded child-process regressions for native frontend bootstrap cache locks."""

import os
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_managed_agent_gateway import managed  # noqa: F401


CHILD = r'''
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
from agent_market.gateway.store import Store
import agent_market.concierge.front as frontend
from agent_market.capability_registry import Registry

frontend.RedisHub.get_instance = staticmethod(lambda: SimpleNamespace(is_available=lambda: False))

def fixture(path, suffix):
    with sqlite3.connect(path) as db:
        db.executescript(ADMIN_SCHEMA)
        create_admin_user(db, 'sadmin', 'Synthetic-bootstrap-lock-password-42', 'Synthetic fixture', 'superadmin')
    store = Store(str(path))
    rid = store.upsert_resource({
        'key': 'synthetic:bootstrap:' + suffix, 'source': 'synthetic', 'kind': 'mcp',
        'url': 'https://bootstrap-' + suffix + '.example/mcp',
        'name': 'Synthetic bootstrap ' + suffix, 'description': 'Search synthetic public documents',
        'category': 'research', 'networks': [], 'details': {},
    }, now=10)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy',eval_security='ok',auth_observed=0 WHERE id=?", (rid,))
    tools=[{'name':'search_documents','description':'Search synthetic public documents',
            'inputSchema':{'type':'object','properties':{}}}]
    store.record_usage(rid,tools=tools,digest='synthetic-bootstrap-schema',guide={'tools':tools},changes=None,trial=None)
    at=time.time()
    Registry(store).record(Registry(store).current(rid),scope='execution',outcome='succeeded',started=at,finished=at)
    return store

def page(client):
    print('request-started', flush=True)
    response = client.get('/', headers={'accept': 'text/html'})
    assert response.status_code == 200
    match = re.search(r'<script[^>]*id="appBootstrapData"[^>]*>(.*?)</script>', response.text, re.S)
    assert match
    data = json.loads(match.group(1))
    assert type(data) is dict and set(('overview', 'explore', 'insights', 'testbench_examples')) <= data.keys()
    assert "script-src 'nonce-" in response.headers['content-security-policy']
    return data

with tempfile.TemporaryDirectory(prefix='a2a-bootstrap-lock-') as directory:
    stores = []
    try:
        first = fixture(Path(directory) / 'first.sqlite3', 'alpha')
        stores.append(first)
        with TestClient(frontend.create_front_app(frontend.Front(first))) as client:
            initial = page(client)
            assert initial['explore']['items'][0]['name'] == 'Synthetic bootstrap alpha'
            if sys.argv[1] == 'expired':
                with frontend._bootstrap_snapshot_cache['lock']:
                    frontend._bootstrap_snapshot_cache['at'] = time.time() - 301
                    frontend._bootstrap_snapshot_cache['revalidating'] = True
                refreshed = page(client)
                assert refreshed['explore']['items'][0]['name'] == 'Synthetic bootstrap alpha'
                assert frontend._bootstrap_snapshot_cache['revalidating'] is False
        if sys.argv[1] == 'cross_store':
            second = fixture(Path(directory) / 'second.sqlite3', 'beta')
            stores.append(second)
            with TestClient(frontend.create_front_app(frontend.Front(second))) as client:
                data = page(client)
                assert data['explore']['items'][0]['name'] == 'Synthetic bootstrap beta'
                assert frontend._bootstrap_snapshot_cache['store_id'] == id(second)
        print(json.dumps({'ok': True, 'scenario': sys.argv[1]}), flush=True)
    finally:
        for store in stores:
            store._db.close()
'''


@pytest.mark.parametrize('scenario', ['cold', 'cross_store', 'expired'])
def test_native_html_bootstrap_completes_in_bounded_child(scenario):
    env = {key: value for key, value in os.environ.items()
           if key not in ('AGENT_UPDATES_KEY', 'ADMIN_BOOTSTRAP_PASSWORD', 'ADMIN_TOKEN', 'DEPLOYMENT_MODE')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-B', '-c', CHILD, scenario],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"ok": true' in result.stdout and '"scenario": "' + scenario + '"' in result.stdout


@pytest.fixture
def fresh_managed(monkeypatch, request):
    import agent_market.concierge.front as frontend
    class UnavailableCache:
        def is_available(self):
            return False
    monkeypatch.setattr(frontend.RedisHub, 'get_instance', staticmethod(UnavailableCache))
    return request.getfixturevalue('managed')


def _cards(value, rid):
    if isinstance(value, list):
        return [card for child in value for card in _cards(child, rid)]
    if isinstance(value, dict):
        own = [value] if value.get('id') == rid and 'agent_ref' in value else []
        return own + [card for child in value.values() for card in _cards(child, rid)]
    return []


def _success(world):
    import agent_market.concierge.front as frontend
    store, _, client, _, rid, _, _ = world
    frontend.clear_front_caches()
    assert client.post('/api/test/execute', json={
        'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'},
    }).json()['execution_succeeded']
    return store, rid


@pytest.mark.parametrize('surface', ['explore', 'insights'])
@pytest.mark.parametrize('cache_kind', ['memory', 'redis'])
def test_warm_catalog_cache_rechecks_actual_failed_evidence(fresh_managed, monkeypatch, surface, cache_kind):
    import agent_market.concierge.front as frontend
    from agent_market.capability_registry import Registry
    store, rid = _success(fresh_managed)
    calls = fresh_managed[5]
    read = (lambda: frontend.get_front_explore(store, '', None, None, True, False)) if surface == 'explore' else lambda: frontend.get_front_insights(store)
    first = read()
    assert _cards(first, rid) and all(card['connection_readiness']['verified_callable'] for card in _cards(first, rid))
    if cache_kind == 'redis':
        frontend._front_explore_cache.clear()
        frontend._front_insights_cache.update(at=0.0, data=None, store_id=None)
        class SharedCache:
            def is_available(self):
                return True

            def get_json(self, key):
                return copy.deepcopy(first)
        monkeypatch.setattr(frontend.RedisHub, 'get_instance', staticmethod(SharedCache))
    registry = Registry(store)
    now = time.time()
    registry.record(registry.current(rid), scope='execution', outcome='failed', started=now, finished=now)
    before_calls = len(calls)
    second = read()
    if surface == 'explore':
        assert not _cards(second,rid) and second['total'] == 0
    else:
        assert _cards(second, rid) and all(not card['connection_readiness']['verified_callable'] for card in _cards(second, rid))
        assert all(card['connection_readiness']['reason'] == 'latest_failure' for card in _cards(second, rid))
    assert all(card['connection_readiness']['verified_callable'] for card in _cards(first, rid))
    assert len(calls) == before_calls


@pytest.mark.parametrize('surface', ['dict', 'json', 'html'])
def test_warm_bootstrap_and_html_never_reuse_recorded_success(fresh_managed, surface):
    from agent_market.capability_registry import Registry
    store, rid = _success(fresh_managed)
    front, client, calls = fresh_managed[1], fresh_managed[2], fresh_managed[5]
    first = front.bootstrap_snapshot()
    assert any(card['connection_readiness']['verified_callable'] for card in _cards(first, rid))
    registry = Registry(store)
    now = time.time()
    registry.record(registry.current(rid), scope='execution', outcome='failed', started=now, finished=now)
    before_calls = len(calls)
    if surface == 'dict':
        second = front.bootstrap_snapshot()
    elif surface == 'json':
        second = json.loads(front.bootstrap_snapshot_json())
    else:
        response = client.get('/', headers={'accept': 'text/html'})
        assert response.status_code == 200
        match = re.search(r'<script[^>]*id="appBootstrapData"[^>]*>(.*?)</script>', response.text, re.S)
        assert match
        second = json.loads(match.group(1))
    assert _cards(second, rid) and all(not card['connection_readiness']['verified_callable'] for card in _cards(second, rid))
    assert len(calls) == before_calls


@pytest.mark.parametrize('change', ['expiry', 'invoke_pause'])
def test_warm_bootstrap_checks_time_and_authority_without_new_failure(fresh_managed, change):
    from agent_market.capability_registry import Registry
    store, rid = _success(fresh_managed)
    front = fresh_managed[1]
    assert any(card['connection_readiness']['verified_callable'] for card in _cards(front.bootstrap_snapshot(), rid))
    version = Registry(store).current(rid)
    with store.tx() as db:
        if change == 'expiry':
            db.execute('UPDATE capability_evidence SET expires=? WHERE version_id=?', (time.time()-1, version['id']))
        else:
            db.execute('UPDATE execution_controls SET invoke_enabled=0 WHERE id=1')
    cards = _cards(json.loads(front.bootstrap_snapshot_json()), rid)
    assert cards and all(not card['connection_readiness']['verified_callable'] for card in cards)


def test_deleted_cached_resource_clears_all_contract_verification_flags(fresh_managed):
    import agent_market.concierge.front as frontend
    store, rid = _success(fresh_managed)
    resource = fresh_managed[2].get(f'/api/agents/{rid}').json()['agent']
    resource['capability_contracts'] = [{'id': 'docs.search.v1', 'verified': True}]
    with store.tx() as db:
        db.execute('DELETE FROM resources WHERE id=?', (rid,))
    result = frontend.refresh_connection_states(store, resource)
    assert result['connection_readiness']['verified_callable'] is False
    assert result['connection_readiness']['verified_at'] is None
    assert result['capability_contracts'] == [{'id': 'docs.search.v1', 'verified': False}]
    assert resource['capability_contracts'][0]['verified'] is True


def test_warm_bootstrap_json_escapes_markup_once_and_preserves_decoded_text(fresh_managed, monkeypatch):
    import agent_market.concierge.front as frontend
    front = fresh_managed[1]
    payload = {'note': 'Version A < Version B; <script>untrusted text</script>'}
    for key, value in {'at': time.time(), 'store_id': id(front.store), 'data': payload,
                       'json': json.dumps(payload), 'revalidating': False}.items():
        monkeypatch.setitem(frontend._bootstrap_snapshot_cache, key, value)
    encoded = front.bootstrap_snapshot_json()
    assert '<' not in encoded and r'\u003c' in encoded
    assert json.loads(encoded) == payload
