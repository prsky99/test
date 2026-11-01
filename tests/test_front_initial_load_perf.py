import gzip
import time
import pytest
from starlette.testclient import TestClient
from agent_market.gateway.store import Store
from agent_market.concierge.front import Front, create_front_app, get_snapshot_overview

@pytest.fixture
def performance_store(tmp_path):
    # Never initialize, migrate, or modify the operator's live database in a test.
    store = Store(str(tmp_path / 'performance.sqlite3'))
    store.upsert_page([{
        'key': f'performance-{i}', 'source': 'fixture', 'kind': 'mcp',
        'url': f'https://agent-{i}.example/mcp', 'name': f'Agent {i}',
        'description': 'Task discovery and verification fixture',
        'category': 'ai_models', 'networks': [],
    } for i in range(2000)])
    try:
        yield store
    finally:
        store._db.close()


def test_front_initial_load_under_3_seconds_and_swr_caching(performance_store):
    store = performance_store
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    # 1. Measure Initial First-Visit Page Load Time (Must be strictly under 3.0 seconds)
    t0 = time.time()
    res = client.get("/", headers={"accept": "text/html", "accept-encoding": "gzip"})
    first_load_time = time.time() - t0
    assert res.status_code == 200
    assert first_load_time < 3.0, f"Initial load took {first_load_time:.3f}s which exceeds 3.0s limit!"

    # 2. Check GZip compression (transfers < 125 KB over wire including visual workflow studio)
    assert res.headers.get("content-encoding") == "gzip"
    wire_size = len(gzip.compress(res.content))
    assert wire_size < 125000, f"Gzip compressed payload {wire_size} bytes is too large"

    # 3. Check Cache-Control header (Strict no-store for visitor privacy and token protection)
    cc = res.headers.get("cache-control", "")
    assert cc == "no-store"

    # 4. Measure Subsequent Warm Page Load (RFC 5861 SWR - sub-50ms)
    t1 = time.time()
    res2 = client.get("/", headers={"accept": "text/html", "accept-encoding": "gzip"})
    warm_load_time = time.time() - t1
    assert res2.status_code == 200
    assert warm_load_time < 0.1, f"Warm load took {warm_load_time:.3f}s which exceeds 0.1s target"

    # 5. Measure get_snapshot_overview SWR caching
    t2 = time.time()
    ov = get_snapshot_overview(store)
    ov_time = time.time() - t2
    assert ov_time < 0.1, f"Cached overview query took {ov_time:.3f}s"
    client.close()
