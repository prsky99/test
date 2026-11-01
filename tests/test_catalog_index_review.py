"""Independent fenced artifact recovery, atomic replacement, and privacy checks."""
from dataclasses import replace
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from tests.test_catalog_writer_review import FaultConnection, command, logical_state, operation, seed


def components(db):
    from agent_market.catalog_index import ARTIFACT_SCHEMA, MODEL_HASH, CatalogIndex
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.catalog_writer import CatalogWriter
    adapter, _previous_writer = seed(db)
    with adapter.transaction() as session:
        for statement in ARTIFACT_SCHEMA:
            session.execute(statement)
    return SimpleNamespace(db=db, adapter=adapter, writer=CatalogWriter(adapter, model_hash=MODEL_HASH),
                           index=CatalogIndex(adapter), outbox=CatalogIndexOutbox(adapter))


@pytest.fixture
def indexed():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        yield components(db)
    finally:
        db.close()


def prepare(system, *, number=1, name='Public weather', description='Weather climate public research', expected_revision=0):
    written = system.writer.upsert(command(name=name, description=description), operation_id=operation(number),
                                   expected_revision=expected_revision, observed_at=number * 10)
    system.db.execute("UPDATE resources SET health_status='healthy',eval_security='ok' WHERE id=?", (written.resource_id,))
    system.db.commit()
    claim = system.outbox.claim('review-worker', now=number * 10 + 1, lease_seconds=30)
    assert claim is not None and claim.resource_id == written.resource_id
    artifact = system.index.build(claim)
    return written, claim, artifact


def test_replacement_hides_previous_revision_then_removes_old_terms(indexed):
    first, first_claim, first_artifact = prepare(indexed, name='Weather reader', description='Legacy weather reference')
    assert indexed.index.publish(first_claim, first_artifact, now=12) == 'indexed'
    assert len(indexed.index.search('legacy weather')) == 1
    second, second_claim, second_artifact = prepare(indexed, number=2, name='Climate reader',
        description='Current climate documentation', expected_revision=1)
    assert second.resource_id == first.resource_id and second.revision == 2
    assert indexed.index.artifact(first.resource_id) is None
    assert indexed.index.search('legacy weather') == ()
    assert indexed.index.publish(second_claim, second_artifact, now=22) == 'indexed'
    assert indexed.index.search('legacy weather') == ()
    assert len(indexed.index.search('current climate')) == 1


def test_stale_worker_cannot_delete_or_replace_current_artifact(indexed):
    first, old_claim, old_artifact = prepare(indexed)
    _new, new_claim, new_artifact = prepare(indexed, number=2, name='Current climate',
        description='Current climate documentation', expected_revision=1)
    assert indexed.index.publish(new_claim, new_artifact, now=22) == 'indexed'
    before = logical_state(indexed.db)
    assert indexed.index.publish(old_claim, old_artifact, now=23) in {'superseded', 'stale_claim'}
    assert logical_state(indexed.db) == before
    assert indexed.index.artifact(first.resource_id) == new_artifact
    assert len(indexed.index.search('current climate')) == 1


def test_expired_and_reclaimed_fence_cannot_ack_current_pending_artifact(indexed):
    written, expired, old_artifact = prepare(indexed)
    replacement = indexed.outbox.claim('replacement-worker', now=42, lease_seconds=30)
    assert replacement is not None and replacement.fence > expired.fence
    current_artifact = indexed.index.build(replacement)
    before = logical_state(indexed.db)
    assert indexed.index.publish(expired, old_artifact, now=43) == 'stale_claim'
    assert logical_state(indexed.db) == before
    assert indexed.index.artifact(written.resource_id) is None
    assert indexed.index.publish(replacement, current_artifact, now=44) == 'indexed'


