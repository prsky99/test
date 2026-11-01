"""Bounded anonymous visit writes on actual isolated SQLite transactions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import math
import sqlite3
import threading
import time

from fastapi.testclient import TestClient
import pytest

from agent_market.concierge import memory
from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway import admin_auth, store as store_module


@pytest.fixture
def hit_book(monkeypatch):
    # Do not issue a bootstrap account or touch a configured database.
    monkeypatch.setattr(store_module, 'init_admin_auth_db', lambda db: db.executescript(admin_auth.ADMIN_SCHEMA))
    store = store_module.Store()
    book = memory.VisitorBook(store)
    yield book
    assert book.close()
    store._db.close()


def hit_id(index):
    return memory.fingerprint('synthetic-' + str(index), 'synthetic-client')


def test_request_admission_never_waits_for_store_and_preserves_request_order(hit_book):
    book = hit_book
    token = 'vt_' + 'x' * 32
    first_before = time.time()
    with book.store.tx():
        started = time.monotonic()
        assert book.record_hit(hit_id(1), 'Synthetic ' + token + '\n' + 'a' * 2000, '/first?secret=omitted')
        assert time.monotonic() - started < 0.1
        first_after = time.time()
        time.sleep(0.02)
        second_before = time.time()
        assert book.record_hit(hit_id(1), 'Second client', '/second#omitted')
        second_after = time.time()
        assert not book.flush_hits(0.02)
    assert book.flush_hits()
    row = dict(book.store.query('SELECT * FROM agent_hits')[0])
    assert first_before <= row['first_seen'] <= first_after
    assert second_before <= row['last_seen'] <= second_after
    assert row['hits'] == 2 and row['last_path'] == '/second'
    assert len(row['user_agent']) <= 300 and '\n' not in row['user_agent'] and token not in row['user_agent']
    assert '[REDACTED_VISITOR_TOKEN]' in row['user_agent']
    assert book.store.query('SELECT COUNT(*) AS n FROM agent_visitors')[0]['n'] == 0


def test_queue_saturation_is_bounded_newest_rejected_and_shutdown_drains(hit_book, monkeypatch):
    book = hit_book
    book._hit_queue = memory.queue.Queue(maxsize=3)
    entered, release = threading.Event(), threading.Event()
    write = book._write_hit_batch

    def blocked(batch):
        entered.set()
        assert release.wait(5)
        write(batch)

    monkeypatch.setattr(book, '_write_hit_batch', blocked)
    try:
        assert book.record_hit(hit_id(0), 'Synthetic', '/')
        assert entered.wait(2)
        assert all(book.record_hit(hit_id(index), 'Synthetic', '/') for index in (1, 2, 3))
        started = time.monotonic()
        assert not book.record_hit(hit_id(4), 'Synthetic', '/')
        assert time.monotonic() - started < 0.1
        assert book.hit_diagnostics()['pending'] == 4
        assert not book.flush_hits(0.01)
        assert not book.close(0.01)
        assert not book.record_hit(hit_id(5), 'Synthetic', '/')
    finally:
        release.set()
    assert book.close()
    counts = book.hit_diagnostics()
    assert counts == dict(accepted=4, persisted=4, unconfirmed=0, rejected_full=1,
                          rejected_closed=1, rejected_invalid=0, rejected_start=0,
                          pending=0, closed=True, worker_running=False)
    assert book.close(0)
    assert len(book.store.query('SELECT * FROM agent_hits')) == 4


def test_rolled_back_batch_is_reported_without_replay_and_next_batch_can_succeed(hit_book, monkeypatch, caplog):
    book = hit_book
    transaction = book.store.tx
    calls = []

    @contextmanager
    def failed_once():
        with transaction() as db:
            calls.append(threading.get_ident())
            yield db
            if len(calls) == 1:
                raise sqlite3.OperationalError('Synthetic private exception details must never be logged')

    monkeypatch.setattr(book.store, 'tx', failed_once)
    assert book.record_hit(hit_id(1), 'Synthetic private user agent', '/')
    assert book.flush_hits()
    assert book.store.query('SELECT * FROM agent_hits') == []
    assert book.hit_diagnostics()['unconfirmed'] == 1
    assert book.record_hit(hit_id(2), 'Synthetic', '/')
    assert book.flush_hits()
    assert len(calls) == 2 and all(owner != threading.get_ident() for owner in calls)
    assert book.hit_diagnostics()['persisted'] == 1
    assert len(book.store.query('SELECT * FROM agent_hits')) == 1
    assert 'write unconfirmed' in caplog.text
    assert 'Synthetic private' not in caplog.text and hit_id(1) not in caplog.text


def test_lost_commit_acknowledgement_is_unconfirmed_and_never_double_counted(hit_book, monkeypatch, caplog):
    book = hit_book
    transaction = book.store.tx
    attempts = []

    @contextmanager
    def commit_acknowledgement_lost():
        attempts.append(1)
        with transaction() as db:
            yield db
        raise RuntimeError('Synthetic secret connection details')

    monkeypatch.setattr(book.store, 'tx', commit_acknowledgement_lost)
    assert book.record_hit(hit_id(1), 'Synthetic', '/')
    assert book.flush_hits() and book.flush_hits()
    assert book.close()
    assert attempts == [1]
    assert book.store.query('SELECT hits FROM agent_hits')[0]['hits'] == 1
    assert book.hit_diagnostics()['persisted'] == 0
    assert book.hit_diagnostics()['unconfirmed'] == 1
    assert 'Synthetic secret' not in caplog.text


def test_retention_and_hard_row_cap_drop_oldest_without_random_pruning(hit_book, monkeypatch):
    book = hit_book
    monkeypatch.setattr(memory, 'MAX_HITS', 3)
    now = time.time()
    with book.store.tx() as db:
        db.executemany('INSERT INTO agent_hits VALUES (?,?,?,?,1,?)', [
            (hit_id(0), 'Synthetic', now-memory.HIT_RETENTION-10, now-memory.HIT_RETENTION-10, '/expired'),
            *[(hit_id(index), 'Synthetic', now-100+index, now-100+index, '/older') for index in (1, 2, 3, 4)],
        ])
    assert book.record_hit(hit_id(5), 'Synthetic', '/newest')
    assert book.flush_hits()
    rows = [dict(row) for row in book.store.query('SELECT * FROM agent_hits ORDER BY last_seen DESC')]
    assert [row['fingerprint'] for row in rows] == [hit_id(5), hit_id(4), hit_id(3)]


def test_concurrent_producers_have_one_worker_and_exact_confirmed_hit_count(hit_book, monkeypatch):
    book = hit_book
    owners = set()
    write = book._write_hit_batch

    def record_owner(batch):
        owners.add(threading.get_ident())
        write(batch)

    monkeypatch.setattr(book, '_write_hit_batch', record_owner)
    with ThreadPoolExecutor(max_workers=8) as producers:
        accepted = list(producers.map(lambda index: book.record_hit(hit_id(index % 4), 'Synthetic', '/'), range(1000)))
    assert all(accepted) and book.close()
    assert sum(row['hits'] for row in book.store.query('SELECT hits FROM agent_hits')) == 1000
    assert len(owners) == 1
    assert book.hit_diagnostics()['persisted'] == 1000
    assert book.hit_diagnostics()['pending'] == book.hit_diagnostics()['unconfirmed'] == 0


def test_two_books_persisting_out_of_order_keep_earliest_and_latest_request_times(hit_book, monkeypatch):
    other = memory.VisitorBook(hit_book.store)
    entered, release = threading.Event(), threading.Event()
    write = hit_book._write_hit_batch

    def delayed(batch):
        entered.set()
        assert release.wait(5)
        write(batch)

    monkeypatch.setattr(hit_book, '_write_hit_batch', delayed)
    first_before = time.time()
    assert hit_book.record_hit(hit_id(1), 'Synthetic', '/earlier')
    assert entered.wait(2)
    first_after = time.time()
    time.sleep(0.01)
    last_before = time.time()
    try:
        assert other.record_hit(hit_id(1), 'Synthetic', '/later')
        assert other.close()
        last_after = time.time()
    finally:
        release.set()
        other.close()
    assert hit_book.close()
    row = dict(hit_book.store.query('SELECT * FROM agent_hits')[0])
    assert first_before <= row['first_seen'] <= first_after
    assert last_before <= row['last_seen'] <= last_after
    assert row['hits'] == 2 and row['last_path'] == '/later'


def test_thread_start_failure_does_not_admit_or_strand_a_hit(hit_book, monkeypatch):
    def fail_start(_thread):
        raise RuntimeError('Synthetic thread exhaustion')

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, 'start', fail_start)
        assert not hit_book.record_hit(hit_id(1), 'Synthetic', '/')
        assert hit_book.flush_hits(0)
        assert hit_book.hit_diagnostics()['rejected_start'] == 1
        assert hit_book.hit_diagnostics()['accepted'] == 0
    assert hit_book.record_hit(hit_id(1), 'Synthetic', '/')
    assert hit_book.flush_hits()


def test_idle_worker_releases_book_and_later_hit_starts_without_loss(hit_book, monkeypatch):
    monkeypatch.setattr(memory, 'HIT_WORKER_IDLE_SECONDS', 0.01)
    assert hit_book.record_hit(hit_id(1), 'Synthetic', '/first')
    assert hit_book.flush_hits()
    deadline = time.monotonic() + 2
    with hit_book._hit_condition:
        while hit_book.hit_diagnostics()['worker_running']:
            remaining = deadline - time.monotonic()
            assert remaining > 0
            hit_book._hit_condition.wait(remaining)
    assert hit_book.record_hit(hit_id(1), 'Synthetic', '/later')
    assert hit_book.close()
    assert hit_book.store.query('SELECT hits FROM agent_hits')[0]['hits'] == 2
    assert hit_book.hit_diagnostics()['persisted'] == 2


def test_invalid_fingerprint_or_input_never_enters_queue(hit_book):
    assert not hit_book.record_hit('synthetic-private-address', 'Synthetic', '/')
    assert not hit_book.record_hit(hit_id(1), object(), '/')
    assert not hit_book.record_hit(hit_id(1), 'Synthetic', object())
    assert hit_book.hit_diagnostics()['rejected_invalid'] == 3
    assert hit_book.hit_diagnostics()['worker_running'] is False
    assert hit_book.close(0)
    assert not hit_book.record_hit(hit_id(1), 'Synthetic', '/')
    assert hit_book.hit_diagnostics()['rejected_closed'] == 1


@pytest.mark.parametrize('timeout', [-1, math.inf, math.nan])
def test_hit_flush_and_close_refuse_unbounded_or_invalid_waits(hit_book, timeout):
    with pytest.raises(ValueError, match='invalid_hit_timeout'):
        hit_book.flush_hits(timeout)
    with pytest.raises(ValueError, match='invalid_hit_timeout'):
        hit_book.close(timeout)


@pytest.mark.parametrize('managed', [True, False])
def test_standalone_front_lifecycle_drains_only_when_it_owns_the_book(hit_book, managed):
    front = Front(hit_book.store)
    front.book = hit_book
    with TestClient(create_front_app(front, manage_book_lifecycle=managed)) as client:
        response = client.get('/', headers={'accept': 'application/json'})
        assert response.status_code == 200
        assert not hit_book.hit_diagnostics()['closed']
    assert hit_book.hit_diagnostics()['closed'] is managed
    assert hit_book.close()
    assert hit_book.hit_diagnostics()['persisted'] == 1
    assert hit_book.store.query('SELECT hits FROM agent_hits')[0]['hits'] == 1


def test_gateway_lifecycle_drains_its_shared_front_book_once(monkeypatch):
    from tests.test_gateway import GW_World
    world = GW_World()
    book = world.app.state.front.book
    closed = []
    close = book.close

    def counted_close():
        closed.append(1)
        return close()

    monkeypatch.setattr(book, 'close', counted_close)
    try:
        with TestClient(world.app):
            with TestClient(create_front_app(world.app.state.front, manage_book_lifecycle=False)) as client:
                assert client.get('/', headers={'accept': 'application/json'}).status_code == 200
            assert closed == []
        assert closed == [1]
        assert book.hit_diagnostics()['closed'] and book.hit_diagnostics()['persisted'] == 1
        assert world.store.query('SELECT hits FROM agent_hits')[0]['hits'] == 1
    finally:
        close()
        world.store._db.close()
