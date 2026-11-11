"""A slow catalog cannot block HTML or create unbounded background work."""
import json
import re
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent_market.concierge.bootstrap_delivery import HtmlBootstrap, EMPTY
from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store


def test_slow_snapshot_is_single_flight_and_never_returned_after_completion():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def build():
        calls.append(1)
        entered.set()
        release.wait(3)
        return json.dumps(dict(EMPTY, overview={'fresh': len(calls)}))
    delivery = HtmlBootstrap(SimpleNamespace(bootstrap_snapshot_json=build))
    try:
        started = time.monotonic()
        assert json.loads(delivery.read(.02)) == EMPTY
        assert time.monotonic() - started < .5 and entered.is_set()
        for _ in range(4):
            assert json.loads(delivery.read(0)) == EMPTY
        assert len(calls) == 1
    finally:
        release.set()
        assert delivery.job['done'].wait(3)
    # Reopening a page must recompute current authority, rather than reuse a
    # completed job's successful connection state.
    assert json.loads(delivery.read())['overview']['fresh'] == 2


def test_background_capacity_has_no_waiting_queue():
    release = threading.Event()
    calls = []
    def build():
        calls.append(1)
        release.wait(3)
        return '{}'
    deliveries = [HtmlBootstrap(SimpleNamespace(bootstrap_snapshot_json=build)) for _ in range(5)]
    try:
        for delivery in deliveries:
            assert json.loads(delivery.read(0)) == EMPTY
        assert len(calls) <= 2
        assert sum(d.job is not None for d in deliveries) == 2
    finally:
        release.set()
        for delivery in deliveries:
            if delivery.job:
                assert delivery.job['done'].wait(3)


def test_failed_or_large_snapshot_uses_existing_hydration_APIs():
    def fail():
        raise ValueError('private diagnostic must not reach the page')
    delivery = HtmlBootstrap(SimpleNamespace(bootstrap_snapshot_json=fail))
    assert json.loads(delivery.read()) == EMPTY
    delivery = HtmlBootstrap(SimpleNamespace(bootstrap_snapshot_json=lambda:json.dumps(
        dict(EMPTY, explore={'items': ['x' * 40000]}))))
    assert json.loads(delivery.read()) == EMPTY


def test_html_does_not_wait_for_welcome_counts_or_catalog(tmp_path, monkeypatch):
    store = Store(str(tmp_path/'isolated.sqlite3'))
    front = Front(store)
    entered, release = threading.Event(), threading.Event()
    def build():
        entered.set()
        release.wait(3)
        return '{}'
    monkeypatch.setattr(front, 'bootstrap_snapshot_json', build)
    monkeypatch.setattr(front, 'welcome', lambda *_: (_ for _ in ()).throw(
        AssertionError('HTML must not wait for visitor memory or counts')))
    try:
        with TestClient(create_front_app(front)) as client:
            started = time.monotonic()
            result = client.get('/', headers={'Accept':'text/html'})
            elapsed = time.monotonic()-started
            assert result.status_code == 200 and elapsed < 1.
            assert 'private diagnostic' not in result.text
            assert 'worker-src' in result.headers['content-security-policy']
            assert result.headers['cache-control'] == 'public, max-age=0, s-maxage=60'  # 11-11 same bytes for everyone
            assert entered.is_set()
    finally:
        release.set()
        if front.html_bootstrap.job:
            assert front.html_bootstrap.job['done'].wait(3)
        store._db.close()


def test_forced_empty_shell_keeps_authoritative_menu_hydration_apis_usable(tmp_path,monkeypatch):
    store = Store(str(tmp_path/'empty-shell.sqlite3'))
    rid = store.upsert_resource({'key':'hydration-weather','kind':'mcp','source':'fixture',
        'name':'Hydrated Weather','url':'https://hydration-weather.example/mcp',
        'description':'Read public weather records','category':'travel_maps_weather','networks':[]})
    with store.tx() as db:
        db.execute("UPDATE resources SET active=1,health_status='healthy',auth_observed=0 WHERE id=?",(rid,))
    front = Front(store)
    monkeypatch.setattr(front.html_bootstrap,'read',lambda:json.dumps(EMPTY))
    monkeypatch.setattr(front,'bootstrap_snapshot_json',lambda:(_ for _ in ()).throw(
        AssertionError('The forced empty shell must not synchronously build a snapshot')))
    try:
        with TestClient(create_front_app(front)) as client:
            started = time.monotonic()
            shell = client.get('/',headers={'Accept':'text/html'})
            assert shell.status_code == 200 and time.monotonic()-started < 1.
            match = re.search(r'<script[^>]*id="appBootstrapData"[^>]*>(.*?)</script>',shell.text,re.S)
            assert match and json.loads(match.group(1)) == EMPTY
            assert shell.headers['cache-control'] == 'public, max-age=0, s-maxage=60'
            assert "script-src 'self' 'sha256-" in shell.headers['content-security-policy']
            overview = client.get('/api/overview')
            assert overview.status_code == 200 and overview.json()['health_summary']['live_total'] == 1
            assert overview.json()['verification']['completed'] == 0
            explore = client.get('/api/explore?limit=45')
            assert explore.status_code == 200 and explore.json()['total'] == 1
            assert [item['id'] for item in explore.json()['items']] == [rid]
            assert not explore.json()['items'][0]['connection_readiness']['verified_callable']
            insights = client.get('/api/insights')
            assert insights.status_code == 200 and insights.json()['kinds']['mcp']['stats']['total'] == 1
            templates = client.get('/api/workflows/templates')
            assert templates.status_code == 200 and templates.json()['templates']
            assert all(isinstance(template['nodes'],list) for template in templates.json()['templates'])
            presets = client.get('/api/test/presets')
            assert presets.status_code == 200 and presets.json()['presets']
            assert not any(item['available'] for item in presets.json()['live_examples'])
    finally:
        front.book.close()
        store._db.close()
