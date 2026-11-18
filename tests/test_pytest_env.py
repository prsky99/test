"""Precision review R03 (11-15): tests never reach production through inherited values."""
import os
from pathlib import Path

import pytest

from agent_market import application_runtime as runtime
from scripts import pytest_env

ROOT = Path(__file__).resolve().parents[1]


def test_conftest_cleared_the_production_pointers_for_this_session():
    import tests.conftest as conftest
    assert conftest._PRODUCTION_POINTERS == pytest_env.PRODUCTION_POINTERS
    assert not [k for k in os.environ if k.startswith(pytest_env.PRODUCTION_POINTERS) and k != 'REDIS_DB']
    assert os.environ['REDIS_DB'] == pytest_env.TEST_REDIS_DB != '0'


def test_clean_environment_drops_every_pointer_and_keeps_the_rest():
    base = {'APPLICATION_STORE_BACKEND': 'postgresql', 'APPLICATION_POSTGRES_DSN_FILE': '/x', 'GATEWAY_DB': 'g',
            'AD_COIN_V2_ENABLED': '1', 'AGENT_EDGE_KEY': 'k', 'AGENT_PRIVATE_X': 'p', 'PGHOST': 'h', 'REDIS_PORT': '1',
            'AGENTCON_TESTS_MAY_USE_PRODUCTION': '1', 'AGENTCON_PROJECT_ROOT': 'r', 'PATH': '/bin', 'HOME': '/h'}
    assert pytest_env.clean_environment(base) == {'PATH': '/bin', 'HOME': '/h', 'REDIS_DB': '15'}


@pytest.mark.parametrize('command,expected', [
    (['.venv-tests/bin/python', '-m', 'pytest', '-q'], True),
    (['/x/.venv-tests/bin/pytest', 'tests'], True),
    (['.venv-tests/bin/python', '-m', 'scripts.release_gate', 'r1'], True),
    (['python', 'scripts/release_gate.py', 'r1'], True),
    (['.venv/bin/python', '-m', 'scripts.db_change_rehearsal', 'run'], False),
    (['bash', 'logs/ops/x.sh'], False)])
def test_heavy_slot_cleans_only_test_commands(command, expected):
    assert pytest_env.is_test_command(command) is expected


def test_the_production_socket_is_refused_while_pytest_runs():
    production = {'host': '/Users/x/workspace/A2A_Discovery/gateway-data/postgres18/run', 'port': '55432'}
    testing = {'PYTEST_CURRENT_TEST': 't'}
    with pytest.raises(runtime.RuntimeStorageError, match='production_storage_in_tests'):
        runtime.refuse_production_in_tests(production, testing)
    with pytest.raises(runtime.RuntimeStorageError, match='production_storage_in_tests'):
        runtime.refuse_production_in_tests({'host': '/elsewhere', 'port': '55432'}, testing)
    runtime.refuse_production_in_tests({'host': '/tmp/cluster', 'port': '55447'}, testing)          # private cluster
    runtime.refuse_production_in_tests(production, {**testing, 'AGENTCON_TESTS_MAY_USE_PRODUCTION': '1'})
    runtime.refuse_production_in_tests(production, {})                                             # not a test


def test_connect_refuses_before_opening_anything(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('connected')))
    with pytest.raises(runtime.RuntimeStorageError, match='production_storage_in_tests'):
        runtime._connect('host=/Users/x/A2A_Discovery/gateway-data/postgres18/run port=55432 dbname=d user=u')


def test_redis_uses_the_database_number_from_the_environment(monkeypatch):
    from agent_market.infra.redis_hub import RedisHub
    assert RedisHub().db == 15
    assert RedisHub(db=3).db == 3
    monkeypatch.delenv('REDIS_DB')
    monkeypatch.delenv('AGENTCON_UNDER_TEST', raising=False)   # production: no mark, database 0 as before
    assert RedisHub().db == 0


@pytest.mark.parametrize('path,needle', [
    ('scripts/release_gate.py', "env = {**clean_environment(), 'PYTHONPATH': str(copy)}"),
    ('scripts/pytest_slot.py', 'env=clean_environment()'),
    ('scripts/heavy_slot.py', 'clean_environment() if is_test_command(command) else None')])
def test_test_runners_start_tests_without_production_pointers(path, needle):
    assert needle in (ROOT / path).read_text()
