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
