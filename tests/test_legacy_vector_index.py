"""Pure model/corpus/vector contracts and real isolated sqlite-vec lifecycle."""
from dataclasses import replace
import math
import sqlite3
import struct
import threading

import pytest

import agent_market.legacy_vector_index as module
from agent_market.legacy_vector_index import (
    ModelDescriptor, VectorError, VectorIndex, install, lookup, register,
    source, validate_vector,
)


def row(number=1, **changes):
    return dict(id=number, kind='mcp', source='synthetic-vector', name='Synthetic reader',
        url='https://synthetic.example/mcp', description='Current reference lookup', category='news',
        active=1, health_status='healthy', price_usdc=0, probe_latency_ms=5,
        eval_grade='B', eval_score=80.0, eval_security='ok', trial_ok=0,
        payers_30d=0, calls_30d=0) | changes


def insert(db, value):
    fields = tuple(value)
    db.execute('INSERT INTO resources(' + ','.join(fields) + ')VALUES(' + ','.join('?' for _ in fields) + ')',
               tuple(value.values()))


@pytest.fixture
def world():
    from agent_market.gateway.rag import ensure_vec_table
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.row_factory = sqlite3.Row
    assert ensure_vec_table(db), 'Actual installed sqlite-vec is required; no silent skip.'
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,source TEXT,name TEXT,url TEXT,
        description TEXT,category TEXT,active INTEGER,health_status TEXT,price_usdc INTEGER,
        probe_latency_ms INTEGER,eval_grade TEXT,eval_score REAL,eval_security TEXT,
        trial_ok INTEGER,payers_30d INTEGER,calls_30d INTEGER)''')
    db.execute('BEGIN IMMEDIATE')
    install(db)
    db.commit()
    with db:
        insert(db, row())
    index = register(db, threading.RLock())
    try:
        yield db, index, ModelDescriptor('synthetic-embedding')
    finally:
        db.close()


def rejected(call, code):
    with pytest.raises(VectorError) as caught:
        call()
    assert caught.value.code == code


def vector():
    return [1.0] + [0.0] * 767


def test_model_identity_binds_every_declared_setting_without_weights_attestation():
    model = ModelDescriptor('synthetic-embedding')
    assert model.digest == ModelDescriptor('synthetic-embedding').digest
    assert model.digest != replace(model, revision='second-declared-revision').digest
    assert model.digest != replace(model, model_id='other-synthetic-embedding').digest
    assert model.digest != replace(model, weights_digest='a' * 64).digest
    assert repr(model) == '<VectorModel declared-private>'


@pytest.mark.parametrize('field,value', [
    ('dimension', True), ('dimension', 767), ('dimension', 769), ('model_id', ''),
    ('model_id', 'bad\nmodel'), ('revision', ''), ('float_format', 'float64'),
    ('metric', 'euclidean'), ('recipe_id', 'unreviewed-recipe'), ('weights_digest', 'not-a-digest'),
])
def test_only_the_explicit_current_768_float32_cosine_profile_is_supported(field, value):
    rejected(lambda: ModelDescriptor(**({'model_id': 'synthetic'} | {field: value})), 'invalid_model')


def test_recipe_has_separate_raw_source_and_outbound_corpus_hashes():
    first = source(row())
    changed_binding = source(row(url='https://other-synthetic.example/mcp'))
    assert first.source_hash != changed_binding.source_hash
    assert first.corpus_hash == changed_binding.corpus_hash and first.text == changed_binding.text
    changed_text = source(row(description='Other reference material'))
    assert first.corpus_hash != changed_text.corpus_hash
    assert repr(first) == '<VectorSource private>'
    assert 'https://' not in first.text and 'synthetic.example' not in first.text


@pytest.mark.parametrize('value', [
    'Useful password=synthetic-secret reference',
    'Useful password%3Dsynthetic-secret reference',
    'Useful password%253Dsynthetic-secret reference',
    'Useful https://user:synthetic-secret@provider.example/mcp?token=synthetic-secret reference',
    'Useful https%253A%252F%252Fprovider.example%252Fmcp%253Fapi_key%253Dsynthetic-secret reference',
    'Useful private-user@example.invalid reference',
])
def test_known_encoded_credentials_connection_urls_and_emails_are_not_embedding_corpus(value):
    prepared = source(row(description=value))
    assert all(text not in prepared.text for text in ('synthetic-secret', 'provider.example', 'private-user@'))
    assert 'Useful' in prepared.text and 'reference' in prepared.text


def test_recipe_omits_tools_auth_payload_and_observation_metrics():
    prepared = source(row() | {'auth_info': 'raw-private-auth', 'usage_tools': 'raw-private-tool',
                               'eval_info': 'raw-private-profile', 'health_n_24h': 999})
    assert prepared.text == source(row()).text
    assert all(value not in prepared.text for value in ('raw-private', '999'))


@pytest.mark.parametrize('value', [
    '{"token":"synthetic-secret"}',
    'Useful {"password": "synthetic-secret with spaces"} reference',
    'Useful {&quot;access_token&quot;: &quot;synthetic-secret&quot;} reference',
    'Useful {"client_secret": "synthetic-secret\\\"suffix"} reference',
    'Useful file:///Users/synthetic-private/config.json reference',
    r'Useful C:\Users\synthetic-private\config.json reference',
    'Useful /Users/synthetic-private/config.json reference',
])
def test_known_quoted_credentials_and_private_local_paths_are_not_embedding_corpus(value):
    prepared = source(row(description=value))
    assert 'synthetic-secret' not in prepared.text
    assert 'synthetic-private' not in prepared.text


@pytest.mark.parametrize('metric', ['l2', 'l1'])
def test_install_refuses_native_vector_table_with_a_different_distance_metric(metric):
    from agent_market.gateway.rag import load_sqlite_vec
    db = sqlite3.connect(':memory:')
    assert load_sqlite_vec(db)
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,name TEXT,description TEXT,category TEXT,
        active INTEGER,kind TEXT,url TEXT,health_status TEXT,eval_security TEXT)''')
    db.execute('CREATE VIRTUAL TABLE vec_resources USING vec0(rowid INTEGER PRIMARY KEY, '
               'embedding float[768] distance_metric=' + metric + ')')
    try:
        db.execute('BEGIN IMMEDIATE')
        rejected(lambda: install(db), 'invalid_schema')
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize('values', [
    [], [1.0] * 767, [1.0] * 769, [False] + [1.0] * 767,
    ['1'] + [1.0] * 767, [math.nan] + [1.0] * 767, [math.inf] + [1.0] * 767,
    [3.5e38] + [1.0] * 767, [10**1000] + [1.0] * 767,
    [0.0] * 768, [1e-100] * 768,
    [1e-30] * 768, [1e38] * 768,
])
def test_vector_guard_rejects_wrong_shape_nonfinite_boolean_overflow_and_rounded_zero(values):
    rejected(lambda: validate_vector(values, ModelDescriptor('synthetic')), 'invalid_vector')


