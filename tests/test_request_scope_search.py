"""PM 11-16 source review 3.3: one request no longer repeats the same retrieval, and a split request's parts start
together on read-pool sessions."""
import inspect

from agent_market.concierge import fast_chat as fc
from agent_market.concierge.retrieval_metrics import capture, remembered, request_memo


def test_a_retrieval_step_runs_once_per_request_and_every_time_outside_one():
    runs = []
    compute = lambda: runs.append(1) or ['a', 'b']
    with request_memo(), capture() as values:
        assert remembered(('ann', 'x'), compute) == ['a', 'b']
        assert remembered(('ann', 'x'), compute) == ['a', 'b']
        assert remembered(('ann', 'y'), compute) == ['a', 'b']
    assert len(runs) == 2 and 'request_memo' in values['stages_ms']
    remembered(('ann', 'x'), compute)
    remembered(('ann', 'x'), compute)
    assert len(runs) == 4                                  # no request scope: nothing is shared
    with request_memo():
        remembered(('ann', 'x'), compute)
    assert len(runs) == 5                                  # a new request starts empty


def test_discovery_remembers_lexical_embedding_and_ann_by_what_they_depend_on():
    from agent_market.concierge import discovery, request_timing
    source = inspect.getsource(discovery.candidates)
    assert "remembered(('lexical', tuple(words), joiner, kind, category)" in source
    assert "remembered(('embedding'," in source and "remembered(('ann', descriptor.digest, intent.positive, kind, category)" in source
    assert 'request_memo()' in inspect.getsource(request_timing.RequestTiming.__call__)


class _NoFailures:
    def failed_resources(self, visitor):
        return set()

    def global_failing_resources(self):
        return set()


class _PartRec:
    rag_engine = None

    def __init__(self):
        self.calls = []

    def search(self, text, kind=None, limit=3, offset=0, exclude=None):
        self.calls.append((text, frozenset(exclude or ())))
        return []


def test_split_parts_use_the_early_searches_and_a_taken_first_listing_is_searched_again_in_turn(monkeypatch):
    from agent_market.concierge.chat_guidance import separate_requests
    task = 'translate a pdf and email it'
    parts = separate_requests(task)
    assert len(parts) == 2
    monkeypatch.setattr(fc, 'capability_focus', lambda *a, **k: None)
    monkeypatch.setattr(fc, 'neighbor_focus', lambda *a, **k: None)
    monkeypatch.setattr(fc, 'unknown_words', lambda *a, **k: [])
    listing = {'id': 7, 'name': 'Doc tool', 'kind': 'mcp', 'category': 'productivity', 'tools': ['t'], 'tools_schema': [{'name': 't'}]}
    asked = []
    monkeypatch.setattr(fc.FastConcierge, '_part_searches',
                        staticmethod(lambda self, split, protocol, excluded: asked.append(list(split)) or [[listing], [listing]]))
    bot = fc.FastConcierge.__new__(fc.FastConcierge)
    bot.store, bot.rec, bot.book = object(), _PartRec(), _NoFailures()
    try:
        bot._recommend_unobserved(None, task, persist=False)
    except Exception:
        pass                                               # what follows the parts needs a real store
    assert asked == [parts]
    in_turn = [(text, exclude) for text, exclude in bot.rec.calls if text == fc.part_text(parts[1])]
    assert in_turn and 7 in in_turn[0][1]                  # part 2's early first listing was taken by part 1
    assert not [text for text, _ in bot.rec.calls if text == fc.part_text(parts[0])]   # part 1 used its early one


def test_waiting_before_the_app_is_named_queue_and_the_loop_lag_is_watched():
    """PM 11-16 15:46: time spent before the middleware (proxy stamp) and the event loop's wake-up delay."""
    import asyncio
    from agent_market.concierge import request_timing as rt
    scope = {'headers': [(b'x-request-start', b't=1000000')]}
    assert rt.queued_ms(scope, now_epoch=1000.25) == 250.0
    assert rt.queued_ms({'headers': []}) is None and rt.queued_ms({'headers': [(b'x-request-start', b'junk')]}) is None
    assert rt.queued_ms(scope, now_epoch=900) is None              # a stamp from the future is ignored

    async def run():
        rt._lag.update(task=None, samples=__import__('collections').deque())
        assert rt.loop_lag_ms() is None                            # no sample yet
        await asyncio.sleep(0.15)
        time.sleep(0.2)                                            # a blocking call in the loop
        await asyncio.sleep(0.25)
        lag = rt.loop_lag_ms()
        rt._lag['task'].cancel()
        return lag
    import time
    assert asyncio.run(run()) >= 150
