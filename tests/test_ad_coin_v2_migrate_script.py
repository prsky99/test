"""The v2 migration tool plans without a connection, refuses migrate without approval, and is idempotent."""
import pytest

from scripts import ad_coin_v2_migrate as tool
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def test_plan_lists_only_additive_changes():
    plan = tool.plan()
    assert plan['schema_version'] >= 9 and len(plan['tables']) >= 50 and not plan['drops_or_deletes_data']
    assert all(name.startswith('adc2_') for name in plan['tables'])


def test_migrate_needs_the_approval_flag():
    with pytest.raises(SystemExit):
        tool.main(['migrate', '--dsn-file', 'x', '--key-file', 'y'])


def test_status_then_migrate_twice_on_an_empty_database(store):  # noqa: F811
    before = tool.run(store, 'status')
    assert before['existing_tables'] == 0 and before['schema'] is None
    first = tool.run(store, 'migrate')
    again = tool.run(store, 'migrate')
    assert first['existing_tables'] == again['existing_tables'] == first['expected_tables']
    assert first['schema']['real_value'] == 0 and first['schema']['environment'] == 'model'
