"""Bounded aggregate-only comparison of explicitly supplied private snapshots.

No database, path, environment, Store, index engine or source capture is opened.
The caller owns snapshot consistency. A completed analysis is not migration,
cutover, search parity, provider verification or authority evidence.
"""
import math
import re

from .catalog_repository import COLUMNS
from .catalog_writer import RegistryUpsert, WriterError, PROFILE as HASH_PROFILE
from .catalog_writer import CORPUS_PROFILE, _EXTRA, _OWNED, _normalized, _digest

PROFILE = 'bounded-catalog-shadow-v1'
SNAPSHOT_FIELDS = ('resources', 'revisions', 'heads', 'jobs', 'projections')
RESOURCE_FIELDS = COLUMNS + _EXTRA
MAX_RESOURCES = 100
MAX_METADATA_ROWS = 500
MAX_TOTAL_ROWS = 1000
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_VALUE_BYTES = 16384
MAX_ROW_FIELDS = 64
MAX_CELLS = 50000

_REVISION_FIELDS = frozenset(('resource_id', 'revision', 'content_hash', 'hash_profile', 'corpus_hash', 'model_hash', 'updated_at'))
_HEAD_FIELDS = frozenset(('resource_id', 'model_hash', 'revision', 'corpus_hash', 'updated'))
_JOB_FIELDS = frozenset(('job_id', 'resource_id', 'revision', 'corpus_hash', 'model_hash', 'state', 'projection_hash'))
_PROJECTION_FIELDS = frozenset(('resource_id', 'model_hash', 'revision', 'corpus_hash', 'projection_hash', 'job_id', 'indexed_at'))
_OBSERVATION_FIELDS = tuple(name for name in RESOURCE_FIELDS if name not in _OWNED and name not in ('id', 'key', 'first_seen', 'last_seen', 'active', 'content_hash'))
_METRICS = (
    'matched_identity_rows', 'missing_candidate_rows', 'added_candidate_rows',
    'id_key_changed_rows', 'key_to_id_changed_rows', 'first_seen_changed_rows',
    'last_seen_changed_rows', 'activity_changed_rows', 'observation_changed_rows',
    'legacy_normalization_refused_rows', 'legacy_normalization_changed_rows',
    'candidate_normalization_refused_rows', 'candidate_normalization_changed_rows',
    'normalized_registry_assessed_rows', 'normalized_registry_difference_rows', 'stored_hash_difference_rows',
    'expected_profile_hash_replacement_rows', 'candidate_hash_assessed_rows',
    'candidate_hash_mismatch_rows', 'missing_revision_rows', 'revision_mismatch_rows',
    'corpus_mismatch_rows', 'model_mismatch_rows', 'missing_head_rows',
    'head_mismatch_rows', 'current_job_missing_rows', 'current_job_ambiguous_rows',
    'current_job_pending_rows', 'current_job_claimed_rows', 'current_job_indexed_rows',
    'current_job_failed_rows', 'current_job_superseded_rows', 'current_projection_missing_rows',
    'current_projection_mismatch_rows', 'projection_without_indexed_job_rows',
    'orphan_metadata_rows',
)
_DIFFERENCES = tuple(name for name in _METRICS if name not in (
    'matched_identity_rows', 'candidate_hash_assessed_rows',
    'normalized_registry_assessed_rows', 'expected_profile_hash_replacement_rows',
    'current_job_pending_rows', 'current_job_claimed_rows', 'current_job_indexed_rows'))


