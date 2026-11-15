"""PM 11-16 06:4x: discovery remembers each vector provenance verdict for up to 120 s, bounded in size, and says in
Server-Timing whether it read the database (provenance_miss) or memory only (provenance_hit)."""
import pytest

from agent_market import vector_provenance_cache as cache
from agent_market.concierge.retrieval_metrics import capture


class Info:
    host, port, dbname = 'db', 5432, 'catalog'


class Index:
    def __init__(self, current, dbname='catalog'):
        info = type('I', (), {'host': 'db', 'port': 5432, 'dbname': dbname})()
        self.store = type('S', (), {'_connection': type('C', (), {'info': info})()})()
        self.current, self.asked = set(current), []

    def current_ids(self, ids, descriptor):
        self.asked.append(list(ids))
        return {rid for rid in ids if rid in self.current}


class Descriptor:
    digest = 'model-a'


@pytest.fixture(autouse=True)
def empty(monkeypatch):
    monkeypatch.setattr(cache, 'ENABLED', True)
    cache.clear()
    yield
    cache.clear()


def test_the_answer_is_the_index_answer_and_a_second_read_stays_in_memory():
    index = Index({1, 3})
    with capture() as first:
        assert cache.current_ids(index, [1, 2, 3], Descriptor(), now=0) == {1, 3}
    with capture() as second:
        assert cache.current_ids(index, [3, 2, 1], Descriptor(), now=60) == {1, 3}
    assert index.asked == [[1, 2, 3]]
    assert 'provenance_miss' in first['stages_ms'] and 'provenance_hit' not in first['stages_ms']
    assert 'provenance_hit' in second['stages_ms'] and 'provenance_miss' not in second['stages_ms']


def test_only_unknown_or_expired_ids_are_asked_again():
    index = Index({1, 2, 4})
    cache.current_ids(index, [1, 2], Descriptor(), now=0)
    assert cache.current_ids(index, [1, 2, 4], Descriptor(), now=10) == {1, 2, 4}
    assert index.asked[-1] == [4]
    index.current.discard(1)                       # retired since; known again once the verdict is 120 s old
    assert cache.current_ids(index, [1, 2], Descriptor(), now=119) == {1, 2}
    assert cache.current_ids(index, [1, 2], Descriptor(), now=121) == {2}


def test_another_database_or_model_is_never_answered_from_memory():
    cache.current_ids(Index({1}), [1], Descriptor(), now=0)
    other = Index(set(), dbname='copy')
    assert cache.current_ids(other, [1], Descriptor(), now=1) == set() and other.asked == [[1]]
    model = type('D', (), {'digest': 'model-b'})()
    third = Index(set())
    assert cache.current_ids(third, [1], model, now=1) == set() and third.asked == [[1]]


def test_sqlite_or_unknown_sessions_always_read_the_index():
    index = Index({1})
    index.store = type('S', (), {'_connection': object()})()
    cache.current_ids(index, [1], Descriptor(), now=0)
    cache.current_ids(index, [1], Descriptor(), now=1)
    assert index.asked == [[1], [1]]


def test_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(cache, 'MAX_ENTRIES', 5)
    index = Index(set(range(20)))
    cache.current_ids(index, list(range(20)), Descriptor(), now=0)
    assert len(cache._verdicts) == 5
    cache.current_ids(index, [19], Descriptor(), now=1)
    assert index.asked[-1] == list(range(20))      # the newest stayed
    cache.current_ids(index, [0], Descriptor(), now=1)
    assert index.asked[-1] == [0]                  # the oldest left first


def test_a_publish_in_this_process_forgets_that_listing():
    index = Index({1, 2})
    cache.current_ids(index, [1, 2], Descriptor(), now=0)
    cache.forget(1)
    cache.current_ids(index, [1, 2], Descriptor(), now=1)
    assert index.asked[-1] == [1]


def test_discovery_uses_the_memory_and_publishing_forgets():
    import inspect
    from agent_market.concierge import discovery
    from agent_market.application_store_vector import PostgresVectorIndex
    assert 'remembered_current_ids(index, ids, descriptor)' in inspect.getsource(discovery)
    assert 'forget(claim.resource_id)' in inspect.getsource(PostgresVectorIndex._after_publish)


def test_off_by_default_every_call_reads_the_index_as_before(monkeypatch):
    """PM 11-16 06:5x: shipped off until the copy measurement; off, nothing is remembered or timed."""
    import importlib
    assert importlib.reload(cache).ENABLED is False
    index = Index({1, 3})
    with capture() as values:
        assert cache.current_ids(index, [1, 2, 3], Descriptor(), now=0) == {1, 3}
        assert cache.current_ids(index, [1, 2, 3], Descriptor(), now=1) == {1, 3}
    assert index.asked == [[1, 2, 3], [1, 2, 3]] and not cache._verdicts
    assert not {'provenance_hit', 'provenance_miss'} & set(values['stages_ms'])
