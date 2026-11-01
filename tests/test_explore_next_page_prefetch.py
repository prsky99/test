"""Load More finds the next window already computed; the prefetch never blocks a search."""
import threading

from agent_market.concierge import front as front_module
from agent_market.concierge.front import _ExploreResultCache, _NextPagePrefetch


def test_prefetched_window_is_cached_for_load_more(monkeypatch):
    cache = _ExploreResultCache()
    monkeypatch.setattr(front_module, '_explore_result_cache', cache)
    done = threading.Event()
    calls = []

    def compute():
        calls.append(1)
        done.set()
        return {'items': [{'id': i} for i in range(91)], 'complete': False}

    prefetch = _NextPagePrefetch()
    key = ('store', 'currency exchange rates', None, None, False, False, 91)
    assert prefetch.submit(key, compute)
    assert done.wait(5)
    for _ in range(100):
        if cache.get(key) is not None:
            break
        threading.Event().wait(0.01)
    assert cache.get(key)['items'][90] == {'id': 90}
    # A window already cached is not computed again.
    assert prefetch.submit(key, compute)
    threading.Event().wait(0.1)
    assert len(calls) == 1


def test_a_full_queue_drops_instead_of_waiting(monkeypatch):
    monkeypatch.setattr(front_module, '_explore_result_cache', _ExploreResultCache())
    release = threading.Event()
    prefetch = _NextPagePrefetch(maximum=1)
    assert prefetch.submit(('k', 1), lambda: release.wait(5) and {'items': []})
    threading.Event().wait(0.05)  # the worker takes the first request and blocks on it
    assert prefetch.submit(('k', 2), lambda: {'items': []})
    assert prefetch.submit(('k', 3), lambda: {'items': []}) is False
    release.set()


def test_a_failing_prefetch_is_skipped(monkeypatch):
    cache = _ExploreResultCache()
    monkeypatch.setattr(front_module, '_explore_result_cache', cache)
    prefetch = _NextPagePrefetch()
    done = threading.Event()

    def broken():
        raise RuntimeError('database unavailable')

    assert prefetch.submit(('k', 1), broken)
    assert prefetch.submit(('k', 2), lambda: done.set() or {'items': [], 'complete': True})
    assert done.wait(5)