def test_vector_bytes_are_exact_little_endian_finite_float32_with_hash():
    blob, digest = validate_vector(vector(), ModelDescriptor('synthetic'))
    assert len(blob) == 3072 and struct.unpack('<f', blob[:4]) == (1.0,)
    assert len(digest) == 64 and len(set(blob[4:])) == 1


@pytest.mark.parametrize('scale', [1e-15, 1e13])
def test_accepted_conservative_norms_have_finite_real_native_cosine_distances(world, scale):
    db, _, model = world
    blob, _ = validate_vector([scale] * 768, model)
    unit, _ = validate_vector(vector(), model)
    actual = db.execute('SELECT vec_distance_cosine(?,?),vec_distance_cosine(?,?)',
                        (blob, blob, blob, unit)).fetchone()
    assert all(math.isfinite(value) for value in actual)
    assert actual[0] == pytest.approx(0.0, abs=1e-6)


def test_native_job_publication_and_exact_ack_current_provenance(world):
    db, index, model = world
    claim = index.claim_batch(model)[0]
    assert repr(claim) == '<VectorClaim private>' and lookup(db) is index
    assert db.execute('SELECT descriptor_hash FROM legacy_vector_control').fetchone()[0] == model.digest
    assert index.publish(claim, vector(), model) == 'indexed'
    assert not db.execute('SELECT * FROM vec_outbox').fetchall()
    assert index.current_ids([1], model) == {1}
    assert index.inspect(claim.job_id, model) == {'profile': module.PROFILE, 'found': True,
        'status': 'indexed', 'current': True, 'replay_performed': False}
    assert index.publish(claim, vector(), model) == 'stale'


def test_queue_same_source_replacement_keeps_prior_blob_until_a_valid_atomic_publish(world):
    db, index, model = world
    original = index.claim_batch(model)[0]
    assert index.publish(original, vector(), model) == 'indexed'
    previous = bytes(db.execute('SELECT embedding FROM vec_resources WHERE rowid=1').fetchone()[0])
    with db:
        db.execute("INSERT OR REPLACE INTO vec_outbox VALUES(1,100,'synthetic-repeat')")
    replacement = index.claim_batch(model)[0]
    assert index.current_ids([1], model) == set(), 'Old dense hit is hidden immediately by the new head.'
    rejected(lambda: index.publish(replacement, [0.0] * 768, model), 'invalid_vector')
    assert bytes(db.execute('SELECT embedding FROM vec_resources WHERE rowid=1').fetchone()[0]) == previous
    assert index.fail(replacement, model, 'invalid_vector') == 'failed'
    assert db.execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0] == 1


def test_read_current_descriptor_is_checked_even_if_old_provenance_still_exists(world):
    db, index, model = world
    claim = index.claim_batch(model)[0]
    index.publish(claim, vector(), model)
    with db:
        db.execute('UPDATE legacy_vector_control SET descriptor_hash=? WHERE id=1', (ModelDescriptor('other').digest,))
    assert not index.current_ids([1], model)


