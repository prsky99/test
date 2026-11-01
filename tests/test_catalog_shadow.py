"""Aggregate-only shadow comparisons over caller-supplied synthetic snapshots."""
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from agent_market.catalog_index_outbox import CatalogIndexOutbox
from agent_market.catalog_shadow import compare_snapshots, SNAPSHOT_FIELDS, RESOURCE_FIELDS
from agent_market.catalog_writer import CatalogWriter
from agent_market.catalog_writer_fixtures import seed, command, operation, MODEL_HASH, URL
from agent_market.storage_adapter import SQLiteAdapter


TABLES = (
    ('resources', 'resources'), ('revisions', 'catalog_resource_revisions'),
    ('heads', 'catalog_index_heads'), ('jobs', 'catalog_index_jobs'),
    ('projections', 'catalog_index_projections'),
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def capture(db):
    """Fixed test-only table names; production comparison captures nothing."""
    return {name: tuple(dict(row) for row in db.execute('SELECT * FROM ' + table))
            for name, table in TABLES}


@pytest.fixture
def catalog():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    adapter = SQLiteAdapter(db)
    seed(adapter)
    writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
    writer.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=0)
    try:
        yield db, adapter, writer
    finally:
        db.close()


def compare(source, candidate, model=MODEL_HASH):
    return compare_snapshots(source, candidate, expected_model_hash=model)


def empty():
    return {name: () for name in SNAPSHOT_FIELDS}


def assert_incomplete(result, issue):
    assert result['complete'] is False and result['assessment'] == 'incomplete'
    assert result['issues'] == [issue]
    assert result['input_counts'] is None
    assert all(value is None for value in result['counts'].values())
    assert result['scope']['writes_performed'] == result['scope']['provider_calls'] == 0


def test_matching_private_writer_snapshots_compare_without_publication_or_capture(catalog):
    db, _adapter, _writer = catalog
    snapshot = capture(db)
    calls = []
    db.set_trace_callback(calls.append)
    try:
        result = compare(snapshot, snapshot)
    finally:
        db.set_trace_callback(None)
    assert not calls
    assert result['complete'] and result['assessment'] == 'bounded_comparison_complete'
    assert result['issues'] == []
    counts = result['counts']
    assert counts['matched_identity_rows'] == counts['normalized_registry_assessed_rows'] == 1
    assert counts['candidate_hash_assessed_rows'] == counts['current_job_pending_rows'] == 1
    assert counts['candidate_hash_mismatch_rows'] == counts['missing_revision_rows'] == 0
    assert result['scope']['atomic_capture_verified'] is False
    assert result['scope']['artifact_body_or_search_quality_assessed'] is False
    assert result['scope']['operating_cutover_authorized'] is False


def test_legacy_normalization_and_hash_replacement_are_explicit_not_recertified(catalog, monkeypatch):
    from agent_market import catalog_shadow
    db, _adapter, _writer = catalog
    candidate = capture(db)
    source = deepcopy(candidate)
    for name in SNAPSHOT_FIELDS[1:]:
        source[name] = ()
    row = source['resources'][0]
    row['content_hash'] = 'legacy-declared-hash-not-reconstructed'
    row['details'] = json.dumps(json.loads(row['details']), sort_keys=True)
    original = catalog_shadow._digest
    digested = []

    def observed(value):
        digested.append(value[0])
        return original(value)

    monkeypatch.setattr(catalog_shadow, '_digest', observed)
    result = compare(source, candidate)
    assert result['complete'] and result['assessment'] == 'differences_observed'
    assert result['counts']['legacy_normalization_changed_rows'] == 1
    assert result['counts']['normalized_registry_difference_rows'] == 0
    assert result['counts']['stored_hash_difference_rows'] == 1
    assert result['counts']['expected_profile_hash_replacement_rows'] == 1
    assert len(digested) == 2  # Candidate hash and corpus only; never source hash.
    assert result['scope']['legacy_hash_recomputed'] is False
    assert result['scope']['source_values_before_legacy_truncation_recoverable'] is False


