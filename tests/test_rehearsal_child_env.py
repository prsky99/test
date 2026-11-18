"""11-18 (검색과 RAG): children of a private cluster never reach the production Redis database (0)."""
from pathlib import Path

from scripts.rehearse_storage_adapter_postgres import _environment


def test_children_use_the_tests_redis_database(tmp_path: Path):
    env = _environment(tmp_path)
    assert env.get('REDIS_DB') not in (None, '', '0')
    assert 'OWNED_NEWS_BUNDLE' in env and str(tmp_path) in env['OWNED_NEWS_BUNDLE']
