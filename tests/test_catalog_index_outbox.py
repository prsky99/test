"""Revision/head/lease fencing over disposable explicit adapters only."""
from dataclasses import replace
import hashlib
import sqlite3
import threading

import pytest

from agent_market.catalog_index_outbox import (
    INDEX_SCHEMA, CatalogIndexOutbox, IndexOutboxError, enqueue,
)
from agent_market.storage_adapter import SQLiteAdapter, Statement, StorageError


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


MODEL = digest('synthetic-model-v1')
CORPUS = digest('synthetic-corpus-v1')
PROJECTION = digest('synthetic-projection-v1')


def initialize(connection):
    adapter = SQLiteAdapter(connection)
    with adapter.transaction() as session:
        for statement in INDEX_SCHEMA:
            session.execute(statement)
    return adapter


@pytest.fixture
def outbox():
    db = sqlite3.connect(':memory:')
    adapter = initialize(db)
    try:
        yield CatalogIndexOutbox(adapter), adapter, db
    finally:
        db.close()


def put(adapter, *, resource_id=1, revision=1, corpus_hash=CORPUS, model_hash=MODEL, now=1):
    with adapter.transaction() as session:
        return enqueue(session, resource_id=resource_id, revision=revision,
                       corpus_hash=corpus_hash, model_hash=model_hash, now=now)


def assert_code(code, action):
    with pytest.raises(IndexOutboxError) as caught:
        action()
    assert caught.value.code == code and str(caught.value) == code


def test_enqueue_owns_no_nested_transaction_and_rolls_back_with_writer(outbox):
    queue, adapter, db = outbox
    statement = Statement('fixture.registry', 'CREATE TABLE registry (id INTEGER PRIMARY KEY)',
                          'CREATE TABLE registry (id BIGINT PRIMARY KEY)')
    insert = Statement('fixture.registry_insert', 'INSERT INTO registry VALUES (?)',
                       'INSERT INTO registry VALUES (%s)')
    with adapter.transaction() as session:
        session.execute(statement)
    with pytest.raises(RuntimeError):
        with adapter.transaction() as session:
            session.execute(insert, (1,))
            job = enqueue(session, resource_id=1, revision=1, corpus_hash=CORPUS, model_hash=MODEL, now=1)
            assert job.state == 'pending'
            raise RuntimeError('Synthetic writer rollback')
    assert db.execute('SELECT COUNT(*) FROM registry').fetchone() == (0,)
    assert db.execute('SELECT COUNT(*) FROM catalog_index_heads').fetchone() == (0,)
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone() == (0,)
    assert queue.claim('worker', now=2) is None


def test_repeated_enqueue_does_not_reset_success_or_failure(outbox):
    queue, adapter, _db = outbox
    first = put(adapter)
    claim = queue.claim('worker', now=2)
    assert queue.fail(claim, 'index_failed', now=3) == 'failed'
    repeated = put(adapter, now=4)
    assert repeated.job_id == first.job_id and repeated.created == 1
    assert repeated.state == 'failed' and repeated.error_code == 'index_failed'
    assert queue.claim('worker', now=5) is None
    assert queue.indexed_projection(1, MODEL) is None


def test_superseded_worker_cannot_ack_new_work_or_overwrite_new_projection(outbox):
    queue, adapter, db = outbox
    old_job = put(adapter)
    old = queue.claim('worker-old', now=2)
    new_job = put(adapter, revision=2, corpus_hash=digest('new corpus'), now=3)
    assert queue.job(old_job.job_id).state == 'superseded'
    assert queue.complete(old, PROJECTION, now=4) == 'superseded'
    assert queue.fail(old, 'worker_cancelled', now=4) == 'superseded'
    assert queue.job(new_job.job_id).state == 'pending'
    assert queue.indexed_projection(1, MODEL) is None
    fresh = queue.claim('worker-new', now=5)
    assert fresh.job_id == new_job.job_id
    latest_hash = digest('new projection')
    assert queue.complete(fresh, latest_hash, now=6) == 'indexed'
    assert queue.complete(old, PROJECTION, now=7) == 'superseded'
    result = queue.indexed_projection(1, MODEL)
    assert (result.revision, result.corpus_hash, result.projection_hash, result.job_id) == (2, digest('new corpus'), latest_hash, new_job.job_id)
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone() == (2,)


def test_even_unchanged_corpus_new_revision_requires_new_index_ack(outbox):
    queue, adapter, _db = outbox
    old = put(adapter)
    claim = queue.claim('worker', now=2)
    assert queue.complete(claim, PROJECTION, now=3) == 'indexed'
    assert queue.indexed_projection(1, MODEL).revision == 1
    new = put(adapter, revision=2, now=4)
    assert new.job_id != old.job_id
    assert queue.job(old.job_id).state == 'superseded'
    assert queue.indexed_projection(1, MODEL) is None
    assert queue.complete(claim, PROJECTION, now=5) == 'superseded'
    assert queue.job(new.job_id).state == 'pending'