def test_current_resource_safety_filters_apply_without_rebuilding_old_artifact(indexed):
    written, claim, artifact = prepare(indexed)
    assert indexed.index.publish(claim, artifact, now=12) == 'indexed'
    assert len(indexed.index.search('weather climate')) == 1
    for field, unsafe, restored in (('active', 0, 1), ('health_status', 'down', 'healthy'),
                                    ('health_status', 'retired', 'healthy'), ('eval_security', 'quarantine', 'ok')):
        indexed.db.execute('UPDATE resources SET ' + field + '=? WHERE id=?', (unsafe, written.resource_id))
        indexed.db.commit()
        assert indexed.index.search('weather climate') == ()
        indexed.db.execute('UPDATE resources SET ' + field + '=? WHERE id=?', (restored, written.resource_id))
        indexed.db.commit()
    assert len(indexed.index.search('weather climate')) == 1


@pytest.mark.parametrize('encoded', [
    'api%5Fkey%3Dsyntheticsecret',
    'api&#95;key&#61;syntheticsecret',
    'Bearer%20syntheticsecret',
    'api%26%2395%3Bkey%26%2361%3Bsyntheticsecret',
])
def test_decoding_cannot_reintroduce_known_credential_values_into_artifact(indexed, encoded):
    _written, claim, artifact = prepare(indexed, description='Weather reference ' + encoded)
    assert 'syntheticsecret' not in artifact.terms
    assert indexed.index.publish(claim, artifact, now=12) == 'indexed'
    assert indexed.index.search('syntheticsecret') == ()
    assert len(indexed.index.search('weather reference')) == 1


def test_corpus_omits_known_secrets_endpoints_and_email_without_network_or_registry_writes(indexed, monkeypatch):
    import socket
    import httpx
    from agent_market.capability_registry import Registry
    def forbidden(*_args, **_kwargs):
        pytest.fail('Indexing must not fetch providers or enrich registry evidence')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(Registry, 'current', forbidden)
    description = ('Weather reference. Call https://provider.example/project/tools?token=syntheticurlsecret. '
                   'Contact private.person@example.org. Bearer syntheticbearersecret api_key=syntheticapisecret')
    _written, claim, artifact = prepare(indexed, description=description)
    forbidden_terms = {'syntheticurlsecret', 'syntheticbearersecret', 'syntheticapisecret', 'provider',
                       'private', 'person', 'example', 'org', 'redacted'}
    assert not forbidden_terms.intersection(artifact.terms)
    assert indexed.index.publish(claim, artifact, now=12) == 'indexed'
    assert len(indexed.index.search('weather reference')) == 1
    for term in ('syntheticurlsecret', 'syntheticbearersecret', 'syntheticapisecret', 'person'):
        assert indexed.index.search(term) == ()
    assert 'synthetic' not in repr(artifact)


@pytest.mark.parametrize('tamper', ['hash', 'scope', 'self_consistent_body'])
def test_tampered_artifact_cannot_ack_job_or_materialize_terms(indexed, tamper):
    from agent_market.catalog_index import IndexArtifactError
    _written, claim, artifact = prepare(indexed)
    if tamper == 'hash':
        forged = replace(artifact, artifact_hash='0' * 64)
    elif tamper == 'scope':
        forged = replace(artifact, resource_id=999)
    else:
        document = json.loads(artifact.document)
        document['terms'] = sorted(set(document['terms']) | {'syntheticforgedterm'})
        text = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        forged = replace(artifact, document=text, artifact_hash=hashlib.sha256(text.encode('ascii')).hexdigest())
    before = logical_state(indexed.db)
    with pytest.raises(IndexArtifactError) as captured:
        indexed.index.publish(claim, forged, now=12)
    assert captured.value.code == 'invalid_artifact'
    assert logical_state(indexed.db) == before
    assert indexed.outbox.job(claim.job_id).state == 'claimed'


@pytest.mark.parametrize('column,value', [('document', '{"private":"synthetic-private-artifact"}'),
                                         ('artifact_hash', '0' * 64)])
def test_tampered_persisted_artifact_is_never_returned_as_valid_or_partial(indexed, column, value):
    from agent_market.catalog_index import IndexArtifactError
    written, claim, artifact = prepare(indexed)
    assert indexed.index.publish(claim, artifact, now=12) == 'indexed'
    indexed.db.execute('UPDATE catalog_index_artifacts SET ' + column + '=? WHERE resource_id=?', (value, written.resource_id))
    indexed.db.commit()
    before = logical_state(indexed.db)
    for action, empty in ((lambda: indexed.index.artifact(written.resource_id), None),
                          (lambda: indexed.index.search('weather climate'), ())):
        try:
            observed = action()
        except IndexArtifactError as error:
            assert error.code in {'invalid_artifact', 'invalid_record'}
            assert 'synthetic-private-artifact' not in str(error)
        else:
            assert observed == empty
    assert logical_state(indexed.db) == before


