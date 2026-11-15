"""Environment for test runs on the production Mac (precision review R03, 11-15).

A test, or a subprocess it starts, must never reach a production store or service through values inherited from
the shell that started it (11-15: a test's subprocess ran workflow_maintenance --apply on the production database).
The release gate, pytest_slot and heavy_slot (for test commands) start tests with these values removed and Redis on
its own database number; tests/conftest.py clears the same keys when the session starts (keep the lists equal,
tests/test_pytest_env.py checks it); agent_market.application_runtime refuses the production socket while
PYTEST_CURRENT_TEST is set unless AGENTCON_TESTS_MAY_USE_PRODUCTION=1.
"""
import os

PRODUCTION_POINTERS = ('APPLICATION_', 'AGENTCON_PROJECT_ROOT', 'AGENTCON_TESTS_MAY_USE_PRODUCTION', 'GATEWAY_DB',
                       'COLLECTOR_DB', 'AD_COIN_', 'AGENT_EDGE_', 'AGENT_PRIVATE_', 'PG', 'REDIS_')
TEST_REDIS_DB = '15'   # production uses Redis database 0 on the same server


def clean_environment(base=None):
    env = dict(os.environ if base is None else base)
    for key in [k for k in env if k.startswith(PRODUCTION_POINTERS)]:
        del env[key]
    env['REDIS_DB'] = TEST_REDIS_DB
    return env


def is_test_command(command):
    """True for pytest, the release gate and pytest_slot (heavy_slot keeps other commands' environment)."""
    words = [str(part) for part in command]
    return any(w.rsplit('/', 1)[-1] in ('pytest', 'py.test') or w in ('pytest', 'scripts.release_gate',
               'scripts.pytest_slot') or w.endswith(('release_gate.py', 'pytest_slot.py')) for w in words)
