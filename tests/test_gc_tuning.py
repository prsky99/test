"""PM 11-16 20:2x: freeze long-lived objects after warm-up and snapshot refreshes; larger generation-0 threshold."""
import gc

import pytest

from agent_market import gc_tuning as G


@pytest.fixture(autouse=True)
def restore():
    threshold = gc.get_threshold()
    start = dict(G._start)
    yield
    gc.unfreeze()
    gc.set_threshold(*threshold)
    G._start.clear()
    G._start.update(start)


def test_configure_raises_only_generation_zero():
    _, one, two = gc.get_threshold()
    assert G.configure() == (G.THRESHOLD0, one, two)


def test_settle_freezes_what_is_alive_and_frozen_objects_are_skipped():
    G._start['frozen'] = None
    keep = [{'n': i} for i in range(20_000)]
    done = G.settle('startup')
    assert done['collected'] and done['frozen'] >= 20_000 and G._start['frozen'] == done['frozen']
    assert abs(gc.get_freeze_count() - done['frozen']) <= 100 and done['rss_peak_mb'] > 0   # a few freed since
    assert keep


def test_a_refresh_freezes_without_a_collection_until_the_frozen_count_doubles(monkeypatch):
    calls = []
    monkeypatch.setattr(G.gc, 'collect', lambda *a: calls.append('collect') or 0)
    G._start['frozen'] = 10 ** 9
    assert G.settle('report_snapshot', collect=False)['collected'] is False and calls == []
    G._start['frozen'] = 1                     # the frozen count has more than doubled: one full collection
    assert G.settle('report_snapshot', collect=False)['collected'] is True and calls == ['collect']


def test_a_refresh_frees_the_old_snapshot_before_freezing_the_new_one(monkeypatch):
    import weakref
    from agent_market.concierge import report_snapshot as R

    class Store:
        pass
    store = Store()
    old = R.Snapshot([{'row': {'id': i}} for i in range(1000)], 0.0)
    R._snapshots[id(store)] = old
    gone = weakref.ref(old)
    del old
    seen = {}
    monkeypatch.setattr(R, 'build', lambda *a: R.Snapshot([{'row': {'id': 1}}], 1.0))
    monkeypatch.setattr(G, 'settle', lambda reason, collect=True: seen.setdefault('old_alive', gone() is not None))
    try:
        R.refresh(store)
    finally:
        R._snapshots.pop(id(store), None)
        R._states.pop(id(store), None)
    assert seen == {'old_alive': False}          # freed by reference counting before the freeze


def test_keep_fresh_holds_no_snapshot_of_its_own():
    import inspect
    from agent_market.concierge import report_snapshot as R
    assert 'snapshot = _snapshots' not in inspect.getsource(R.keep_fresh)
