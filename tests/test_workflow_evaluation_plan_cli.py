"""Offline plan validation cannot authorize execution or mutate local artifacts."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'validate_workflow_evaluation_plan.py'
MANIFEST = ROOT / 'tests' / 'fixtures' / 'workflow_holdout_manifest.json'
PLAN = ROOT / 'tests' / 'fixtures' / 'workflow_evaluation_plan.json'
MAX_BYTES = 512 * 1024
PRIVATE = 'synthetic-private-reviewer-secret'


def invoke(directory, *arguments, guarded=False):
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    if guarded:
        runner = r'''
import os, runpy, sys
entry_only = len(sys.argv) == 2 or '--help' in sys.argv[2:]
blocked_mutations = {'os.mkdir', 'os.rename', 'os.remove', 'os.rmdir', 'os.link',
                     'os.symlink', 'os.chmod', 'os.chown', 'os.truncate',
                     'os.system', 'subprocess.Popen', 'sqlite3.connect'}
def audit(event, arguments):
    if event in blocked_mutations or event.startswith('socket.'):
        raise RuntimeError('Offline validation attempted a forbidden side effect')
    if event == 'open':
        if (entry_only and isinstance(arguments[0], str) and
                arguments[0].endswith(('workflow_holdout_manifest.json',
                                       'workflow_evaluation_plan.json',
                                       'workflow-evaluation-cases.json'))):
            raise RuntimeError('Entry-only invocation read an input inventory')
        mode, flags = arguments[1:3]
        if ((isinstance(mode, str) and any(item in mode for item in 'wax+'))
                or (isinstance(flags, int) and flags &
                    (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            raise RuntimeError('Offline validation attempted a file write')
sys.addaudithook(audit)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        command = [sys.executable, '-B', '-c', runner, str(SCRIPT), *arguments]
    else:
        command = [sys.executable, '-B', str(SCRIPT), *arguments]
    return subprocess.run(command, cwd=directory, env=environment, text=True,
                          capture_output=True, timeout=15)


def copied_inputs(directory):
    manifest = directory / 'manifest.json'
    plan = directory / 'plan.json'
    manifest.write_bytes(MANIFEST.read_bytes())
    plan.write_bytes(PLAN.read_bytes())
    return manifest, plan


def snapshot(directory):
    return {str(path.relative_to(directory)):
            (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
            for path in directory.rglob('*') if path.is_file() and not path.is_symlink()}


def assert_private_error(result, code=None):
    assert result.returncode == 1, result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed['status'] == 'invalid' and parsed['mode'] == 'offline-read-only'
    if code is not None:
        assert parsed['error_code'] == code
    for field in ('provider_calls', 'model_calls', 'database_opens', 'artifact_writes'):
        assert parsed[field] == 0
    combined = result.stdout + result.stderr
    assert PRIVATE not in combined and 'Traceback' not in combined
    return parsed


def test_success_from_unrelated_directory_is_read_only_and_reports_no_certification(tmp_path):
    manifest, plan = copied_inputs(tmp_path)
    before = snapshot(tmp_path)
    result = invoke(tmp_path, '--manifest', str(manifest), '--plan', str(plan), guarded=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ''
    parsed = json.loads(result.stdout)
    assert parsed['status'] == 'needs_human_actions' and parsed['mode'] == 'offline-read-only'
    assert parsed['manifest_fingerprint'] == json.loads(manifest.read_text())['manifest_fingerprint']
    assert parsed['plan_fingerprint'] == json.loads(plan.read_text())['plan_fingerprint']
    assert isinstance(parsed['counts'], dict) and parsed['counts']
    assert all(type(value) is int and value >= 0 for value in parsed['counts'].values())
    for field in ('identity_verification', 'reviewer_qualification_verification',
                  'reviewer_independence_verification', 'access_enforcement',
                  'pre_run_allocation', 'chronological_reservation', 'unseen_holdout_status'):
        assert parsed[field] == 'not_established'
    for field in ('human_expert_reviewed', 'source_evidence_verified',
                  'provider_quality_certified', 'execution_authorized', 'scores_recorded'):
        assert parsed[field] is False
    assert parsed['human_judgments'] == 0 and parsed['representativeness'] == 'not_assessed'
    assert parsed['rubric_binding'] == json.loads(plan.read_text())['rubric_binding']
    for field in ('provider_calls', 'model_calls', 'database_opens', 'artifact_writes'):
        assert parsed[field] == 0
    assert snapshot(tmp_path) == before
    for path in (manifest, plan):
        assert str(path) not in result.stdout
    for case in json.loads(manifest.read_text())['cases']:
        assert case['task'] not in result.stdout and case['case_id'] not in result.stdout


@pytest.mark.parametrize('arguments', [(), ('--help',)])
def test_help_or_missing_arguments_have_no_implicit_input_access_or_writes(tmp_path, arguments):
    before = snapshot(tmp_path)
    result = invoke(tmp_path, *arguments, guarded=True)
    assert result.returncode == (0 if arguments else 2)
    if not arguments:
        assert json.loads(result.stderr)['error_code'] == 'invalid_arguments'
    assert snapshot(tmp_path) == before
    assert 'Traceback' not in result.stdout + result.stderr


def test_import_does_not_load_application_or_read_any_input_file(tmp_path):
    code = r'''
import importlib, os, sys
sys.path.insert(0, sys.argv[1])
inputs = set(sys.argv[2:])
def audit(event, arguments):
    if event == 'open':
        if isinstance(arguments[0], str) and arguments[0] in inputs:
            raise AssertionError('Import read an input inventory')
        mode, flags = arguments[1:3]
        if ((isinstance(mode, str) and any(item in mode for item in 'wax+'))
                or (isinstance(flags, int) and flags &
                    (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            raise AssertionError('Import wrote a file')
    if event == 'sqlite3.connect' or event.startswith('socket.'):
        raise AssertionError('Import initialized application resources')
sys.addaudithook(audit)
importlib.import_module('scripts.validate_workflow_evaluation_plan')
assert not any(name == 'agent_market' or name.startswith('agent_market.') for name in sys.modules)
'''
    before = snapshot(tmp_path)
    result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT), str(MANIFEST), str(PLAN)],
                            cwd=tmp_path, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == '' and snapshot(tmp_path) == before


@pytest.mark.parametrize('arguments', [
    ('--manifest', str(MANIFEST)), ('--plan', str(PLAN)),
    ('--manifest', str(MANIFEST), '--plan', str(PLAN), '--plan', PRIVATE),
    ('--manifest', str(MANIFEST), '--manifest', PRIVATE, '--plan', str(PLAN)),
    ('--manifest', str(MANIFEST), '--plan', str(PLAN), '--apply', PRIVATE),
    ('--manifest', str(MANIFEST), '--plan', str(PLAN), '--output', PRIVATE),
    ('--manifest', str(MANIFEST), '--plan', str(PLAN), '--run', PRIVATE),
    ('--man', str(MANIFEST), '--plan', str(PLAN)),
    ('--manifest', str(MANIFEST), '--pl', str(PLAN)),
])
def test_incomplete_ambiguous_or_mutating_arguments_fail_without_private_echo(tmp_path, arguments):
    before = snapshot(tmp_path)
    result = invoke(tmp_path, *arguments, guarded=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)['error_code'] == 'invalid_arguments'
    assert PRIVATE not in result.stdout + result.stderr and 'Traceback' not in result.stdout + result.stderr
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('which', ['manifest', 'plan'])
@pytest.mark.parametrize('kind', ['missing', 'file_symlink', 'parent_symlink', 'directory', 'fifo', 'too_large'])
def test_each_explicit_input_refuses_unsafe_paths_without_creating_or_echoing_them(tmp_path, which, kind):
    manifest, plan = copied_inputs(tmp_path)
    target = manifest if which == 'manifest' else plan
    path = tmp_path / (PRIVATE + '.json')
    if kind == 'file_symlink':
        path.symlink_to(target)
    elif kind == 'parent_symlink':
        directory = tmp_path / (PRIVATE + '-directory')
        directory.symlink_to(tmp_path, target_is_directory=True)
        path = directory / target.name
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'too_large':
        path.write_bytes(b'x' * (MAX_BYTES + 1))
    arguments = {'manifest': manifest, 'plan': plan}
    arguments[which] = path
    before = {entry.name for entry in tmp_path.iterdir()}
    result = invoke(tmp_path, '--manifest', str(arguments['manifest']), '--plan', str(arguments['plan']), guarded=True)
    parsed = assert_private_error(result)
    assert parsed['error_code'] == 'input_unavailable_or_invalid_json'
    assert str(path) not in result.stdout + result.stderr
    assert {entry.name for entry in tmp_path.iterdir()} == before


@pytest.mark.parametrize('which', ['manifest', 'plan'])
@pytest.mark.parametrize('data', [
    b'{"secret":"' + PRIVATE.encode() + b'"',
    b'{"secret":1,"secret":2}', b'{"secret":NaN}', b'{"secret":Infinity}', b'\xff\xfe',
])
def test_each_input_uses_strict_json_and_never_repairs_or_discloses_content(tmp_path, which, data):
    manifest, plan = copied_inputs(tmp_path)
    target = manifest if which == 'manifest' else plan
    target.write_bytes(data)
    before = snapshot(tmp_path)
    result = invoke(tmp_path, '--manifest', str(manifest), '--plan', str(plan), guarded=True)
    assert_private_error(result, 'input_unavailable_or_invalid_json')
    assert snapshot(tmp_path) == before


def test_invalid_governance_payload_never_echoes_identity_or_local_paths(tmp_path):
    manifest, plan = copied_inputs(tmp_path)
    value = json.loads(plan.read_text())
    value['unexpected_reviewer'] = {'name': PRIVATE, 'evidence_path': str(tmp_path / PRIVATE)}
    plan.write_text(json.dumps(value))
    before = snapshot(tmp_path)
    result = invoke(tmp_path, '--manifest', str(manifest), '--plan', str(plan), guarded=True)
    assert_private_error(result)
    assert str(tmp_path) not in result.stdout + result.stderr
    assert snapshot(tmp_path) == before