def test_forged_posting_cannot_create_a_match_outside_validated_artifact(indexed):
    from agent_market.catalog_index import IndexArtifactError
    written, claim, artifact = prepare(indexed)
    assert indexed.index.publish(claim, artifact, now=12) == 'indexed'
    indexed.db.execute('INSERT INTO catalog_index_terms VALUES (?,?)', (written.resource_id, 'forgedsecret'))
    indexed.db.commit()
    before = logical_state(indexed.db)
    with pytest.raises(IndexArtifactError) as captured:
        indexed.index.search('forgedsecret')
    assert captured.value.code == 'invalid_record'
    assert logical_state(indexed.db) == before


@pytest.mark.parametrize('prefix', ['INSERT INTO catalog_index_artifacts',
                                  'DELETE FROM catalog_index_terms',
                                  'INSERT INTO catalog_index_terms'])
def test_materialization_failure_rolls_back_ack_body_and_replacement_terms(prefix):
    from agent_market.storage_adapter import StorageError
    db = sqlite3.connect(':memory:', factory=FaultConnection)
    db.row_factory = sqlite3.Row
    try:
        system = components(db)
        _first, first_claim, first_artifact = prepare(system, description='Legacy weather reference')
        assert system.index.publish(first_claim, first_artifact, now=12) == 'indexed'
        written, claim, artifact = prepare(system, number=2, description='Current climate reference', expected_revision=1)
        before = logical_state(db)
        db.fail_prefix = prefix
        with pytest.raises(StorageError) as captured:
            system.index.publish(claim, artifact, now=22)
        db.fail_prefix = None
        assert captured.value.code == 'statement_failed' and db.failures == 1
        assert logical_state(db) == before
        assert system.outbox.job(claim.job_id).state == 'claimed'
        assert system.index.artifact(written.resource_id) is None
        assert system.index.publish(claim, artifact, now=23) == 'indexed'
        assert system.index.search('legacy weather') == ()
        assert len(system.index.search('current climate')) == 1
    finally:
        db.close()


def test_commit_unknown_keeps_new_artifact_and_postings_visible_to_fresh_reader(tmp_path):
    from agent_market.catalog_index import CatalogIndex
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class LostPublishAcknowledgement(sqlite3.Connection):
        armed = False
        commit_attempts = 0
        def commit(self):
            super().commit()
            if self.armed:
                self.commit_attempts += 1
                raise RuntimeError('synthetic-private-publish-acknowledgement')
    path = tmp_path / 'isolated-artifact.sqlite3'
    db = sqlite3.connect(path, factory=LostPublishAcknowledgement)
    db.row_factory = sqlite3.Row
    system = components(db)
    _first, first_claim, first_artifact = prepare(system, description='Legacy weather reference')
    assert system.index.publish(first_claim, first_artifact, now=12) == 'indexed'
    written, claim, artifact = prepare(system, number=2, description='Current climate reference', expected_revision=1)
    db.armed = True
    try:
        with pytest.raises(StorageError) as captured:
            system.index.publish(claim, artifact, now=22)
        assert captured.value.code == 'commit_unknown' and db.commit_attempts == 1
    finally:
        db.close()
    fresh = sqlite3.connect(path)
    try:
        adapter = SQLiteAdapter(fresh)
        recovered = CatalogIndex(adapter)
        assert recovered.artifact(written.resource_id) == artifact
        assert recovered.search('legacy weather') == ()
        assert len(recovered.search('current climate')) == 1
        assert CatalogIndexOutbox(adapter).job(claim.job_id).state == 'indexed'
        before = logical_state(fresh)
        assert recovered.publish(claim, artifact, now=23) == 'stale_claim'
        assert logical_state(fresh) == before
    finally:
        fresh.close()