def test_same_resource_revision_cannot_select_two_active_models(outbox):
    queue, adapter, _db = outbox
    first = put(adapter)
    assert_code('revision_conflict', lambda: put(adapter, model_hash=digest('synthetic-model-v2')))
    claim = queue.claim('worker', now=2)
    assert claim.job_id == first.job_id
    assert queue.complete(claim, PROJECTION, now=3) == 'indexed'
    assert queue.indexed_projection(1, MODEL).revision == 1
    assert queue.indexed_projection(1, digest('synthetic-model-v2')) is None


@pytest.mark.parametrize('old_complete', [False, True])
def test_new_resource_revision_and_model_invalidate_old_model_work(outbox, old_complete):
    queue, adapter, _db = outbox
    old_job = put(adapter)
    old = queue.claim('old-model-worker', now=2)
    if old_complete:
        assert queue.complete(old, PROJECTION, now=3) == 'indexed'
    new_model = digest('synthetic-active-model-v2')
    latest = put(adapter, revision=2, model_hash=new_model, now=4)
    assert queue.indexed_projection(1, MODEL) is None
    assert queue.job(old_job.job_id).state == 'superseded'
    assert queue.complete(old, digest('stale old model result'), now=5) == 'superseded'
    fresh = queue.claim('active-model-worker', now=6)
    assert fresh.job_id == latest.job_id and fresh.model_hash == new_model
    assert queue.complete(fresh, PROJECTION, now=7) == 'indexed'
    assert queue.indexed_projection(1, new_model).revision == 2
    assert queue.indexed_projection(1, MODEL) is None


def test_lease_expiry_and_new_fence_refuse_old_worker(outbox):
    queue, adapter, _db = outbox
    put(adapter)
    old = queue.claim('same-worker', now=2, lease_seconds=2)
    assert queue.claim('other-worker', now=3) is None
    assert queue.complete(old, PROJECTION, now=4) == 'stale_claim'
    fresh = queue.claim('same-worker', now=4, lease_seconds=2)
    assert fresh.fence == old.fence + 1 and fresh.token != old.token
    assert queue.complete(old, PROJECTION, now=4.5) == 'stale_claim'
    assert queue.fail(old, 'index_failed', now=4.5) == 'stale_claim'
    assert queue.complete(fresh, PROJECTION, now=5) == 'indexed'
    assert queue.complete(fresh, digest('changed same claim'), now=5.5) == 'stale_claim'
    assert queue.indexed_projection(1, MODEL).projection_hash == PROJECTION


@pytest.mark.parametrize('change', [
    {'worker_id': 'someone-else'}, {'token': '0' * 32}, {'fence': 2},
    {'lease_until': 99}, {'revision': 2}, {'resource_id': 2},
    {'corpus_hash': digest('wrong corpus')}, {'model_hash': digest('wrong model')},
])
def test_claim_scope_is_bound_to_each_saved_dimension(outbox, change):
    queue, adapter, _db = outbox
    job = put(adapter)
    claim = queue.claim('worker', now=2)
    assert queue.complete(replace(claim, **change), PROJECTION, now=3) == 'stale_claim'
    assert queue.job(job.job_id).state == 'claimed'
    assert queue.indexed_projection(1, MODEL) is None
    assert queue.complete(claim, PROJECTION, now=4) == 'indexed'


def test_projection_failure_rolls_back_job_ack_and_can_be_reconciled(outbox):
    queue, adapter, db = outbox
    job = put(adapter)
    claim = queue.claim('worker', now=2)

    def authorizer(action, first, _second, _database, _source):
        if action == sqlite3.SQLITE_INSERT and first == 'catalog_index_projections':
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_authorizer(authorizer)
    try:
        with pytest.raises(StorageError) as caught:
            queue.complete(claim, PROJECTION, now=3)
        assert caught.value.code == 'statement_failed'
    finally:
        db.set_authorizer(None)
    assert queue.job(job.job_id).state == 'claimed'
    assert queue.indexed_projection(1, MODEL) is None
    assert queue.complete(claim, PROJECTION, now=4) == 'indexed'