def test_output_contains_no_raw_key_url_hash_credential_or_record(catalog):
    db, _adapter, _writer = catalog
    candidate = capture(db)
    source = deepcopy(candidate)
    source['resources'][0]['auth_info'] = 'Bearer synthetic-private-observation'
    before = deepcopy((source, candidate))
    result = compare(source, candidate)
    encoded = json.dumps(result, sort_keys=True)
    needles = (URL, MODEL_HASH, 'synthetic-private-token', 'synthetic:catalog:one',
               'synthetic-private-observation', candidate['resources'][0]['content_hash'],
               candidate['revisions'][0]['corpus_hash'], candidate['jobs'][0]['job_id'])
    assert all(value not in encoded for value in needles)
    assert result['counts']['observation_changed_rows'] == 1
    assert (source, candidate) == before


def test_identity_key_time_and_registry_observation_differences_are_separate(catalog):
    db, _adapter, _writer = catalog
    candidate = capture(db)
    source = deepcopy(candidate)
    old = source['resources'][0]
    old.update(key='synthetic:old-key', first_seen=1, last_seen=2, active=0, eval_grade='A')
    result = compare(source, candidate)
    for name in ('id_key_changed_rows', 'first_seen_changed_rows', 'last_seen_changed_rows',
                 'activity_changed_rows', 'observation_changed_rows', 'normalized_registry_difference_rows'):
        assert result['counts'][name] == 1
    assert result['scope']['provider_or_observation_truth_verified'] is False


def test_reidentified_key_is_not_mistaken_for_stable_resource(catalog):
    db, _adapter, _writer = catalog
    candidate = capture(db)
    source = deepcopy(candidate)
    source['resources'][0]['id'] = 99
    for name in SNAPSHOT_FIELDS[1:]:
        source[name] = ()
    result = compare(source, candidate)
    assert result['counts']['matched_identity_rows'] == 0
    assert result['counts']['missing_candidate_rows'] == result['counts']['added_candidate_rows'] == 1
    assert result['counts']['key_to_id_changed_rows'] == 1


@pytest.mark.parametrize('field,value', [('details', 'not-json'), ('name', 'x' * 201),
                                         ('networks', 'not-packed'), ('price_usdc', -1)])
def test_legacy_values_refused_by_new_profile_are_reported_without_adoption(catalog, field, value):
    db, _adapter, _writer = catalog
    candidate = capture(db)
    source = deepcopy(candidate)
    source['resources'][0][field] = value
    result = compare(source, candidate)
    assert result['complete'] and result['counts']['legacy_normalization_refused_rows'] == 1
    assert result['counts']['normalized_registry_assessed_rows'] == 0
    assert result['counts']['expected_profile_hash_replacement_rows'] == 0


@pytest.mark.parametrize('change,metric', [
    ('missing_revision', 'missing_revision_rows'), ('wrong_hash', 'candidate_hash_mismatch_rows'),
    ('wrong_profile', 'revision_mismatch_rows'), ('wrong_corpus', 'corpus_mismatch_rows'),
    ('missing_head', 'missing_head_rows'), ('wrong_head', 'head_mismatch_rows'),
    ('missing_job', 'current_job_missing_rows'), ('ambiguous_job', 'current_job_ambiguous_rows'),
    ('superseded_job', 'current_job_superseded_rows'),
])
def test_candidate_revision_hash_corpus_head_and_job_intent_are_checked(catalog, change, metric):
    db, _adapter, _writer = catalog
    source = capture(db)
    candidate = deepcopy(source)
    if change == 'missing_revision': candidate['revisions'] = ()
    elif change == 'wrong_hash': candidate['resources'][0]['content_hash'] = digest('different hash')
    elif change == 'wrong_profile': candidate['revisions'][0]['hash_profile'] = 'unsupported-profile'
    elif change == 'wrong_corpus': candidate['revisions'][0]['corpus_hash'] = digest('different corpus')
    elif change == 'missing_head': candidate['heads'] = ()
    elif change == 'wrong_head': candidate['heads'][0]['revision'] += 1
    elif change == 'missing_job': candidate['jobs'] = ()
    elif change == 'ambiguous_job':
        extra = deepcopy(candidate['jobs'][0]); extra['job_id'] = 'cij_' + '0' * 64
        candidate['jobs'] += (extra,)
    elif change == 'superseded_job': candidate['jobs'][0]['state'] = 'superseded'
    result = compare(source, candidate)
    assert result['complete'] and result['assessment'] == 'differences_observed'
    assert result['counts'][metric] == 1


