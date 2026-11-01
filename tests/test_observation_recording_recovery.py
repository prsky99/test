"""Bounded metadata recovery never repeats a business call or commits its transaction."""
import json
import asyncio
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

import agent_market.observability as obs
from agent_market.gateway.store import Store
from tests.test_admin_security_audit import admin, H


@pytest.fixture
def recording(tmp_path):
    store = Store(str(tmp_path / 'recording.sqlite3'))
    journal = obs.journal_for(store)
    op = journal.begin('execution', 'managed')
    attempt = op.attempt(7, 'mcp')
    assert op.id and attempt.id
    yield store, journal, op, attempt
    journal.close()
    store._db.close()


def test_completion_recovers_from_real_writer_lock_without_changing_observed_time(recording, monkeypatch):
    store, journal, op, attempt = recording
    origin = time.time()
    clock = [origin]
    monkeypatch.setattr(obs.time, 'time', lambda: clock[0])
    blocker = sqlite3.connect(store._path)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        attempt.dispatch()
        clock[0] += 1
        attempt.finish('succeeded', transport=True, valid=True)
        clock[0] += 1
        op.finish('succeeded')
        health = journal.health()
        assert health['pending_writes'] == 3 and not health['complete']
        assert health['dropped_writes'] == 0 and health['write_failures'] >= 1
        assert store.query('SELECT status FROM platform_operations WHERE id=?', (op.id,))[0][0] == 'running'
    finally:
        blocker.rollback()
        blocker.close()
    clock[0] += 30
    assert journal.flush() == 3
    with store._lock:
        report = obs.snapshot(store._db, journal=journal)
    row = report['operations'][0]
    assert row['status'] == 'succeeded' and row['finished'] == origin + 2
    assert row['attempts'][0]['dispatched'] == origin
    assert row['attempts'][0]['finished'] == origin + 1
    assert row['attempts'][0]['dispatch_to_result_ms'] == pytest.approx(1000)
    assert report['attempt_counts']['prepared'] == 1
    assert report['recording']['complete'] and report['recording']['pending_writes'] == 0
    assert report['coverage_complete'] is False


def test_buffered_timeout_and_late_success_keep_unknown_and_single_finish(recording):
    store, journal, op, attempt = recording
    blocker = sqlite3.connect(store._path)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        started = time.monotonic()
        attempt.dispatch()
        op.finish('timed_out', 'UPSTREAM_TIMEOUT')
        attempt.finish('succeeded', transport=True, valid=True)
        op.finish('succeeded')
        assert time.monotonic() - started < .6
        assert journal.health()['pending_writes'] == 4
    finally:
        blocker.rollback()
        blocker.close()
    journal.flush()
    with store._lock:
        row = obs.snapshot(store._db, journal=journal)['operations'][0]
    assert row['status'] == 'unknown' and row['attempts'][0]['status'] == 'unknown'
    assert sum(event['event'] == 'operation.finished' for event in row['events']) == 1
    assert any(event['event'] == 'attempt.late_result' for event in row['events'])


def test_queue_has_bounded_capacity_and_reports_loss(recording, monkeypatch):
    _, journal, op, _ = recording
    monkeypatch.setattr(obs, 'MAX_PENDING_WRITES', 3)
    assert journal._flush_lock.acquire(blocking=False)
    try:
        for _ in range(9):
            op.finish('succeeded')
        health = journal.health()
        assert health['pending_writes'] == 3 and health['dropped_writes'] == 6
        assert not health['complete']
    finally:
        journal._flush_lock.release()
    journal.flush()
    assert journal.health()['pending_writes'] == 0
    assert not journal.health()['complete'], 'Recovery must not conceal already dropped metadata.'


def test_flush_budget_is_bounded_and_replay_is_idempotent(recording, monkeypatch):
    store, journal, op, _ = recording
    monkeypatch.setattr(obs, 'MAX_FLUSH_WRITES', 2)
    assert journal._flush_lock.acquire(blocking=False)
    try:
        for _ in range(4):
            op.finish('succeeded')
    finally:
        journal._flush_lock.release()
    assert journal.flush() == 2 and journal.health()['pending_writes'] == 2
    assert journal.flush() == 2 and journal.health()['pending_writes'] == 0
    assert store.query("SELECT COUNT(*) FROM platform_observation_events WHERE event='operation.finished'")[0][0] == 1


