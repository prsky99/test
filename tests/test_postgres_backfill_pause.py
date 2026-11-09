"""An empty catalog backfill scan is not repeated until BACKFILL_PAUSE has passed."""
from contextlib import contextmanager

import agent_market.application_store_vector as vector
import agent_market.legacy_vector_index as legacy
from agent_market.legacy_vector_index import ModelDescriptor


def index(monkeypatch, found):
    item = object.__new__(vector.PostgresVectorIndex)
    item.ann_enabled, scans, queued = False, [], []

    def candidates(descriptor, limit):
        scans.append(limit)
        return list(found.pop(0)) if found else []

    @contextmanager
    def tx():
        yield
    item._backfill_candidates, item._tx = candidates, tx
    item._pin, item._bootstrap = (lambda descriptor, bind=True: None), (lambda limit: None)
    monkeypatch.setattr(legacy.VectorIndex, 'ensure_jobs',
                        lambda self, descriptor, limit, ids=None, expected=None: queued.append(ids) or len(ids))
    return item, scans, queued


def test_empty_scan_pauses_and_found_listings_keep_scanning(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(legacy, '_now', lambda: clock[0])
    model = ModelDescriptor('synthetic-embedding')
    item, scans, queued = index(monkeypatch, [[], [5, 6]])
    assert item.ensure_jobs(model, limit=2) == 0 and len(scans) == 1
    clock[0] += vector.BACKFILL_PAUSE - 1
    assert item.ensure_jobs(model, limit=2) == 0 and len(scans) == 1  # paused: no catalog scan
    clock[0] += 2
    assert item.ensure_jobs(model, limit=2) == 2 and queued == [[5, 6]] and len(scans) == 2
    item.ensure_jobs(model, limit=2)
    assert len(scans) == 3  # the last scan found work, so the next call scans again


def test_explicit_resource_requests_never_wait_for_the_pause(monkeypatch):
    monkeypatch.setattr(legacy, '_now', lambda: 1000.0)
    model = ModelDescriptor('synthetic-embedding')
    item, scans, queued = index(monkeypatch, [])
    item._backfill_after = 10 ** 9
    item.ensure_jobs(model, 1, [7], {7: None})
    assert queued == [[7]] and scans == []


def test_a_failed_scan_waits_instead_of_repeating_every_round(monkeypatch):
    # 11-10: the whole-catalog scan hit the 5 s statement timeout every 10 s (4,073 errors).
    import pytest
    from agent_market.legacy_vector_index import VectorError
    clock = [1000.0]
    monkeypatch.setattr(legacy, '_now', lambda: clock[0])
    model = ModelDescriptor('synthetic-embedding')
    item, scans, queued = index(monkeypatch, [])

    def failing(descriptor, limit):
        scans.append(limit)
        raise VectorError('database_error')
    item._backfill_candidates = failing
    with pytest.raises(VectorError):
        item.ensure_jobs(model, limit=2)
    clock[0] += 10
    assert item.ensure_jobs(model, limit=2) == 0 and len(scans) == 1


def test_an_unfinished_sweep_keeps_scanning_the_next_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(legacy, '_now', lambda: clock[0])
    model = ModelDescriptor('synthetic-embedding')
    item, scans, queued = index(monkeypatch, [])
    windows = [False, False, True]

    def window(descriptor, limit):
        scans.append(limit)
        item._backfill_swept = windows.pop(0)
        return []
    item._backfill_candidates = window
    for _ in range(3):
        item.ensure_jobs(model, limit=2)
    assert len(scans) == 3  # each round scans the next window until the sweep ends
    item.ensure_jobs(model, limit=2)
    assert len(scans) == 3  # then it rests
