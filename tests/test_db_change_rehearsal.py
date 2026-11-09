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
