"""Real-process rehearsal boundaries never accept an operating database."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'rehearse_workflow_storage.py'
PROFILE = 'workflow-storage-load-rehearsal-v1'
PRIVATE = 'synthetic-private-storage-secret'
MINIMUM = ('--run', '--iterations', '1', '--readers', '1', '--writers', '1')


BOOTSTRAP = r'''
import importlib, json, os, pathlib, runpy, socket, sys
root, script, scratch, source, report, injection = sys.argv[1:7]
arguments = sys.argv[7:]
sys.path.insert(0, root)
scratch = pathlib.Path(scratch).resolve()
source = pathlib.Path(source).resolve()
report = pathlib.Path(report).absolute() if report else None
entry_only = os.environ.get('STORAGE_REHEARSAL_TEST_ARGUMENT_ONLY') == '1' or not arguments or '--help' in arguments or injection == 'import'
def within(path, directory):
    try: pathlib.Path(path).absolute().relative_to(directory); return True
    except (ValueError, TypeError): return False
def audit(event, values):
    if event in {'socket.connect','socket.bind','socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.sendto','socket.sendmsg','subprocess.Popen','os.system','os.exec','os.posix_spawn'} or entry_only and event.startswith('socket.'):
        raise RuntimeError('Forbidden external effect')
    if event == 'sqlite3.connect':
        target = str(values[0])
        if entry_only: raise RuntimeError('Entry-only database access')
        if target != ':memory:':
            if target.startswith('file:'):
                from urllib.parse import unquote, urlsplit
                target = unquote(urlsplit(target).path)
            if not within(target, scratch): raise RuntimeError('Database outside disposable workspace')
    if event == 'open':
        path, mode, flags = values[:3]
        if isinstance(path, (str, bytes, os.PathLike)):
            candidate = pathlib.Path(os.fsdecode(path)).absolute()
            if candidate in (source, pathlib.Path(str(source)+'.updates-key')):
                raise RuntimeError('Operating source was accessed')
            writing = isinstance(mode, str) and any(letter in mode for letter in 'wax+')
            writing = writing or isinstance(flags, int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if writing and (entry_only or not within(candidate, scratch) and candidate != report):
                raise RuntimeError('Unexpected file write')
    if event == 'os.mkdir' and entry_only: raise RuntimeError('Entry-only workspace mutation')
sys.addaudithook(audit)
def no_listener(*args, **kwargs): raise RuntimeError('Forbidden listener')
socket.socket.listen = no_listener
if injection == 'import':
    importlib.import_module('agent_market.workflow_storage_rehearsal')
    assert not any(name in sys.modules for name in ('agent_market.gateway.store','agent_market.workflows','agent_market.server'))
    assert not list(scratch.iterdir())
    raise SystemExit(0)
if injection:
    module = importlib.import_module('agent_market.workflow_storage_rehearsal')
    original_build = module._build_fixture
    entered = []
    if injection in ('failure','timeout'):
        def failed(directory):
            assert pathlib.Path(directory).parent.is_dir()
            entered.append(True)
            if injection == 'timeout': raise TimeoutError('synthetic-private-storage-secret')
            raise RuntimeError('synthetic-private-storage-secret')
        module._build_fixture = failed
    elif injection == 'invariant':
        original_run = module.run_rehearsal
        def invalid(*args, **kwargs):
            result = original_run(*args, **kwargs)
            assert result['ok'] is True and result['invariants']
            result['invariants'][next(iter(result['invariants']))] = False
            entered.append(True)
            return result
        module.run_rehearsal = invalid
    elif injection == 'vacuum':
        import sqlite3
        original_connect = sqlite3.connect
        first_file = []
        class Recording(sqlite3.Connection):
            def execute(self, statement, *args, **kwargs):
                if statement.strip().upper().startswith('VACUUM'):
                    current = pathlib.Path(super().execute('PRAGMA database_list').fetchone()[2]).resolve()
                    assert within(current, scratch) and first_file and current != first_file[0]
                    assert current.parent.stat().st_mode & 0o777 == 0o700
                    assert first_file[0].parent.stat().st_mode & 0o777 == 0o700
                    controls = super().execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls').fetchall()
                    assert controls and all(tuple(row) == (0,0,0) for row in controls)
                    entered.append(True)
                return super().execute(statement, *args, **kwargs)
        def connect(target, *args, **kwargs):
            name = str(target)
            if name.startswith('file:'):
                from urllib.parse import unquote, urlsplit
                name = unquote(urlsplit(name).path)
            if name != ':memory:' and not first_file: first_file.append(pathlib.Path(name).resolve())
            kwargs.setdefault('factory', Recording)
            return original_connect(target, *args, **kwargs)
        sqlite3.connect = connect
sys.argv = [script, *arguments]
try:
    runpy.run_path(script, run_name='__main__')
finally:
    assert not list(scratch.iterdir()), 'Disposable workspace was not cleaned'
    if injection: assert entered, 'Failure injection was not reached'
'''


def invoke(directory, *arguments, report=None, injection='', argument_only=False, environment_changes=None):
    scratch = directory / 'scratch'
    scratch.mkdir(mode=0o700, exist_ok=True)
    source = directory / 'operating-collector.sqlite3'
    if not source.exists():
        source.write_bytes((PRIVATE + ':not-a-rehearsal-fixture').encode())
        Path(str(source) + '.updates-key').write_bytes(b'k' * 32)
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(scratch),
                   'STORAGE_REHEARSAL_TEST_ARGUMENT_ONLY': '1' if argument_only else '0'}
    environment.pop('AGENT_UPDATES_KEY', None)
    environment.update(environment_changes or {})
    command = [sys.executable, '-B', '-c', BOOTSTRAP, str(ROOT), str(SCRIPT),
               str(scratch), str(source), str(report) if report else '', injection, *map(str, arguments)]
    return subprocess.run(command, cwd=directory, env=environment, capture_output=True,
                          text=True, timeout=45)


def source_snapshot(directory):
    return {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_ino)
            for path in (directory / 'operating-collector.sqlite3', directory / 'operating-collector.sqlite3.updates-key')}


def assert_private(result):
    combined = result.stdout + result.stderr
    assert PRIVATE not in combined and 'Traceback' not in combined and str(ROOT) not in combined
    assert not re.search(r'\b(?:wr|ex|cv|ag|pub|capp|aut|cdg)_[a-f0-9]{16,}\b', combined)
    assert 'Bearer ' not in combined and 'cpk_' not in combined and 'wfpk_' not in combined
    assert 'storage-fixture.example' not in combined and not re.search(r'https?://', combined)


def error_json(result, expected):
    assert result.returncode == expected, result.stdout + result.stderr
    assert_private(result)
    value = json.loads(result.stdout or result.stderr)
    assert value['ok'] is False and value['profile'] == PROFILE
    if expected == 2: assert value['error'] == 'invalid_arguments_or_report'
    return value


@pytest.mark.parametrize('arguments', [(), ('--help',)])
def test_argument_only_invocation_never_opens_or_changes_database_or_workspace(tmp_path, arguments):
    result = invoke(tmp_path, *arguments)
    assert result.returncode == (0 if arguments else 2), result.stdout + result.stderr
    assert_private(result)
    assert not list((tmp_path / 'scratch').iterdir())
    if not arguments: error_json(result, 2)


def test_import_is_inert_without_store_runtime_network_or_fixture(tmp_path):
    result = invoke(tmp_path, injection='import')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == ''


def test_operating_database_argument_is_rejected_without_even_reading_source_or_key(tmp_path):
    invoke(tmp_path, '--help')
    before = source_snapshot(tmp_path)
    source = tmp_path / 'operating-collector.sqlite3'
    result = invoke(tmp_path, '--run', '--db', source, argument_only=True)
    error_json(result, 2)
    assert str(source) not in result.stdout + result.stderr
    assert source_snapshot(tmp_path) == before


def test_configured_operating_key_is_refused_before_any_workspace_and_never_echoed(tmp_path):
    result = invoke(tmp_path, *MINIMUM, argument_only=True,
                    environment_changes={'AGENT_UPDATES_KEY': PRIVATE + '-invalid-operating-key'})
    value = error_json(result, 1)
    assert value['error'] == 'configured_key_environment'
    assert not list((tmp_path / 'scratch').iterdir())


@pytest.mark.parametrize('arguments', [
    ('--db', PRIVATE), ('--input', PRIVATE), ('--server', PRIVATE), ('--seed', PRIVATE),
    ('--payload-bytes', PRIVATE), ('--work-dir', PRIVATE), ('--iter', '1'),
    ('--iterations', '0'), ('--iterations', '51'), ('--iterations', '1.5'),
    ('--readers', '0'), ('--readers', '5'), ('--writers', '0'), ('--writers', '5'),
    ('--run',), ('--iterations', '1', '--iterations', '2'),
    ('--report', PRIVATE, '--report', PRIVATE), ('--unknown\n'+PRIVATE,),
])
def test_unsupported_ambiguous_or_unbounded_arguments_are_fixed_private_errors(tmp_path, arguments):
    result = invoke(tmp_path, '--run', *arguments, argument_only=True)
    error_json(result, 2)
    assert not list((tmp_path / 'scratch').iterdir())


@pytest.mark.parametrize('kind', ['existing', 'symlink', 'parent_symlink', 'directory', 'fifo', 'missing_parent'])
def test_report_refuses_existing_symlink_and_nonregular_paths_without_overwrite(tmp_path, kind):
    target = tmp_path / (PRIVATE + '.json')
    real = tmp_path / 'protected.json'; real.write_bytes(b'original-report-bytes')
    if kind == 'existing': target.write_bytes(b'kept-existing-report')
    elif kind == 'symlink': target.symlink_to(real)
    elif kind == 'parent_symlink':
        linked = tmp_path / 'linked'; linked.symlink_to(tmp_path, target_is_directory=True)
        target = linked / 'new-report.json'
    elif kind == 'directory': target.mkdir()
    elif kind == 'fifo': os.mkfifo(target)
    else: target = tmp_path / 'absent-directory' / 'new-report.json'
    before = real.read_bytes()
    existing = target.read_bytes() if kind == 'existing' else None
    result = invoke(tmp_path, *MINIMUM, '--report', target, report=target, argument_only=True)
    error_json(result, 2)
    assert real.read_bytes() == before
    if existing is not None: assert target.read_bytes() == existing
    assert not list((tmp_path / 'scratch').iterdir())


@pytest.mark.parametrize('injection', ['failure', 'timeout', 'invariant'])
def test_failure_timeout_or_false_invariant_cannot_emit_pass_and_cleans_owned_workspace(tmp_path, injection):
    target = tmp_path / 'failed-report.json'
    result = invoke(tmp_path, *MINIMUM, '--report', target, report=target, injection=injection)
    value = error_json(result, 1)
    assert value['error'] == ('invariant_failed' if injection == 'invariant' else 'rehearsal_failed')
    assert json.loads(target.read_text()) == value and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list((tmp_path / 'scratch').iterdir())


def test_real_cli_report_has_measured_values_private_permissions_and_unchanged_source(tmp_path):
    invoke(tmp_path, '--help')
    before = source_snapshot(tmp_path)
    target = tmp_path / 'new-report.json'
    result = invoke(tmp_path, *MINIMUM, '--report', target, report=target, injection='vacuum')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ''
    assert_private(result)
    report = json.loads(result.stdout)
    assert report['ok'] is True and report['profile'] == PROFILE
    assert report['invariants'] and all(value is True for value in report['invariants'].values())
    assert report['limits']['isolated_only'] is True and report['limits']['synthetic'] is True
    assert report['limits']['external_provider_calls'] == report['limits']['production_actions'] == 0
    assert report['limits']['establishes_sla'] is False
    assert report['limits']['workflow_throughput_measured'] is False
    assert isinstance(report['elapsed_ms'], (int, float)) and math.isfinite(report['elapsed_ms']) and report['elapsed_ms'] > 0
    load = report['phases']['load']
    assert load['attempted_writes'] == 1 and load['readers'] == load['writers'] == load['iterations'] == 1
    assert load['committed_writes'] + load['busy_writes'] + load['budget_skipped_writes'] == 1
    assert load['deterministic_busy_refusals'] == 1 and load['consistent_reads'] is True and load['accounted_writes'] is True
    for key in ('elapsed_ms', 'write_p50_ms', 'write_p95_ms', 'read_p50_ms', 'read_p95_ms'):
        assert load[key] is None or type(load[key]) in (int, float) and math.isfinite(load[key]) and load[key] >= 0
    physical = report['phases']['physical_compaction']
    assert physical['performed'] and physical['disposable_restored_copy'] and physical['controls_paused']
    assert physical['integrity_before'] and physical['integrity_after'] and physical['critical_workflow_state_unchanged']
    assert json.loads(target.read_text()) == report
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert str(tmp_path) not in result.stdout and target.name not in result.stdout
    assert source_snapshot(tmp_path) == before
    assert not list((tmp_path / 'scratch').iterdir())
