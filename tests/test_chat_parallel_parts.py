"""PM 11-13 21:0x: a two-part Chat request searches its parts at once on read-pool sessions; the answer is
the one the in-turn loop gives, and with no two free sessions the parts are searched in turn as before."""
from contextlib import contextmanager
import threading

from agent_market.concierge import fast_chat
from agent_market.concierge.chat_guidance import separate_requests
from agent_market.concierge.fast_chat import FastConcierge, part_text

TASK = 'translate a pdf and email it'


class Pool:
    def __init__(self, free):
        self.maximum, self.free, self.leases = 6, free, 0

    def free_sessions(self):
        return self.free

    @contextmanager
    def lease_store(self):
        self.leases += 1
        yield type('Leased', (), {})()


class Store:
    backend = 'postgresql'

    def __init__(self, free):
        self._admin_read_pool = Pool(free)


class Rec:
    """Ranked listings per part text; exclude filters them, as the recommender's exclude does."""

    def __init__(self, table):
        self.table, self.store, self.calls, self.lock = table, None, [], threading.Lock()

    def __copy__(self):
        twin = Rec(self.table)
        twin.calls, twin.lock = self.calls, self.lock
        return twin

    def search(self, text, kind=None, limit=3, offset=0, exclude=None):
        with self.lock:
            self.calls.append((text, frozenset(exclude or ()), self.store is not None and not isinstance(self.store, Store)))
        return [{'id': rid, 'name': str(rid)} for rid in self.table[text] if rid not in (exclude or set())][:limit]


def concierge(table, free):
    bot = FastConcierge.__new__(FastConcierge)
    bot.store, bot.rec = Store(free), Rec(table)
    return bot


def answer(bot):
    return bot._cover_parts(TASK, [{'id': 99, 'name': 'whole'}], None, {7})


def in_turn(table):
    return answer(concierge(table, free=0))


def test_parts_run_at_once_and_match_the_in_turn_answer():
    first, second = [part_text(p) for p in separate_requests(TASK)]
    table = {first: [1, 2, 3], second: [4, 5, 6]}
    bot = concierge(table, free=6)
    assert answer(bot) == in_turn(table)
    assert [item['id'] for item in answer(bot)[0]] == [1, 4]
    pooled = [call for call in bot.rec.calls if call[2]]
    assert len(pooled) >= 2 and bot.store._admin_read_pool.leases >= 2


def test_a_listing_taken_by_an_earlier_part_is_searched_again_in_turn():
    first, second = [part_text(p) for p in separate_requests(TASK)]
    table = {first: [1, 2], second: [1, 5]}           # the second part's early best is the first part's pick
    bot = concierge(table, free=6)
    got = answer(bot)
    assert got == in_turn(table) and [item['id'] for item in got[0]] == [1, 5]
    assert (second, frozenset({7, 1}), False) in bot.rec.calls   # the in-turn search, listing 1 excluded


def test_without_two_free_sessions_the_parts_are_searched_in_turn():
    first, second = [part_text(p) for p in separate_requests(TASK)]
    table = {first: [1], second: [4]}
    bot = concierge(table, free=1)
    assert [item['id'] for item in answer(bot)[0]] == [1, 4]
    assert bot.store._admin_read_pool.leases == 0 and all(not call[2] for call in bot.rec.calls)


def test_a_store_without_a_read_pool_and_a_busy_slot_keep_the_in_turn_loop():
    first, second = [part_text(p) for p in separate_requests(TASK)]
    table = {first: [1], second: [4]}
    bot = concierge(table, free=6)
    bot.store = type('Plain', (), {'backend': 'sqlite'})()
    assert [item['id'] for item in answer(bot)[0]] == [1, 4]
    bot = concierge(table, free=6)
    assert fast_chat._parallel_parts.acquire(blocking=False)
    try:
        assert [item['id'] for item in answer(bot)[0]] == [1, 4] and bot.store._admin_read_pool.leases == 0
    finally:
        fast_chat._parallel_parts.release()


def test_qualifiers_leave_the_catalog_search_but_bulk_stays():
    """PM 11-13 22:3x: when or for whom is not a capability; batch processing is."""
    from agent_market.concierge.fast_chat import retrieval_text
    assert retrieval_text('send email small business 13') == 'send email 13'
    assert retrieval_text('book flights in real time') == 'book flights'
    assert retrieval_text('weather forecast for my team today') == 'weather forecast'
    assert retrieval_text('stock quotes for agents quickly') == 'stock quotes'
    assert retrieval_text('customer support bulk') == 'customer support bulk'
    assert retrieval_text('real-time stock prices') == 'real-time stock prices'
    assert retrieval_text('small business') == 'small business'      # nothing else to search for
