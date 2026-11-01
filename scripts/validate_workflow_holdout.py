#!/usr/bin/env python3
"""Validate an explicit offline candidate holdout manifest without running tasks.

This structural check does not establish hidden/unseen tasks, representative
sampling, expert judgments or a pre-execution holdout allocation. No database,
runtime, key store, provider, model or network client is initialized.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

MAX_BYTES = 512 * 1024
MAX_CASES = 200
IDENTIFIER = re.compile(r'[a-z][a-z0-9._-]{0,63}\Z')
FINGERPRINT = re.compile(r'[a-f0-9]{64}\Z')
CONTRACTS = ('news.search.v1', 'docs.search.v1')
PUBLISHED_CASES_DIGEST = 'd1576f5dba1ea15a6959a242f94ed45216efa41e4eb67d1e1f6c08528b72375d'
MANIFEST_FIELDS = frozenset(('schema_version', 'dataset_id', 'version', 'review_state',
                             'cases', 'manifest_fingerprint'))
CASE_FIELDS = frozenset(('case_id', 'family_id', 'split', 'origin', 'review_state',
                        'task', 'contracts', 'inputs', 'task_fingerprint', 'input_fingerprint'))


class ManifestError(ValueError):
    """Only fixed reason codes leave the validator."""


class SafeParser(argparse.ArgumentParser):
    def error(self, _):
        print(json.dumps({'status':'invalid', 'error_code':'invalid_arguments',
                          'mode':'offline-read-only'}, indent=2), file=sys.stderr)
        self.exit(2)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ManifestError('invalid_json_value') from None


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def task_fingerprint(task):
    if not isinstance(task, str):
        raise ManifestError('invalid_task')
    normalized = ' '.join(unicodedata.normalize('NFKC', task).casefold().split())
    return digest(normalized)


def input_fingerprint(case):
    # Order of requested contracts is not an independent input. Every complete
    # contract argument remains exact, including news period, language and limit.
    return digest({'contracts': sorted(case['contracts']), 'inputs': case['inputs']})


def manifest_fingerprint(manifest):
    return digest({key: value for key, value in manifest.items() if key != 'manifest_fingerprint'})


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError('duplicate_json_key')
        result[key] = value
    return result


def _constant(_):
    raise ManifestError('nonfinite_json_value')


def read_json(path):
    """Read a bounded regular file, refusing symlinks in every path component."""
    descriptors = []
    try:
        if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
            raise ManifestError('safe_file_open_unavailable')
        absolute = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        directory = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        components = absolute.parts[1:]
        if not components:
            raise ManifestError('manifest_unavailable')
        for part in components[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            descriptors.append(directory)
        descriptor = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ManifestError('manifest_not_regular_file')
        if before.st_size > MAX_BYTES:
            raise ManifestError('manifest_too_large')
        chunks = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if size > MAX_BYTES:
            raise ManifestError('manifest_too_large')
        if (size != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise ManifestError('manifest_changed_during_read')
        data = b''.join(chunks).decode('utf-8')
        return json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
    except ManifestError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError, RecursionError):
        raise ManifestError('manifest_unavailable_or_invalid_json') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _published_tasks():
    path = Path(__file__).absolute().parents[1] / 'docs' / 'workflow-evaluation-cases.json'
    try:
        artifact = read_json(path)
        if (artifact.get('dataset_id') != 'workflow-typed-flow-cases-v1'
                or type(artifact.get('schema_version')) is not int or artifact['schema_version'] != 1
                or artifact.get('review_status') != 'pending-human-review'
                or not isinstance(artifact.get('cases'), list) or len(artifact['cases']) != 30
                or digest(artifact['cases']) != PUBLISHED_CASES_DIGEST):
            raise ValueError()
        return {task_fingerprint(case['source_title']) for case in artifact['cases']
                if case['expected']['title_accepted'] and isinstance(case['source_title'], str)}
    except (ManifestError, ValueError, TypeError, KeyError, AttributeError):
        raise ManifestError('published_fixture_inventory_unavailable') from None


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ManifestError('invalid_manifest_fields')
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ManifestError('unsupported_manifest_schema')
    if (not isinstance(manifest['dataset_id'], str) or not IDENTIFIER.fullmatch(manifest['dataset_id'])
            or type(manifest['version']) is not int or not 1 <= manifest['version'] <= 1000000):
        raise ManifestError('invalid_manifest_identity')
    if manifest['review_state'] != 'pending_human_review':
        raise ManifestError('human_review_not_established')
    cases = manifest['cases']
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ManifestError('invalid_case_count')
    if len(canonical(manifest).encode('utf-8')) > MAX_BYTES:
        raise ManifestError('manifest_too_large')
    published = _published_tasks()
    # Pure existing validators are imported only after explicit validation starts.
    # Importing this CLI or requesting --help does not load application services.
    from agent_market.workflow_composer import intent_spec
    from agent_market.workflow_typed_flow import validate_title
    from agent_market.capability_contracts import validate
    identifiers = set()
    families = {}
    tasks = {}
    inputs = {}
    queries = {}
    counts = {'cases': len(cases), 'development': 0, 'candidate_holdout': 0,
              'authored_candidate': 0, 'published_machine_fixture': 0}
    for case in cases:
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            raise ManifestError('invalid_case_fields')
        for key in ('case_id', 'family_id'):
            if not isinstance(case[key], str) or not IDENTIFIER.fullmatch(case[key]):
                raise ManifestError('invalid_case_identity')
        if case['case_id'] in identifiers:
            raise ManifestError('duplicate_case_id')
        identifiers.add(case['case_id'])
        split = case['split']
        if split not in ('development', 'candidate_holdout'):
            raise ManifestError('unsupported_split')
        if case['origin'] not in ('authored_candidate', 'published_machine_fixture'):
            raise ManifestError('unsupported_case_origin')
        if case['review_state'] != 'pending_human_review':
            raise ManifestError('human_review_not_established')
        contracts = case['contracts']
        if (not isinstance(contracts, list) or not 1 <= len(contracts) <= 2
                or any(not isinstance(item, str) or item not in CONTRACTS for item in contracts)
                or len(set(contracts)) != len(contracts)
                or not isinstance(case['inputs'], dict) or set(case['inputs']) != set(contracts)):
            raise ManifestError('unsupported_contract_inputs')
        try:
            validate_title(case['task'])
            intent_spec({'intent': {'objective': case['task'], 'contracts': contracts}})
            for contract in contracts:
                args = case['inputs'][contract]
                if not isinstance(args, dict):
                    raise ValueError()
                validate_title(args.get('query'))
                intent_spec({'intent': {'objective': args['query'], 'contracts': [contract],
                                       'limit': args.get('limit')}})
                validate(contract, args)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise ManifestError('unsafe_or_invalid_task_inputs') from None
        expected_task = task_fingerprint(case['task'])
        expected_input = input_fingerprint(case)
        if (not isinstance(case['task_fingerprint'], str) or not FINGERPRINT.fullmatch(case['task_fingerprint'])
                or case['task_fingerprint'] != expected_task
                or not isinstance(case['input_fingerprint'], str) or not FINGERPRINT.fullmatch(case['input_fingerprint'])
                or case['input_fingerprint'] != expected_input):
            raise ManifestError('case_fingerprint_mismatch')
        if split == 'candidate_holdout' and (case['origin'] == 'published_machine_fixture'
                or expected_task in published
                or any(task_fingerprint(case['inputs'][contract]['query']) in published for contract in contracts)):
            raise ManifestError('published_fixture_cannot_be_holdout')
        for mapping, key, reason in ((families, case['family_id'], 'cross_split_family_overlap'),
                                     (tasks, expected_task, 'cross_split_task_overlap'),
                                     (inputs, expected_input, 'cross_split_input_overlap')):
            if key in mapping and mapping[key] != split:
                raise ManifestError(reason)
            mapping[key] = split
        # Changing a case label, result limit or contract set cannot make the
        # same normalized search text independent held-out task evidence.
        for contract in contracts:
            query=task_fingerprint(case['inputs'][contract]['query'])
            if query in queries and queries[query]!=split:
                raise ManifestError('cross_split_query_overlap')
            queries[query]=split
        counts[split] += 1
        counts[case['origin']] += 1
    expected_manifest = manifest_fingerprint(manifest)
    if (not isinstance(manifest['manifest_fingerprint'], str)
            or not FINGERPRINT.fullmatch(manifest['manifest_fingerprint'])
            or manifest['manifest_fingerprint'] != expected_manifest):
        raise ManifestError('manifest_fingerprint_mismatch')
    return {'status': 'structurally_valid_candidate_manifest', 'mode': 'offline-read-only',
            'counts': {**counts, 'families': len(families)}, 'manifest_fingerprint': expected_manifest,
            'review_state': 'pending_human_review', 'pre_run_allocation': 'not_established',
            'unseen_holdout_status': 'not_established', 'representativeness': 'not_assessed',
            'human_expert_reviewed': False, 'provider_quality_certified': False,
            'provider_calls': 0, 'model_calls': 0, 'database_opens': 0, 'artifact_writes': 0}


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--manifest', action='append', required=True, metavar='EXISTING_JSON',
                        help='An explicit existing UTF-8 JSON file, at most 512 KiB; symlinks are refused.')
    args = parser.parse_args(argv)
    if len(args.manifest)!=1:
        parser.error('Provide one manifest.')
    try:
        # Direct script execution from another working directory still uses
        # this repository's pure validation modules, without starting services.
        if __package__ in (None, ''):
            sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
        result = validate_manifest(read_json(args.manifest[0]))
    except ManifestError as exc:
        result = {'status': 'invalid', 'error_code': str(exc), 'mode': 'offline-read-only',
                  'provider_calls': 0, 'model_calls': 0, 'database_opens': 0, 'artifact_writes': 0}
        print(json.dumps(result, indent=2))
        return 1
    except Exception:
        # Unexpected dependency failures must not reveal local paths or inputs.
        print(json.dumps({'status':'invalid', 'error_code':'validation_unavailable',
                          'mode':'offline-read-only', 'provider_calls':0, 'model_calls':0,
                          'database_opens':0, 'artifact_writes':0}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
