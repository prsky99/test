from concurrent.futures import ThreadPoolExecutor
import threading

from agent_market.admin_read_cache import AdminReadCache


def test_single_flight_and_detached_results():
    cache = AdminReadCache()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1)
        entered.set()
        release.wait(3)
        return {'rows': [1]}
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(cache.get, load)
        assert entered.wait(1)
        second = pool.submit(cache.get, load)
        release.set()
        a, b = first.result(), second.result()
    assert len(calls) == 1
    a['rows'].append(2)
    assert b['rows'] == cache.get(load)['rows'] == [1]


def test_stale_reads_return_immediately_and_refresh_once():
    now = [0]
    cache = AdminReadCache(clock=lambda: now[0])
    cache.get(lambda: {'version': 1})
    now[0] = 6
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def load():
        calls.append(1)
        entered.set()
        release.wait(3)
        done.set()
        return {'version': 2}
    assert cache.get(load)['version'] == 1
    assert entered.wait(1)
    assert cache.get(load)['_cache']['status'] == 'stale'
    assert len(calls) == 1
    release.set()
    assert done.wait(1)
    with cache.condition:
        cache.condition.wait_for(lambda: not cache.busy, 1)
    assert cache.get(load)['version'] == 2


def test_invalidation_drops_inflight_old_snapshot():
    cache = AdminReadCache()
    cache.get(lambda: {'value': 'old'})
    cache.invalidate()
    assert cache.get(lambda: {'value': 'new'})['value'] == 'new'
    assert cache.get(lambda: {'value': 'unused'})['value'] == 'new'
