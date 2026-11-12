"""/api/insights reads a jobs snapshot; the request path never aggregates (PM 11-13 02:2x, 01:49 500)."""
import json
import logging
import os
from pathlib import Path

import pytest

from agent_market.concierge import insights_snapshot as snap

VALUE = {'now': 1794500000.0, 'categories': {}, 'kinds': {'mcp': {'stats': {'total': 3}, 'featured': []}}}


class NoQueries:
    """A store a public request must not touch."""
    def query(self, *args, **kwargs):
        raise AssertionError('the request path aggregated the catalog')


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    snap.reset()
    yield tmp_path / 'public-pages'
    snap.reset()


def test_a_request_reads_the_snapshot_without_querying(folder):
    snap.write(str(folder / snap.NAME), VALUE)
    assert snap.served(NoQueries()) == VALUE


def test_before_any_snapshot_the_old_computation_answers(folder, monkeypatch):
    from agent_market.concierge import front
    monkeypatch.setattr(front, 'get_front_insights', lambda store: {'computed': True})
    assert snap.served(object()) == {'computed': True}


def test_reader_rereads_a_new_file_and_keeps_the_last_good_value(tmp_path):
    path = tmp_path / snap.NAME
    clock = [0.0]
    reader = snap.Reader(lambda: path, monotonic=lambda: clock[0])
    assert reader.read() is None                                  # missing
    snap.write(str(path), VALUE)
    clock[0] += snap.CHECK_SECONDS
    assert reader.read() == VALUE
    newer = {**VALUE, 'now': VALUE['now'] + 300}
    snap.write(str(path), newer)
    os.utime(path, ns=(path.stat().st_mtime_ns + 10**9,) * 2)
    assert reader.read() == VALUE                                 # checked at most every CHECK_SECONDS
    clock[0] += snap.CHECK_SECONDS
    assert reader.read() == newer
    path.write_text('{broken')                                    # a bad file never replaces a good value
    os.utime(path, ns=(path.stat().st_mtime_ns + 2 * 10**9,) * 2)
    clock[0] += snap.CHECK_SECONDS
    assert reader.read() == newer
    path.unlink()                                                 # nor does a missing one
    clock[0] += snap.CHECK_SECONDS
    assert reader.read() == newer


def test_write_refuses_an_invalid_value_and_leaves_no_temporary_file(tmp_path):
    with pytest.raises(ValueError):
        snap.write(str(tmp_path / snap.NAME), {'kinds': 'no'})
    assert list(tmp_path.iterdir()) == []


def test_refresher_writes_then_waits_and_keeps_the_last_file_after_a_failure(tmp_path, caplog):
    out = tmp_path / 'public-pages' / snap.NAME
    now = [1000.0]
    result = [VALUE]

    def compute(store):
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]
    front = type('Front', (), {'store': object()})()
    job = snap.InsightsRefresher(front, out=out, clock=lambda: now[0], compute=compute)
    assert job.due() and job.run() is True
    assert json.loads(out.read_text()) == VALUE and job.next_at == now[0] + snap.REFRESH_SECONDS
    now[0] += snap.REFRESH_SECONDS - 1
    assert not job.due()
    now[0] += 1
    error = Exception('timeout')
    error.code = 'statement_failed'
    result[0] = error
    with caplog.at_level(logging.WARNING):
        assert job.run() is False
    assert 'statement_failed' in caplog.text and 'previous snapshot stays' in caplog.text
    assert json.loads(out.read_text()) == VALUE                   # the last success still serves
    assert job.next_at == now[0] + snap.RETRY_SECONDS


def test_refresher_is_idle_without_a_project_root(monkeypatch):
    monkeypatch.delenv('AGENTCON_PROJECT_ROOT', raising=False)
    job = snap.InsightsRefresher(type('Front', (), {'store': None})(), compute=lambda s: VALUE)
    assert job.due() is False


def test_jobs_writer_and_frontend_reader_meet_in_the_same_file(tmp_path, monkeypatch):
    # Production: jobs has AGENTCON_PROJECT_ROOT=<root>; frontend has LOG_DIR=<root>/logs/service-frontend.
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    monkeypatch.setenv('LOG_DIR', str(tmp_path / 'logs' / 'service-frontend'))
    assert snap.output_path() == snap.read_path()


def test_the_real_computation_skips_caches_when_fresh_and_makes_a_valid_snapshot(tmp_path):
    from agent_market.gateway.store import Store
    from agent_market.concierge import front
    store = Store(str(tmp_path / 'insights.sqlite3'))
    try:
        front.clear_front_caches()
        first = front.get_front_insights(store, fresh=True)
        assert snap.valid(first)
        second = front.get_front_insights(store, fresh=True)
        assert second['now'] >= first['now'] and second is not first   # computed again, not the cached copy
    finally:
        front.clear_front_caches()
        store._db.close()


def test_public_paths_use_the_snapshot_and_jobs_refresh_it():
    root = Path(__file__).resolve().parents[1]
    front = (root / 'agent_market/concierge/front.py').read_text()
    assert 'return served_insights(front.store)' in front
    assert "measured('insights', lambda: served_insights(self.store))" in front
    host = (root / 'agent_market/service_host.py').read_text()
    assert 'insights.due()' in host and "InsightsRefresher(front) if self.role=='jobs'" in host