@pytest.mark.parametrize('change', ['profile', 'extra_singleton'])
def test_publish_rechecks_exact_singleton_model_control_after_claim(world, change):
    db, index, model = world
    claim = index.claim_batch(model)[0]
    with db:
        if change == 'profile':
            db.execute("UPDATE legacy_vector_control SET profile='different-private-profile' WHERE id=1")
        else:
            db.execute('INSERT INTO legacy_vector_control SELECT 2,profile,descriptor_hash,descriptor_json '
                       'FROM legacy_vector_control WHERE id=1')
    assert index.publish(claim, vector(), model) == 'stale'
    assert db.execute('SELECT COUNT(*) FROM vec_resources').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0] == 1


def test_backfill_progresses_past_an_already_current_low_id(world):
    db, index, model = world
    claim = index.claim_batch(model)[0]
    index.publish(claim, vector(), model)
    with db:
        insert(db, row(41, name='Later synthetic reader'))
        db.execute('DELETE FROM vec_outbox WHERE resource_id=41')
        db.execute('DELETE FROM legacy_vector_heads WHERE resource_id=41')
        db.execute('DELETE FROM legacy_vector_jobs WHERE resource_id=41')
    assert index.ensure_jobs(model, limit=1) == 1
    assert index.claim_batch(model, limit=1)[0].resource_id == 41


def test_expired_claim_reclaim_changes_fence_and_three_crashes_become_explicit_failed(world, monkeypatch):
    db, index, model = world
    clock = [1000.0]
    monkeypatch.setattr(module, '_now', lambda: clock[0])
    first = index.claim_batch(model)[0]
    clock[0] = first.lease_until + 1
    second = index.claim_batch(model)[0]
    assert second.fence > first.fence and index.publish(first, vector(), model) == 'stale'
    clock[0] = second.lease_until + 1
    third = index.claim_batch(model)[0]
    clock[0] = third.lease_until + 1
    assert index.claim_batch(model) == ()
    state = db.execute('SELECT status,error_code FROM legacy_vector_jobs WHERE job_id=?', (third.job_id,)).fetchone()
    assert tuple(state) == ('failed', 'lease_exhausted')
    assert db.execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0] == 1


def test_install_does_not_commit_caller_seed_and_constructor_refuses_uncommitted_work():
    from agent_market.gateway.rag import ensure_vec_table
    db = sqlite3.connect(':memory:')
    assert ensure_vec_table(db)
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,name TEXT,description TEXT,category TEXT,
        active INTEGER,kind TEXT,url TEXT,health_status TEXT,eval_security TEXT)''')
    db.execute('BEGIN IMMEDIATE')
    install(db)
    assert db.in_transaction
    rejected(lambda: VectorIndex(db, threading.RLock()), 'caller_transaction')
    db.rollback()
    assert not db.execute("SELECT name FROM sqlite_schema WHERE name='legacy_vector_jobs'").fetchall()
    db.close()


def test_wrong_direct_snapshot_cannot_be_rebound_to_the_current_resource(world):
    db, index, model = world
    requested = [{key: row()[key] for key in ('id', 'name', 'description', 'category')}]
    with db:
        db.execute("UPDATE resources SET description='Changed before admission' WHERE id=1")
    assert not index.claim_batch(model, expected_resources=requested)
    assert not db.execute('SELECT * FROM legacy_vector_provenance').fetchall()


def test_terminal_history_gc_is_bounded_and_never_removes_current_head(world, monkeypatch):
    db, index, model = world
    old = index.claim_batch(model)[0]
    index.publish(old, vector(), model)
    with db:
        db.execute("UPDATE legacy_vector_jobs SET finished=1 WHERE job_id=?", (old.job_id,))
        db.execute("INSERT OR REPLACE INTO vec_outbox VALUES(1,2,'newer-intent')")
    current = db.execute('SELECT job_id FROM legacy_vector_heads').fetchone()[0]
    monkeypatch.setattr(module, '_now', lambda: 1000000.0)
    assert index.claim_batch(model)[0].job_id == current
    # Old provenance still references the retained blob, so its history is kept.
    assert db.execute('SELECT COUNT(*) FROM legacy_vector_jobs WHERE job_id=?', (old.job_id,)).fetchone()[0] == 1


def test_retention_sweep_pauses_after_a_short_batch_and_keeps_going_while_full(world, monkeypatch):
    db, index, model = world
    clock = [1000000.0]
    monkeypatch.setattr(module, '_now', lambda: clock[0])

    def history(count, start=0):
        with db:
            db.executemany("INSERT INTO legacy_vector_jobs(job_id,resource_id,generation,status,created,finished) "
                           "VALUES(?,1,1,'superseded',1,1)", [('lvj_%032x' % (start + n),) for n in range(count)])

    def left():
        return db.execute("SELECT COUNT(*) FROM legacy_vector_jobs WHERE status='superseded' AND finished=1").fetchone()[0]

    history(600)
    index.claim_batch(model)
    assert left() == 100  # a full batch of 500
    index.claim_batch(model)
    assert left() == 0  # full batches keep sweeping on the next claim
    history(3, start=1000)
    index.claim_batch(model)
    assert left() == 3  # the last batch was short: paused
    clock[0] += module.RETENTION_PAUSE - 1
    index.claim_batch(model)
    assert left() == 3
    clock[0] += 2
    index.claim_batch(model)
    assert left() == 0
