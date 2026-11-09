"""평가 점수 백분위 캐시(2026-11-10, 운영·SRE): 같은 (종류, 점수)는 10분 동안 다시 세지 않는다."""
from types import SimpleNamespace

from agent_market.collector import percentile_cache


class Store(SimpleNamespace):
    def score_percentile(self, score, kind='mcp'):
        self.calls.append((kind, score))
        return round(score / 100, 3)


def test_same_kind_and_score_is_counted_once_per_window():
    store, now = Store(calls=[]), [0.0]
    clock = lambda: now[0]
    assert percentile_cache.score_percentile(store, 72.5, 'mcp', clock=clock) == 0.725
    assert percentile_cache.score_percentile(store, 72.5, 'mcp', clock=clock) == 0.725
    assert percentile_cache.score_percentile(store, 72.5, 'a2a', clock=clock) == 0.725
    assert percentile_cache.score_percentile(store, 60.0, 'mcp', clock=clock) == 0.6
    assert store.calls == [('mcp', 72.5), ('a2a', 72.5), ('mcp', 60.0)]
    now[0] += percentile_cache.TTL_SECONDS
    percentile_cache.score_percentile(store, 72.5, 'mcp', clock=clock)
    assert store.calls[-1] == ('mcp', 72.5) and len(store.calls) == 4


def test_each_store_has_its_own_cache_and_none_is_cached():
    class Few(Store):
        def score_percentile(self, score, kind='mcp'):
            self.calls.append(score)
            return None
    first, second = Few(calls=[]), Few(calls=[])
    assert percentile_cache.score_percentile(first, 50, 'mcp') is None
    assert percentile_cache.score_percentile(first, 50, 'mcp') is None
    assert percentile_cache.score_percentile(second, 50, 'mcp') is None
    assert first.calls == [50] and second.calls == [50]


def test_the_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr(percentile_cache, 'MAX_ENTRIES', 3)
    store = Store(calls=[])
    for score in range(10):
        percentile_cache.score_percentile(store, score, 'mcp', clock=lambda: 0.0)
    assert len(store._score_percentile_cache) <= 3


def test_evaluators_use_the_cache():
    from pathlib import Path
    root = Path(percentile_cache.__file__).parent
    for name, kind in (('capabilities.py', 'mcp'), ('a2a.py', 'a2a')):
        text = (root / name).read_text(encoding='utf-8')
        assert f'cached_percentile(self.store, ev["score"], "{kind}")' in text
        assert 'self.store.score_percentile(' not in text
