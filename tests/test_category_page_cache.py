"""느린 DB가 카테고리 미리보기·status.json을 막지 않게 하는 캐시(2026-11-09, 운영·SRE).

11-09 20:4x KST에 /agents/category/web_search가 125초, status.json 점검이 5번 시간 초과였다."""
import threading
import time
from types import SimpleNamespace

import pytest

from agent_market.agent_access import pages


def _fake(monkeypatch, behaviour):
    calls = []

    def build(front, category):
        calls.append(category)
        return behaviour(len(calls))
    monkeypatch.setattr(pages, 'category_page', build)
    return calls


def test_page_is_built_once_per_window_and_rebuilt_after(monkeypatch):
    calls = _fake(monkeypatch, lambda n: f'page {n}')
    front, now = SimpleNamespace(), [1000.0]
    clock = lambda: now[0]
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 1'
    now[0] += pages.CACHE_SECONDS - 1
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 1'
    now[0] += 2
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 2'
    assert calls == ['web_search', 'web_search']


def test_unknown_category_is_refused_before_any_build(monkeypatch):
    calls = _fake(monkeypatch, lambda n: 'x')
    with pytest.raises(ValueError):
        pages.cached_category_page(SimpleNamespace(), 'not-a-category')
    assert calls == []


def test_failed_rebuild_serves_the_previous_page(monkeypatch):
    def behaviour(n):
        if n == 2:
            raise TimeoutError('database stalled')
        return f'page {n}'
    _fake(monkeypatch, behaviour)
    front, now = SimpleNamespace(), [0.0]
    clock = lambda: now[0]
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 1'
    now[0] += pages.CACHE_SECONDS + 1
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 1'
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 3'


def test_first_build_failure_is_not_hidden(monkeypatch):
    _fake(monkeypatch, lambda n: (_ for _ in ()).throw(TimeoutError('no page yet')))
    with pytest.raises(TimeoutError):
        pages.cached_category_page(SimpleNamespace(), 'web_search')


def test_requests_during_a_slow_rebuild_get_the_previous_page_at_once(monkeypatch):
    release, started = threading.Event(), threading.Event()

    def behaviour(n):
        if n == 2:
            started.set()
            release.wait(5)
        return f'page {n}'
    _fake(monkeypatch, behaviour)
    front, now = SimpleNamespace(), [0.0]
    clock = lambda: now[0]
    pages.cached_category_page(front, 'web_search', clock=clock)
    now[0] += pages.CACHE_SECONDS + 1
    slow = threading.Thread(target=pages.cached_category_page, args=(front, 'web_search'), kwargs={'clock': clock})
    slow.start()
    assert started.wait(5)
    begun = time.monotonic()
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 1'
    assert time.monotonic() - begun < 1
    release.set()
    slow.join(5)
    assert pages.cached_category_page(front, 'web_search', clock=clock) == 'page 2'


def test_status_projection_is_reused_briefly_but_explicit_times_are_fresh(monkeypatch):
    from agent_market import public_availability
    seen = []

    def compute(store, now):
        seen.append(now)
        return {'n': len(seen)}
    monkeypatch.setattr(public_availability, '_projection', compute)
    store = SimpleNamespace()
    assert public_availability.projection(store) == {'n': 1}
    assert public_availability.projection(store) == {'n': 1}
    assert public_availability.projection(store, 123.0) == {'n': 2}
    store._availability_projection = (time.monotonic() - public_availability.PROJECTION_SECONDS - 1, {'n': 1})
    assert public_availability.projection(store) == {'n': 3}


def test_route_uses_the_cached_builder():
    from pathlib import Path
    source = (Path(pages.__file__).parent / 'service.py').read_text(encoding='utf-8')
    assert 'run_in_threadpool(cached_category_page,front,category)' in source