def test_expected_model_is_explicit_and_not_inferred_from_own_head(catalog):
    db, _adapter, _writer = catalog
    snapshot = capture(db)
    result = compare(snapshot, snapshot, model=digest('different expected model'))
    assert result['counts']['model_mismatch_rows'] == 1
    assert 'different expected model' not in json.dumps(result)


def test_indexed_and_failed_states_are_honest_metadata_not_artifact_evidence(catalog):
    db, adapter, _writer = catalog
    queue = CatalogIndexOutbox(adapter)
    claim = queue.claim('synthetic-worker', now=1)
    queue.complete(claim, digest('synthetic-artifact-metadata'), now=2)
    good = capture(db)
    result = compare(good, good)
    assert result['counts']['current_job_indexed_rows'] == 1
    assert result['counts']['current_projection_missing_rows'] == 0
    missing = deepcopy(good); missing['projections'] = ()
    assert compare(good, missing)['counts']['current_projection_missing_rows'] == 1
    wrong = deepcopy(good); wrong['projections'][0]['projection_hash'] = digest('wrong projection')
    assert compare(good, wrong)['counts']['current_projection_mismatch_rows'] == 1
    failed = deepcopy(good); failed['jobs'][0]['state'] = 'failed'
    result = compare(good, failed)
    assert result['counts']['current_job_failed_rows'] == 1
    assert result['counts']['projection_without_indexed_job_rows'] == 1
    assert result['scope']['artifact_body_or_search_quality_assessed'] is False


def test_historical_projection_and_superseded_jobs_do_not_become_current(catalog):
    db, adapter, writer = catalog
    queue = CatalogIndexOutbox(adapter)
    queue.complete(queue.claim('synthetic-worker', now=1), digest('old artifact'), now=2)
    writer.upsert(command(), operation_id=operation(2), expected_revision=1, observed_at=3)
    snapshot = capture(db)
    result = compare(snapshot, snapshot)
    assert result['assessment'] == 'bounded_comparison_complete'
    assert result['input_counts']['candidate']['projections'] == 1
    assert result['counts']['current_job_pending_rows'] == 1
    assert result['counts']['current_job_indexed_rows'] == 0
    assert result['counts']['projection_without_indexed_job_rows'] == 0


def test_orphan_metadata_is_counted_and_not_ignored(catalog):
    db, _adapter, _writer = catalog
    source = capture(db); candidate = deepcopy(source)
    extra = deepcopy(candidate['revisions'][0]); extra['resource_id'] = 99
    candidate['revisions'] += (extra,)
    result = compare(source, candidate)
    assert result['complete'] and result['counts']['orphan_metadata_rows'] == 1


def test_empty_comparison_does_not_claim_readiness():
    result = compare(empty(), empty())
    assert result['complete'] and result['assessment'] == 'empty_snapshots'
    assert result['counts']['matched_identity_rows'] == 0
    assert result['scope']['operating_cutover_authorized'] is False


@pytest.mark.parametrize('value', [None, 'postgresql://synthetic-private.invalid/catalog',
                                  '/private/synthetic-catalog.sqlite', [], object()])