class _Incomplete(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _positive(value):
    return type(value) is int and 1 <= value < 2**63


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _time(value):
    return type(value) in (int, float) and 0 <= value < 2**53 and math.isfinite(value)


def _copy_snapshot(value):
    if type(value) is not dict or len(value) != len(SNAPSHOT_FIELDS) or set(value) != set(SNAPSHOT_FIELDS):
        raise _Incomplete('invalid_snapshot_shape')
    result, rows, cells, size = {}, 0, 0, 0
    for name in SNAPSHOT_FIELDS:
        values = value[name]
        if type(values) is not tuple:
            raise _Incomplete('invalid_snapshot_shape')
        maximum = MAX_RESOURCES if name == 'resources' else MAX_METADATA_ROWS
        if len(values) > maximum:
            raise _Incomplete('row_limit')
        rows += len(values)
        if rows > MAX_TOTAL_ROWS:
            raise _Incomplete('row_limit')
        copied = []
        for row in values:
            if type(row) is not dict:
                raise _Incomplete('invalid_row_shape')
            if len(row) > MAX_ROW_FIELDS:
                raise _Incomplete('field_limit')
            cells += len(row)
            if cells > MAX_CELLS:
                raise _Incomplete('cell_limit')
            new = {}
            for key, item in row.items():
                if type(key) is not str or not key or len(key) > 64:
                    raise _Incomplete('invalid_row_shape')
                try:
                    size += len(key.encode('utf-8'))
                    if item is None:
                        size += 1
                    elif type(item) is str:
                        if len(item) > MAX_VALUE_BYTES:
                            raise _Incomplete('value_limit')
                        length = len(item.encode('utf-8'))
                        if length > MAX_VALUE_BYTES:
                            raise _Incomplete('value_limit')
                        size += length
                    elif type(item) is int and -(2**63) <= item < 2**63:
                        size += 8
                    elif type(item) is float and math.isfinite(item):
                        size += 8
                    else:
                        raise _Incomplete('invalid_scalar')
                except UnicodeError:
                    raise _Incomplete('invalid_scalar') from None
                if size > MAX_SNAPSHOT_BYTES:
                    raise _Incomplete('byte_limit')
                new[key] = item
            copied.append(new)
        result[name] = tuple(copied)
    return result


def _resources(rows):
    result, keys = {}, set()
    for row in rows:
        if not set(RESOURCE_FIELDS).issubset(row):
            raise _Incomplete('missing_resource_fields')
        identity, key = row['id'], row['key']
        if not _positive(identity) or type(key) is not str:
            raise _Incomplete('invalid_resource_identity')
        if identity in result:
            raise _Incomplete('duplicate_resource_id')
        if key in keys:
            raise _Incomplete('duplicate_resource_key')
        if not _time(row['first_seen']) or not _time(row['last_seen']):
            raise _Incomplete('invalid_resource_time')
        if type(row['active']) is not int or row['active'] not in (0, 1):
            raise _Incomplete('invalid_resource_state')
        result[identity] = row
        keys.add(key)
    return result


def _metadata(snapshot):
    mappings = {}
    for name, fields in (('revisions', _REVISION_FIELDS), ('heads', _HEAD_FIELDS),
                         ('jobs', _JOB_FIELDS), ('projections', _PROJECTION_FIELDS)):
        mapping = {}
        for row in snapshot[name]:
            if not fields.issubset(row) or not _positive(row['resource_id']) or not _positive(row['revision']):
                raise _Incomplete('invalid_metadata_shape')
            if not _hash(row['corpus_hash']) or not _hash(row['model_hash']):
                raise _Incomplete('invalid_metadata_shape')
            if name == 'revisions':
                if not _hash(row['content_hash']) or type(row['hash_profile']) is not str or not _time(row['updated_at']):
                    raise _Incomplete('invalid_metadata_shape')
                key = row['resource_id']
            elif name == 'heads':
                if not _time(row['updated']): raise _Incomplete('invalid_metadata_shape')
                key = row['resource_id']
            elif name == 'jobs':
                if type(row['job_id']) is not str or not re.fullmatch('cij_[0-9a-f]{64}', row['job_id']):
                    raise _Incomplete('invalid_metadata_shape')
                if type(row['state']) is not str or row['state'] not in ('pending', 'claimed', 'indexed', 'failed', 'superseded'):
                    raise _Incomplete('invalid_metadata_shape')
                if row['projection_hash'] is not None and not _hash(row['projection_hash']):
                    raise _Incomplete('invalid_metadata_shape')
                key = row['job_id']
            else:
                if not _hash(row['projection_hash']) or type(row['job_id']) is not str or not re.fullmatch('cij_[0-9a-f]{64}', row['job_id']) or not _time(row['indexed_at']):
                    raise _Incomplete('invalid_metadata_shape')
                key = (row['resource_id'], row['model_hash'])
            if key in mapping:
                raise _Incomplete('duplicate_metadata_identity')
            mapping[key] = row
        mappings[name] = mapping
    return mappings


def _proposed(row, *, hashes=False):
    """Evaluate the declared new profile; never reconstruct a legacy hash."""
    networks = row['networks']
    if type(networks) is not str or not networks.startswith(',') or not networks.endswith(','):
        raise WriterError()
    network_items = () if networks == ',,' else tuple(networks[1:-1].split(','))
    command = RegistryUpsert(key=row['key'], source=row['source'], kind=row['kind'],
        url=row['url'], name=row['name'], description=row['description'], category=row['category'],
        networks=network_items, price_usdc=row['price_usdc'], pay_to=row['pay_to'], method=row['method'],
        details_json=row['details'], calls_30d=row['calls_30d'], payers_30d=row['payers_30d'],
        last_called=row['last_called'], desc_lang=row['desc_lang'], regions=row['regions'],
        auth_declared=row['auth_declared'])
    normalized = _normalized(command)
    if not hashes:
        return normalized, None, None
    return (normalized, _digest([HASH_PROFILE, normalized]),
            _digest([CORPUS_PROFILE, normalized['kind'], normalized['name'], normalized['description'], normalized['category']]))


def _result():
    return {
        'profile': PROFILE, 'complete': False, 'assessment': 'incomplete', 'issues': [],
        'input_counts': None, 'counts': {name: None for name in _METRICS},
        'limits': {'resources_per_snapshot': MAX_RESOURCES, 'rows_per_metadata_kind': MAX_METADATA_ROWS,
            'total_rows_per_snapshot': MAX_TOTAL_ROWS, 'scalar_bytes': MAX_VALUE_BYTES,
            'snapshot_bytes': MAX_SNAPSHOT_BYTES, 'fields_per_row': MAX_ROW_FIELDS, 'cells_per_snapshot': MAX_CELLS},
        'scope': {'caller_supplied_snapshots': True, 'atomic_capture_verified': False,
            'normalization_profile': HASH_PROFILE, 'corpus_profile': CORPUS_PROFILE,
            'legacy_hash_recomputed': False, 'source_values_before_legacy_truncation_recoverable': False,
            'candidate_index_metadata_only': True, 'artifact_body_or_search_quality_assessed': False,
            'job_lease_or_worker_authority_verified': False,
            'public_projection_assessed': False, 'provider_or_observation_truth_verified': False,
            'unselected_fields_assessed': False, 'operating_cutover_authorized': False,
            'database_or_source_capture_performed': False, 'writes_performed': 0, 'provider_calls': 0},
    }


def compare_snapshots(source, candidate, *, expected_model_hash):
    """Compare flat tuple/dict snapshots and return only fixed aggregate fields.

    Completeness describes bounded analysis, not equivalence or cutover safety.
    Source metadata may be empty for a declared legacy snapshot; candidate
    version/head/job/projection intent is evaluated without creating anything.
    """
    report = _result()
    try:
        if not _hash(expected_model_hash): raise _Incomplete('invalid_model_hash')
        source = _copy_snapshot(source)
        candidate = _copy_snapshot(candidate)
        left, right = _resources(source['resources']), _resources(candidate['resources'])
        _metadata(source)
        metadata = _metadata(candidate)
    except _Incomplete as exc:
        report['issues'] = [exc.code]
        return report
    metrics = {name: 0 for name in _METRICS}
    report['input_counts'] = {name: {table: len(snapshot[table]) for table in SNAPSHOT_FIELDS}
                              for name, snapshot in (('source', source), ('candidate', candidate))}
    common = left.keys() & right.keys()
    metrics['matched_identity_rows'] = len(common)
    metrics['missing_candidate_rows'] = len(left.keys() - right.keys())
    metrics['added_candidate_rows'] = len(right.keys() - left.keys())
    right_keys = {row['key']: identity for identity, row in right.items()}
    metrics['key_to_id_changed_rows'] = sum(row['key'] in right_keys and right_keys[row['key']] != identity for identity, row in left.items())
    proposed_source, proposed_candidate = {}, {}
    for label, records, target in (('legacy', left, proposed_source), ('candidate', right, proposed_candidate)):
        for identity, row in records.items():
            try:
                values = _proposed(row, hashes=label == 'candidate')
            except WriterError:
                metrics[label + '_normalization_refused_rows'] += 1
                continue
            target[identity] = values
            metrics[label + '_normalization_changed_rows'] += any(row[name] != value for name, value in values[0].items())
    for identity in common:
        before, after = left[identity], right[identity]
        metrics['id_key_changed_rows'] += before['key'] != after['key']
        metrics['first_seen_changed_rows'] += before['first_seen'] != after['first_seen']
        metrics['last_seen_changed_rows'] += before['last_seen'] != after['last_seen']
        metrics['activity_changed_rows'] += before['active'] != after['active']
        metrics['observation_changed_rows'] += any(before[name] != after[name] for name in _OBSERVATION_FIELDS)
        metrics['stored_hash_difference_rows'] += before['content_hash'] != after['content_hash']
        if identity in proposed_source and identity in proposed_candidate:
            metrics['normalized_registry_assessed_rows'] += 1
            equal = proposed_source[identity][0] == proposed_candidate[identity][0]
            metrics['normalized_registry_difference_rows'] += not equal
            metrics['expected_profile_hash_replacement_rows'] += (equal and before['content_hash'] != after['content_hash']
                and after['content_hash'] == proposed_candidate[identity][1])
    for table in metadata.values():
        metrics['orphan_metadata_rows'] += sum(row['resource_id'] not in right for row in table.values())
    for identity, row in right.items():
        values = proposed_candidate.get(identity)
        if values is not None:
            metrics['candidate_hash_assessed_rows'] += 1
            metrics['candidate_hash_mismatch_rows'] += row['content_hash'] != values[1]
        revision = metadata['revisions'].get(identity)
        if revision is None:
            metrics['missing_revision_rows'] += 1
            continue
        metrics['revision_mismatch_rows'] += (revision['hash_profile'] != HASH_PROFILE
            or revision['content_hash'] != row['content_hash'] or revision['updated_at'] != row['last_seen'])
        metrics['corpus_mismatch_rows'] += values is not None and revision['corpus_hash'] != values[2]
        metrics['model_mismatch_rows'] += revision['model_hash'] != expected_model_hash
        head = metadata['heads'].get(identity)
        if head is None:
            metrics['missing_head_rows'] += 1
            continue
        descriptor = (identity, revision['revision'], revision['corpus_hash'], revision['model_hash'])
        metrics['head_mismatch_rows'] += (head['resource_id'], head['revision'], head['corpus_hash'], head['model_hash']) != descriptor
        current_jobs = [job for job in metadata['jobs'].values()
            if (job['resource_id'], job['revision'], job['corpus_hash'], job['model_hash']) == descriptor]
        if not current_jobs:
            metrics['current_job_missing_rows'] += 1
            continue
        if len(current_jobs) != 1:
            metrics['current_job_ambiguous_rows'] += 1
            continue
        job = current_jobs[0]
        metrics['current_job_' + job['state'] + '_rows'] += 1
        projection = metadata['projections'].get((identity, revision['model_hash']))
        current_projection = projection is not None and (projection['resource_id'], projection['revision'], projection['corpus_hash'], projection['model_hash']) == descriptor
        if job['state'] == 'indexed':
            if not current_projection:
                metrics['current_projection_missing_rows'] += 1
            else:
                metrics['current_projection_mismatch_rows'] += (projection['job_id'] != job['job_id']
                    or projection['projection_hash'] != job['projection_hash'])
        elif current_projection:
            metrics['projection_without_indexed_job_rows'] += 1
    report['complete'] = True
    report['counts'] = metrics
    report['assessment'] = ('empty_snapshots' if not left and not right else
                            'differences_observed' if any(metrics[name] for name in _DIFFERENCES) else 'bounded_comparison_complete')
    return report
