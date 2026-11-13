"""A production DB structure change must pass a rehearsal on a disposable copy first
(2026-11-10 05:38: twelve AD Coin triggers in the public schema made every request fail)."""
import json

import pytest

from scripts import db_change_rehearsal as rehearsal


def test_a_command_naming_the_production_database_is_refused():
    for command in ('python -m x --dsn-file gateway-data/postgres18/application.dsn',
                    'psql -p 55432 -c "select 1"', 'psql -d agentcon_cutover_20261020_191757'):
        with pytest.raises(rehearsal.RehearsalRefused, match='command_names_production'):
            rehearsal.refuse_production(command)
    rehearsal.refuse_production('python -m scripts.ad_coin_v2_migrate migrate --dsn-file {dsn_file} --key-file {key_file}')


def test_check_needs_the_same_change_recently_passed_against_the_active_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, 'REPORTS', tmp_path)
    monkeypatch.setattr(rehearsal, 'active_releases', lambda: ['f-r2', 'j-r5'])
    sql = tmp_path / 'change.sql'
    sql.write_text('CREATE INDEX x ON meta(key);\n')
    assert rehearsal.check(str(sql)) == {'ok': False, 'reason': 'no_passed_rehearsal'}
    digest = rehearsal.change_digest(str(sql))
    (tmp_path / 'passed.json').write_text(json.dumps({digest: {'at': 1000.0, 'releases': ['j-r5', 'f-r2'], 'report': 'r.json'}}))
    assert rehearsal.check(str(sql), now=1000.0 + 3600) == {'ok': True, 'report': 'r.json'}
    assert rehearsal.check(str(sql), now=1000.0 + 25 * 3600)['reason'].startswith('rehearsal_older_than')
    monkeypatch.setattr(rehearsal, 'active_releases', lambda: ['f-r3', 'j-r5'])
    assert rehearsal.check(str(sql), now=1000.0 + 3600)['reason'] == 'active_releases_changed'
    sql.write_text('CREATE INDEX y ON meta(key);\n')  # a different change needs its own rehearsal
    assert rehearsal.check(str(sql), now=1000.0 + 3600)['reason'] == 'no_passed_rehearsal'


def test_active_releases_reads_both_state_shapes(tmp_path, monkeypatch):
    state = tmp_path / 'state.json'
    monkeypatch.setattr(rehearsal, 'STATE', state)
    state.write_text(json.dumps({'services': {'frontend': {'active': 'b', 'slots': {'a': 'f1', 'b': {'release': 'f2', 'pid': 1}}},
                                              'jobs': {'release': 'j1'}}}))
    assert rehearsal.active_releases() == ['f2', 'j1']


def test_restore_workers_apply_to_the_restore_sessions_only(monkeypatch):
    """PM 11-14 00:2x: the restore's HNSW builds used every core; a worker count goes to pg_restore through PGOPTIONS."""
    from scripts import db_change_rehearsal as R
    monkeypatch.delenv('AGENTCON_RESTORE_MAINTENANCE_WORKERS', raising=False)
    monkeypatch.setenv('PGOPTIONS', '-c work_mem=1GB')                 # never inherited from the caller
    monkeypatch.setattr(R, 'RESTORE_MAINTENANCE_WORKERS', None)
    assert 'PGOPTIONS' not in R._restore_environment()
    monkeypatch.setattr(R, 'RESTORE_MAINTENANCE_WORKERS', 0)
    assert R._restore_environment()['PGOPTIONS'] == '-c max_parallel_maintenance_workers=0'
    monkeypatch.setenv('AGENTCON_RESTORE_MAINTENANCE_WORKERS', '1')
    assert R._restore_environment()['PGOPTIONS'] == '-c max_parallel_maintenance_workers=1'
    monkeypatch.setenv('AGENTCON_RESTORE_MAINTENANCE_WORKERS', '1; DROP')
    assert 'PGOPTIONS' not in R._restore_environment()
    assert 'PGOPTIONS' not in R._environment()                          # the checks after the restore keep defaults


def test_restore_timeout_is_raised_only_by_its_variable_within_bounds(monkeypatch):
    """11-14: the graph-cap full rehearsal hit the 3600 s restore limit under load; one run may raise it."""
    from scripts import db_change_rehearsal as rehearsal
    monkeypatch.delenv('AGENTCON_RESTORE_TIMEOUT_SECONDS', raising=False)
    assert rehearsal.restore_timeout() == 3600
    for value, expected in (('5400', 5400), ('60', 600), ('999999', 14400), ('soon', 3600), ('', 3600)):
        monkeypatch.setenv('AGENTCON_RESTORE_TIMEOUT_SECONDS', value)
        assert rehearsal.restore_timeout() == expected
