"""11-18 second guard (PM 16:4x): under the test mark RedisHub refuses the production database 0; without the mark
(production) it behaves as before."""
import pytest

from agent_market.infra.redis_hub import RedisHub
from scripts.rehearse_storage_adapter_postgres import _environment


def test_the_tests_carry_the_mark_and_their_own_database():
    import os
    assert os.environ.get('AGENTCON_UNDER_TEST') == '1' and os.environ.get('REDIS_DB') not in (None, '', '0')
    assert RedisHub().db != 0


def test_under_the_mark_database_0_is_refused(monkeypatch):
    monkeypatch.delenv('REDIS_DB')
    with pytest.raises(RuntimeError, match='redis_production_db_in_tests'):
        RedisHub()
    with pytest.raises(RuntimeError, match='redis_production_db_in_tests'):
        RedisHub(db=0)


def test_without_the_mark_nothing_changes(monkeypatch):
    monkeypatch.delenv('REDIS_DB')
    monkeypatch.delenv('AGENTCON_UNDER_TEST')
    hub = RedisHub()
    assert hub.db == 0 and hub.host == '127.0.0.1' and hub.port == 6379
    assert RedisHub(db=2).db == 2


def test_private_cluster_children_keep_the_mark(tmp_path):
    env = _environment(tmp_path)
    assert env['AGENTCON_UNDER_TEST'] == '1' and env['REDIS_DB'] == '15'


def test_the_mark_can_never_reach_a_service():
    # PM 11-18: the services take only allow-listed keys from agentcon.env and sponsored.env (service_host); the mark
    # in either list would block the production Redis
    from scripts.agentcon_config import ALLOWED_KEYS, SPONSORED_KEYS
    assert 'AGENTCON_UNDER_TEST' not in ALLOWED_KEYS and 'AGENTCON_UNDER_TEST' not in SPONSORED_KEYS