def test_expired_dispatch_metadata_does_not_make_timeout_look_undispatched(recording, monkeypatch):
    store, journal, op, attempt = recording
    assert journal._flush_lock.acquire(blocking=False)
    try:
        attempt.dispatch()
        monkeypatch.setattr(obs, 'MAX_PENDING_AGE', 0)
        assert journal.health()['pending_writes'] == 0
        assert journal.health()['dropped_writes'] == 1
    finally:
        journal._flush_lock.release()
    monkeypatch.setattr(obs, 'MAX_PENDING_AGE', 60)
    op.finish('timed_out', 'UPSTREAM_TIMEOUT')
    with store._lock:
        row = obs.snapshot(store._db, journal=journal)['operations'][0]
    assert row['status'] == 'unknown' and row['attempts'][0]['status'] == 'unknown'
    assert not journal.health()['complete']


def test_close_releases_buffer_and_never_starts_a_background_thread(recording, monkeypatch):
    _, journal, op, attempt = recording
    monkeypatch.setattr(threading, 'Thread', lambda *a, **k: pytest.fail('A metadata retry must not spawn a thread.'))
    assert journal._flush_lock.acquire(blocking=False)
    try:
        attempt.dispatch()
        op.finish('succeeded')
        journal.close()
    finally:
        journal._flush_lock.release()
    assert journal.health()['closed'] and journal.health()['pending_writes'] == 0
    assert journal.health()['dropped_writes'] == 2
    attempt.finish('succeeded')
    assert journal.flush() == 0 and journal.health()['pending_writes'] == 0


def test_journal_initialization_cannot_commit_an_existing_business_transaction():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE business(value TEXT)')
    db.execute("INSERT INTO business VALUES('uncommitted')")
    store = SimpleNamespace(_db=db, _lock=threading.RLock(), _path=':memory:')
    try:
        journal = obs.Journal(store)
        assert db.in_transaction and not journal.enabled
        db.rollback()
        assert db.execute('SELECT COUNT(*) FROM business').fetchone()[0] == 0
    finally:
        db.close()


def test_admin_endpoint_flushes_before_snapshot_and_exposes_only_recording_counters(admin):
    store, client = admin
    journal = obs.journal_for(store)
    op = journal.begin('execution', 'managed')
    assert journal._flush_lock.acquire(blocking=False)
    try:
        op.finish('succeeded')
        assert journal.health()['pending_writes'] == 1
    finally:
        journal._flush_lock.release()
    response = client.get('/admin/api/observations', headers=H)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['recording']['process_local'] is True
    assert result['recording']['pending_writes'] == 0 and result['recording']['complete']
    assert result['counts']['execution'] == {'succeeded': 1}
    assert result['coverage_complete'] is False
    for private in ('visitor_id', 'Bearer', 'api_key', store._path):
        assert private not in json.dumps(result['recording'])


def test_existing_workflow_scheduler_recovers_metadata_without_a_new_request(recording):
    from agent_market.gateway.server import Scheduler
    store, journal, op, _ = recording
    assert journal._flush_lock.acquire(blocking=False)
    try:
        op.finish('succeeded')
    finally:
        journal._flush_lock.release()
    scheduler = Scheduler(SimpleNamespace(), SimpleNamespace(store=store), 900)
    scheduler.workflows = SimpleNamespace(run_due=scheduler.stop_event.set)
    # Execute one existing scheduler tick synchronously; no listener/thread is started.
    scheduler._run_workflows()
    assert journal.health()['pending_writes'] == 0
    assert store.query('SELECT status FROM platform_operations WHERE id=?', (op.id,))[0][0] == 'succeeded'


def test_lifespan_shutdown_drains_and_closes_metadata_without_starting_a_server():
    from tests.test_gateway import GW_World
    world = GW_World()
    journal = obs.journal_for(world.store)
    op = journal.begin('execution', 'managed')
    async def lifecycle():
        async with world.app.router.lifespan_context(world.app):
            assert journal._flush_lock.acquire(blocking=False)
            try:
                op.finish('succeeded')
            finally:
                journal._flush_lock.release()
            assert journal.health()['pending_writes'] == 1
    try:
        asyncio.run(lifecycle())
        assert journal.health()['closed'] and journal.health()['pending_writes'] == 0
        assert world.store.query('SELECT status FROM platform_operations WHERE id=?', (op.id,))[0][0] == 'succeeded'
    finally:
        world.http.close()
        world.store._db.close()