@pytest.mark.parametrize('kwargs,code', [
    ({'revision': 1, 'corpus_hash': digest('different same revision')}, 'revision_conflict'),
    ({'revision': 1}, 'stale_revision'),
])
def test_revision_conflicts_leave_current_work_and_projection_unchanged(outbox, kwargs, code):
    queue, adapter, _db = outbox
    base_revision = 1 if code == 'revision_conflict' else 2
    job = put(adapter, revision=base_revision)
    claim = queue.claim('worker', now=2)
    assert queue.complete(claim, PROJECTION, now=3) == 'indexed'
    before = queue.indexed_projection(1, MODEL)
    assert_code(code, lambda: put(adapter, now=4, **kwargs))
    assert queue.indexed_projection(1, MODEL) == before
    assert queue.job(job.job_id).state == 'indexed'


@pytest.mark.parametrize('field,value', [
    ('resource_id', True), ('resource_id', 0), ('resource_id', 2**63),
    ('revision', False), ('revision', 0), ('revision', 1.0),
    ('corpus_hash', 'synthetic-private'), ('corpus_hash', 'A' * 64),
    ('model_hash', None), ('model_hash', []),
    ('now', True), ('now', -1), ('now', float('nan')), ('now', float('inf')),
    ('now', 2**10000),
])
def test_invalid_enqueue_values_fail_before_mutation_with_fixed_error(outbox, field, value):
    _queue, adapter, db = outbox
    assert_code('invalid_request', lambda: put(adapter, **{field: value}))
    assert db.execute('SELECT COUNT(*) FROM catalog_index_heads').fetchone() == (0,)
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone() == (0,)


@pytest.mark.parametrize('worker,lease,now', [
    ('bad worker', 30, 2), ('private\0value', 30, 2), ('x' * 65, 30, 2),
    (1, 30, 2), ('worker', True, 2), ('worker', 0, 2), ('worker', 61, 2),
    ('worker', 30, float('nan')), ('worker', 30, 2**53 - 1),
])
def test_invalid_claim_values_do_not_consume_pending_job(outbox, worker, lease, now):
    queue, adapter, _db = outbox
    job = put(adapter)
    assert_code('invalid_request', lambda: queue.claim(worker, now=now, lease_seconds=lease))
    assert queue.job(job.job_id).state == 'pending'


def test_fail_accepts_only_fixed_codes_and_retains_explicit_terminal_state(outbox):
    queue, adapter, _db = outbox
    job = put(adapter)
    claim = queue.claim('worker', now=2)
    for error in ('token=synthetic-private', '', None, {}, True):
        assert_code('invalid_request', lambda error=error: queue.fail(claim, error, now=3))
    assert queue.job(job.job_id).state == 'claimed'
    assert queue.fail(claim, 'invalid_projection', now=4) == 'failed'
    assert queue.job(job.job_id).error_code == 'invalid_projection'
    assert queue.claim('other', now=100) is None
    assert queue.indexed_projection(1, MODEL) is None


def test_private_representations_and_constructor_are_inert(outbox):
    queue, adapter, db = outbox
    calls = []
    db.set_trace_callback(calls.append)
    try:
        CatalogIndexOutbox(adapter)
        assert not calls
        for value in (db, ':memory:', 'postgresql://synthetic.invalid/private', None, object()):
            assert_code('invalid_request', lambda value=value: CatalogIndexOutbox(value))
    finally:
        db.set_trace_callback(None)
    job = put(adapter)
    claim = queue.claim('private-worker', now=2)
    assert repr(job) == '<IndexJob private>' and repr(claim) == '<IndexClaim private>'
    assert queue.complete(claim, PROJECTION, now=3) == 'indexed'
    assert repr(queue.indexed_projection(1, MODEL)) == '<IndexProjection private>'


def test_tampered_stored_metadata_is_not_returned_as_partial_success(outbox):
    queue, adapter, db = outbox
    job = put(adapter)
    db.execute('UPDATE catalog_index_jobs SET error_code=? WHERE job_id=?', ('synthetic-private-error', job.job_id))
    db.commit()
    assert_code('invalid_record', lambda: queue.job(job.job_id))


def test_concurrent_connections_have_one_live_claim(tmp_path):
    path = tmp_path / 'synthetic-outbox.sqlite'
    db = sqlite3.connect(path)
    adapter = initialize(db)
    put(adapter)
    db.close()
    barrier = threading.Barrier(4)
    claims, errors = [], []
    lock = threading.Lock()

    def worker(index):
        connection = sqlite3.connect(path, timeout=3)
        try:
            queue = CatalogIndexOutbox(SQLiteAdapter(connection))
            barrier.wait(timeout=3)
            result = queue.claim('worker-' + str(index), now=2)
            with lock:
                claims.append(result)
        except BaseException as exc:
            with lock:
                errors.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors and len(claims) == 4
    assert len([claim for claim in claims if claim is not None]) == 1
