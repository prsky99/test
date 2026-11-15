"""P0 11-16 (PM 19:3x): a recommendation with no protocol asked searches A2A and MCP at once, the MCP search on a
read-pool session; QualityRecommender.search's own merge gives the answer the in-turn loop gives. With no free
session, another prefetch running, a failed head start or changed arguments, the loop searches in turn as before."""
from contextlib import contextmanager
import threading
import time

from agent_market.concierge import protocol_prefetch
from agent_market.concierge.gateway_exposure import ExposedFirstRecommender
from agent_market.concierge.protocol_prefetch import prefetching
from agent_market.concierge.selection import QualityRecommender


class Pool:
    def __init__(self, free):
        self.maximum, self.free, self.leases = 6, free, 0

    def free_sessions(self):
        return self.free

    @contextmanager
    def lease_store(self):
        self.leases += 1
        yield type('Leased', (), {})()


class Source:
    backend = 'postgresql'

    def __init__(self, free):
        self._admin_read_pool = Pool(free)


# (id, focused) per protocol; the merge puts focused A2A, focused MCP, then the rest.
TABLE = {'a2a': [(1, True), (2, False)], 'mcp': [(3, True), (4, False), (5, True)]}


class Rec(QualityRecommender):
    def __init__(self, table=TABLE, fail=(), delay=0.0):
        super().__init__(None)
        self.table, self.fail, self.delay = table, fail, delay
        self.calls, self.lock = [], threading.Lock()

    def __copy__(self):
        twin = Rec(self.table, self.fail, self.delay)
        twin.store, twin.calls, twin.lock = self.store, self.calls, self.lock
        return twin

    def _search_protocol(self, task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None,
                         category=None, tiers=None):
        with self.lock:
            self.calls.append((kind, threading.current_thread().name, type(self.store).__name__))
        time.sleep(self.delay)
        if (kind, threading.current_thread().name.startswith('recommend-prefetch')) in self.fail:
            raise RuntimeError('read failed')
        rows = [(rid, focus) for rid, focus in self.table[kind] if rid not in (exclude or ())][:limit]
        if tiers is not None:
            tiers.extend(focus for _, focus in rows)
        return [{'id': rid, 'kind': kind} for rid, _ in rows]


def in_turn(**options):
    return Rec(**options).search('weather forecast', kind=None, limit=4)


def ids(items):
    return [item['id'] for item in items]


def test_the_mcp_search_runs_on_a_pool_session_and_the_answer_is_the_in_turn_answer():
    source, rec = Source(free=6), Rec(delay=0.05)
    fast = prefetching(rec, source)
    got = fast.search('weather forecast', kind=None, limit=4)
    assert got == in_turn() and ids(got) == [1, 3, 5, 2]
    assert source._admin_read_pool.leases == 1
    mcp = [call for call in rec.calls if call[0] == 'mcp']
    assert mcp == [('mcp', mcp[0][1], 'Leased')] and mcp[0][1].startswith('recommend-prefetch')


def test_the_two_searches_overlap():
    started = time.perf_counter()
    prefetching(Rec(delay=0.3), Source(free=6)).search('weather forecast', kind=None, limit=4)
    overlapped = time.perf_counter() - started
    started = time.perf_counter()
    Rec(delay=0.3).search('weather forecast', kind=None, limit=4)
    assert overlapped < time.perf_counter() - started - 0.15


def test_no_free_session_searches_in_turn():
    source, rec = Source(free=0), Rec()
    got = prefetching(rec, source).search('weather forecast', kind=None, limit=4)
    assert got == in_turn() and source._admin_read_pool.leases == 0
    assert all(not name.startswith('recommend-prefetch') for _, name, _ in rec.calls)


def test_a_failed_head_start_is_searched_again_in_turn():
    rec = Rec(fail={('mcp', True)})
    got = prefetching(rec, Source(free=6)).search('weather forecast', kind=None, limit=4)
    assert got == in_turn()
    assert [call[0] for call in rec.calls].count('mcp') == 2   # the failed prefetch, then the in-turn search


def test_another_prefetch_running_searches_in_turn():
    assert protocol_prefetch._slot.acquire(blocking=False)
    try:
        source, rec = Source(free=6), Rec()
        got = prefetching(rec, source).search('weather forecast', kind=None, limit=4)
        assert got == in_turn() and source._admin_read_pool.leases == 0
    finally:
        protocol_prefetch._slot.release()


def test_the_slot_is_free_again_after_a_search():
    prefetching(Rec(), Source(free=6)).search('weather forecast', kind=None, limit=4)
    deadline = time.monotonic() + 2
    while not protocol_prefetch._slot.acquire(blocking=False):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    protocol_prefetch._slot.release()


def test_sqlite_or_no_pool_is_not_prefetched():
    assert prefetching(Rec(), type('S', (), {'backend': 'sqlite'})()) is None
    assert prefetching(Rec(), None) is None


def test_exposed_first_uses_the_process_store_after_a_request_store_is_bound():
    from copy import copy
    source = Source(free=6)
    exposed = ExposedFirstRecommender(Rec(), source)
    scoped = copy(exposed)
    scoped.store = object()                 # front.chat binds the copy to a request store
    assert scoped._read_source is source
    called = []
    original = protocol_prefetch.prefetching
    protocol_prefetch.prefetching = lambda rec, read: called.append(read) or None
    try:
        scoped.search('weather forecast', kind='mcp', limit=1)
        assert called == []                 # a protocol was asked: nothing to overlap
        scoped.search('weather forecast', kind=None, limit=1)
        assert called == [source]
    finally:
        protocol_prefetch.prefetching = original


def outcome(rec, source):
    from agent_market.concierge.retrieval_metrics import capture
    with capture() as values:
        prefetching(rec, source).search('weather forecast', kind=None, limit=4)
    return {name for name in values['stages_ms'] if name.startswith('prefetch_')}


def test_server_timing_names_the_prefetch_outcome():
    assert outcome(Rec(), Source(free=6)) == {'prefetch_hit'}
    assert outcome(Rec(), Source(free=0)) == {'prefetch_skip'}
    assert outcome(Rec(fail={('mcp', True)}), Source(free=6)) == {'prefetch_miss'}
    filled = {'a2a': [(1, True), (2, True), (6, True), (7, True)], 'mcp': TABLE['mcp']}
    assert outcome(Rec(table=filled), Source(free=6)) == {'prefetch_unused'}   # A2A filled the four