def test_paths_dsn_and_arbitrary_objects_are_not_snapshot_sources(value):
    result = compare(value, empty())
    assert_incomplete(result, 'invalid_snapshot_shape')
    assert 'synthetic-private' not in json.dumps(result)


@pytest.mark.parametrize('problem,issue', [
    ('duplicate_id', 'duplicate_resource_id'), ('duplicate_key', 'duplicate_resource_key'),
    ('missing_field', 'missing_resource_fields'), ('duplicate_metadata', 'duplicate_metadata_identity'),
    ('nested_value', 'invalid_scalar'), ('nonfinite', 'invalid_scalar'),
    ('bool_scalar', 'invalid_scalar'), ('surrogate', 'invalid_scalar'),
    ('field_limit', 'field_limit'), ('value_limit', 'value_limit'),
    ('resource_limit', 'row_limit'), ('metadata_limit', 'row_limit'),
])
def test_incomplete_input_never_returns_zero_difference_assertions(catalog, problem, issue):
    db, _adapter, _writer = catalog
    source = capture(db); candidate = deepcopy(source)
    if problem == 'duplicate_id':
        extra = deepcopy(candidate['resources'][0]); extra['key'] = 'synthetic:other-key'
        candidate['resources'] += (extra,)
    elif problem == 'duplicate_key':
        extra = deepcopy(candidate['resources'][0]); extra['id'] = 99
        candidate['resources'] += (extra,)
    elif problem == 'missing_field': del candidate['resources'][0]['auth_info']
    elif problem == 'duplicate_metadata': candidate['heads'] += candidate['heads']
    elif problem == 'nested_value': candidate['resources'][0]['details'] = {'synthetic': True}
    elif problem == 'nonfinite': candidate['resources'][0]['last_seen'] = float('nan')
    elif problem == 'bool_scalar': candidate['resources'][0]['active'] = True
    elif problem == 'surrogate': candidate['resources'][0]['details'] = '\ud800'
    elif problem == 'field_limit': candidate['resources'][0].update({f'extra_{n}': 0 for n in range(65)})
    elif problem == 'value_limit': candidate['resources'][0]['details'] = 'x' * 16385
    elif problem == 'resource_limit': candidate['resources'] *= 101
    elif problem == 'metadata_limit': candidate['jobs'] *= 501
    assert_incomplete(compare(source, candidate), issue)


def test_cumulative_byte_and_total_row_bounds_are_explicit(catalog):
    db, _adapter, _writer = catalog
    source = capture(db)
    oversized = deepcopy(source)
    rows = []
    for index in range(100):
        row = deepcopy(source['resources'][0]); row.update(id=index + 1, key='synthetic:' + str(index))
        row.update(extra_a='x' * 16384, extra_b='y' * 16384)
        rows.append(row)
    oversized['resources'] = tuple(rows)
    assert_incomplete(compare(source, oversized), 'byte_limit')
    too_many = empty()
    too_many['resources'] = tuple({} for _ in range(100))
    too_many['revisions'] = tuple({} for _ in range(300))
    too_many['heads'] = tuple({} for _ in range(300))
    too_many['jobs'] = tuple({} for _ in range(301))
    assert_incomplete(compare(source, too_many), 'row_limit')


def test_invalid_expected_model_has_no_partial_or_sensitive_result(catalog):
    db, _adapter, _writer = catalog
    snapshot = capture(db)
    for value in ('token=synthetic-private-model', None, [], True):
        result = compare(snapshot, snapshot, model=value)
        assert_incomplete(result, 'invalid_model_hash')
        assert 'synthetic-private-model' not in json.dumps(result)


def test_resource_contract_matches_current_private_schema(catalog):
    db, _adapter, _writer = catalog
    assert set(RESOURCE_FIELDS) == set(capture(db)['resources'][0])
