"""A v2 migration must never break the application store's startup checks (2026-11-10 outage).

The application store refuses a database whose public schema has any non-internal trigger besides
its own five (`_validate_native_invariants`). v2 keeps its tables, functions and triggers in its own
schema so a migration leaves the application schema untouched.
"""
from uuid import uuid4

import psycopg
import pytest

from agent_market.storage_adapter import open_store
from tests.test_ad_coin_postgres import PORT, cluster  # noqa: F401


@pytest.fixture
def database(cluster):  # noqa: F811
    name = 'coexist_' + uuid4().hex
    with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres',
                         autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))

    def connect():
        return psycopg.connect(host=cluster['socket'], port=PORT, dbname=name, user='postgres', autocommit=True)
    return connect


def open_application(connect, *, initialize=False):
    return open_store('postgresql', connection=connect(), initialize=initialize)


def test_application_store_still_opens_after_a_v2_migration(database):
    from agent_market.ad_coin.v2.store import ModelStore
    from scripts import ad_coin_v2_migrate as tool
    open_application(database, initialize=True)._connection.close()
    v2 = ModelStore.postgres(database, maximum=2)
    result = tool.run(v2, 'migrate')
    assert result['existing_tables'] == result['expected_tables']
    store = open_application(database)  # raises schema_invariants_mismatch if v2 leaked a trigger into public
    with store.tx(readonly=True):
        store._validate_native_invariants()
    tool.preflight(database)
    with database() as connection:
        public = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                                    "AND tablename LIKE 'adc2%'").fetchone()[0]
        triggers = connection.execute("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                                      "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                                      "AND NOT t.tgisinternal AND t.tgname LIKE 'adc2%'").fetchone()[0]
    assert public == 0 and triggers == 0
    v2.close()


def test_migration_tool_preflight_refuses_when_the_application_check_would_fail(database):
    from agent_market.ad_coin.v2.store import ModelStore
    from scripts import ad_coin_v2_migrate as tool
    open_application(database, initialize=True)._connection.close()
    with database() as connection:  # simulate a stray trigger in public, like the outage
        connection.execute("CREATE FUNCTION stray() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$")
        connection.execute("CREATE TABLE stray_t (id int)")
        connection.execute("CREATE TRIGGER stray_trigger BEFORE INSERT ON stray_t FOR EACH ROW EXECUTE FUNCTION stray()")
    with pytest.raises(RuntimeError, match='application store check'):
        tool.preflight(database)
    v2 = ModelStore.postgres(database, maximum=1)
    v2.close()


def _recreate_outage(connect):
    """Run the v2 DDL straight into public, as the first migration did on 2026-11-10."""
    from agent_market.ad_coin.v2.schema import statements
    with connect() as connection:
        for sql in statements():
            if not sql.startswith('CREATE SCHEMA'):
                connection.execute(sql)
        connection.execute("INSERT INTO adc2_schema VALUES (1,10,'model',0)")


def test_public_leftovers_from_the_outage_can_be_dropped_and_the_application_recovers(database):
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.ad_coin.v2.store import ModelStore
    from scripts import ad_coin_v2_migrate as tool
    open_application(database, initialize=True)._connection.close()
    _recreate_outage(database)
    with pytest.raises(ApplicationStoreError, match='schema_invariants_mismatch'):
        open_application(database)
    v2 = ModelStore.postgres(database, maximum=1)
    before = tool.public_leftovers(v2)
    assert before['tables'] == 54 and len(before['functions']) == 5 and before['data_tables'] == {}
    after = tool.public_leftovers(v2, drop=True)
    assert after['dropped'] and tool.public_leftovers(v2)['tables'] == 0
    tool.preflight(database)
    v2.close()


def test_public_leftovers_with_real_data_are_not_dropped(database):
    from agent_market.ad_coin.v2.store import ModelStore
    from scripts import ad_coin_v2_migrate as tool
    _recreate_outage(database)
    with database() as connection:
        connection.execute("INSERT INTO adc2_audit_log VALUES ('x',1,'e',NULL,NULL,NULL,NULL,NULL,'succeeded','{}')")
    v2 = ModelStore.postgres(database, maximum=1)
    with pytest.raises(RuntimeError, match='hold data'):
        tool.public_leftovers(v2, drop=True)
    assert tool.public_leftovers(v2)['tables'] == 54
    v2.close()


def test_a_new_process_attaches_to_a_migrated_schema_without_ddl(database):
    """Production processes never migrate: a fresh store must become ready from the existing schema."""
    from agent_market.ad_coin.v2.store import ModelStore
    from scripts import ad_coin_v2_migrate as tool
    fresh = ModelStore.postgres(database, maximum=1)
    assert not fresh.attach()  # nothing migrated yet: stays closed
    tool.run(ModelStore.postgres(database, maximum=1), 'migrate')
    later = ModelStore.postgres(database, maximum=1)
    with later.atomic():  # attaches on first use
        assert later.one('schema_get')['version'] >= 10
    with database() as connection:  # a schema of another version is refused
        connection.execute("UPDATE ad_coin_v2.adc2_schema SET version=999")
    other = ModelStore.postgres(database, maximum=1)
    assert not other.attach()
