"""Chat latency fixes (2026-11-09): writes after the answer, bounded next steps, strong-model pause."""
import threading
import time

from agent_market.concierge import fast_chat
from agent_market.concierge.memory import VisitorBook


class Store:
    backend = 'sqlite'


def test_deferred_writes_run_in_order_and_reads_wait_for_them():
    book = VisitorBook.__new__(VisitorBook)  # no store needed for the deferral itself
    seen, gate = [], threading.Event()
    book.defer('v1', lambda: (gate.wait(1), seen.append('first')))
    book.defer('v1', lambda: seen.append('second'))
    gate.set()
    book.settle('v1')
    assert seen == ['first', 'second']
    book.settle('nobody')  # nothing pending: returns at once


def test_a_deferred_write_may_call_methods_that_settle_without_waiting_on_itself():
    book = VisitorBook.__new__(VisitorBook)
    done = threading.Event()
    book.defer('v2', lambda: (book.settle('v2'), done.set()))
    assert done.wait(2)


def test_a_failing_deferred_write_does_not_block_later_reads():
    book = VisitorBook.__new__(VisitorBook)
    book.defer('v3', lambda: 1 / 0)
    started = time.monotonic()
    book.settle('v3')
    assert time.monotonic() - started < 1


class Http:
    def __init__(self, fail=True):
        self.fail, self.calls = fail, []

    def post(self, url, json=None, timeout=None):
        self.calls.append(timeout)
        if self.fail:
            raise TimeoutError()
        class Response:
            status_code = 200
            def json(self):
                return {'embeddings': [[1.0, 0.0]] * len(json['input'])}
        return Response()


class Engine:
    embeddings_enabled = True
    ollama_url = 'http://127.0.0.1:11434'


def test_a_failing_strong_model_pauses_and_reloads_in_the_background(monkeypatch):
    monkeypatch.setitem(fast_chat._strong_state, 'down_until', 0.0)
    monkeypatch.setitem(fast_chat._strong_state, 'warming', False)
    engine = Engine(); engine.http = Http(fail=True)
    assert fast_chat.strong_embeddings(engine, ['a', 'b']) is None
    assert fast_chat._strong_state['down_until'] > time.monotonic()
    calls = len(engine.http.calls)
    assert fast_chat.strong_embeddings(engine, ['a', 'b']) is None  # paused: no request at all
    time.sleep(0.05)
    assert fast_chat.STRONG_WARMUP_BUDGET in engine.http.calls  # the reload ran with a long budget
    assert len(engine.http.calls) <= calls + 1


def test_next_steps_are_bounded_cached_and_filtered(monkeypatch):
    calls = []
    class Graph:
        def __init__(self, store):
            pass
        def predict_next(self, rid, tool, limit=2, protocol=None):
            calls.append(rid)
            if rid == 'slow':
                time.sleep(1)
            return [{'resource_id': 1}, {'resource_id': 2}]
    import agent_market.concierge.inertia as inertia
    monkeypatch.setattr(inertia, 'InertiaGraph', Graph)
    monkeypatch.setattr(fast_chat, '_next_steps_cache', {})
    store = Store()
    assert fast_chat.bounded_next_steps(store, 7, 't', None, {2}) == [{'resource_id': 1}]
    assert fast_chat.bounded_next_steps(store, 7, 't', None, set()) == [{'resource_id': 1}, {'resource_id': 2}]
    assert calls == [7]  # the second answer used the cache
    started = time.monotonic()
    assert fast_chat.bounded_next_steps(store, 'slow', 't', None, set()) == []
    assert time.monotonic() - started < 0.9


def test_the_model_watch_reloads_a_dropped_model_once(monkeypatch):
    calls = []
    class WatchHttp:
        def get(self, url, timeout=None):
            class Response:
                def json(self):
                    return {'models': [{'name': 'embeddinggemma-2:270m-mxfp8-text'}]}  # qwen3 dropped
            return Response()
        def post(self, url, json=None, timeout=None):
            calls.append((json['model'], timeout))
            raise StopIteration  # end the loop after one reload attempt
    engine = Engine(); engine.http = WatchHttp()
    monkeypatch.setattr(fast_chat, 'MODEL_WATCH_INTERVAL', 0)
    monkeypatch.setitem(fast_chat._strong_state, 'warming', False)
    sleeps = []
    def stop_after_two(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise SystemExit
    monkeypatch.setattr(fast_chat.time, 'sleep', stop_after_two)
    try:
        fast_chat._watch_models(engine)
    except SystemExit:
        pass
    assert calls == [(fast_chat.STRONG_MODEL, fast_chat.STRONG_WARMUP_BUDGET)]
