"""느린 DB가 카테고리 미리보기·status.json을 막지 않게 하는 캐시(2026-11-09, 운영·SRE).

11-09 20:4x KST에 /agents/category/web_search가 125초, status.json 점검이 5번 시간 초과였다."""
import threading
import time
from types import SimpleNamespace

import pytest

from agent_market.agent_access import pages
from tests.test_fast_single_recommendation import catalog  # noqa: F401


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


def test_failed_public_probe_logs_whether_the_origin_answered(caplog):
    import httpx
    from agent_market.public_availability import AvailabilityMonitor
    seen = []

    def local(request):
        seen.append((str(request.url), request.headers['host']))
        return httpx.Response(200, json={'service': 'Agent Concierge'})
    with httpx.Client(transport=httpx.MockTransport(local)) as http:
        monitor = AvailabilityMonitor(SimpleNamespace(public_url='https://agentconcierge.biz'), local_http=http)
        with caplog.at_level('WARNING'):
            assert monitor.record_origin(None, 5002.0) == 'path'
    assert seen == [('http://127.0.0.1:8400/status.json', 'agentconcierge.biz')]
    assert 'path problem' in caplog.text

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as http:
        monitor = AvailabilityMonitor(SimpleNamespace(public_url='https://agentconcierge.biz'), local_http=http)
        assert monitor.record_origin(None, 5002.0) == 'origin'


def test_public_status_rows_are_unchanged_by_the_origin_check(catalog):
    import httpx
    from agent_market.public_availability import AvailabilityMonitor, projection
    store = catalog[0]
    asked = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as public, \
         httpx.Client(transport=httpx.MockTransport(lambda r: asked.append(1) or httpx.Response(200))) as local:
        monitor = AvailabilityMonitor(SimpleNamespace(store=store, public_url='https://agentconcierge.biz'),
                                      http=public, local_http=local, clock=lambda: 1794200000.0)
        monitor.run()
    value = projection(store, 1794200000.0)
    assert asked == [1] and value['availability']['observation_count'] == 1
    assert value['availability']['availability_percent'] == 0 and value['status'] == 'degraded'


def test_snapshot_refresh_stops_when_the_slot_turns_standby(monkeypatch):
    from agent_market.concierge import report_snapshot
    stop = threading.Event()
    serving = [True]
    halt = report_snapshot._UntilStandby(stop, lambda: serving[0], clock=lambda: clock[0])
    clock = [0.0]
    assert halt.is_set() is False
    serving[0] = False
    clock[0] += 1
    assert halt.is_set() is False  # checked at most every CHECK_SECONDS
    clock[0] += report_snapshot._UntilStandby.CHECK_SECONDS
    assert halt.is_set() is True and halt.standby is True


def test_start_build_always_runs_and_later_refreshes_use_the_standby_stop(monkeypatch):
    from agent_market.concierge import report_snapshot
    stop, calls = threading.Event(), []

    def refresh(store, halt):
        calls.append(halt)
        if len(calls) == 2:
            stop.set()
        return None
    monkeypatch.setattr(report_snapshot, 'refresh', refresh)
    monkeypatch.setattr(report_snapshot, 'STANDBY_CHECK_SECONDS', 0)
    report_snapshot.keep_fresh(object(), stop, interval=0, serving=lambda: True)
    assert calls[0] is stop and isinstance(calls[1], report_snapshot._UntilStandby)
