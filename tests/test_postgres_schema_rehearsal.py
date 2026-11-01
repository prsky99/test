"""Owned-schema rehearsal safety without operating database access."""
from types import SimpleNamespace

import pytest

from agent_market import postgres_schema_rehearsal as rehearsal
from agent_market.application_store_postgres import ApplicationStoreError, PostgresApplicationStore, _invariant_ddl, WRITER_LOCK


@pytest.mark.parametrize('name', ['public', 'agentcon_search', '', 'ac_b2a_'+'a'*23,
    'ac_b2a_'+'a'*25, 'ac_b2a_'+'A'*24, 'ac_b2a_'+'a'*24+';DROP SCHEMA public'])
def test_only_minted_schema_descriptor_accepted(monkeypatch, name):
    monkeypatch.setattr(rehearsal, '_identity', lambda *_: pytest.fail('Database queried for invalid descriptor'))
    with pytest.raises(ApplicationStoreError, match='rehearsal_schema_invalid'):
        rehearsal._verify_identity(object(), rehearsal.OwnedSchema(name, 1, 2, 3, ('public',)))


@pytest.mark.parametrize('identity', [None, (2, 2, 3, True, True), (1, 4, 3, True, True),
    (1, 2, 4, True, True), (1, 2, 3, False, True), (1, 2, 3, True, False)])
def test_missing_replaced_or_shared_schema_fails_closed(monkeypatch, identity):
    monkeypatch.setattr(rehearsal, '_identity', lambda *_: identity)
    with pytest.raises(ApplicationStoreError, match='rehearsal_schema_identity_changed'):
        rehearsal._verify_identity(object(), rehearsal.OwnedSchema('ac_b2a_'+'a'*24, 1, 2, 3, ('public',)))


@pytest.mark.parametrize('autocommit,status', [(False, 0), (True, 2), (True, 3)])
def test_caller_transaction_is_never_reused(autocommit, status):
    connection = SimpleNamespace(autocommit=autocommit, info=SimpleNamespace(transaction_status=status))
    with pytest.raises(ApplicationStoreError, match='connection_busy'):
        with rehearsal.owned_schema(connection):
            pytest.fail('Busy connection accepted')


def _store(monkeypatch):
    schema = rehearsal.OwnedSchema('ac_b2a_'+'a'*24, 1, 2, 3, ('public', 'agentcon_search', 'other_fixture'))
    monkeypatch.setattr(rehearsal, '_verify_identity', lambda *_: None)
    monkeypatch.setattr(PostgresApplicationStore, '__init__', lambda *a, **k: None)
    return rehearsal.SchemaRehearsalStore(object(), schema)


@pytest.mark.parametrize('statement', ['SELECT * FROM public.resources',
    'DELETE FROM "PUBLIC" . resources', "SELECT to_regclass('agentcon_search.configuration')",
    'SELECT * FROM other_fixture.resources'])
def test_qualified_operating_schema_never_reaches_driver(monkeypatch, statement):
    store = _store(monkeypatch)
    monkeypatch.setattr(PostgresApplicationStore, '_native', lambda *a: pytest.fail('Escaping SQL reached driver'))
    with pytest.raises(ApplicationStoreError, match='rehearsal_schema_escape'):
        store._native(statement)


def test_private_queries_preserve_bound_values_and_skip_operating_indexes(monkeypatch):
    store = _store(monkeypatch)
    seen = []
    monkeypatch.setattr(PostgresApplicationStore, '_native', lambda _, text, params: seen.append((text, params)))
    store._native('SELECT * FROM resources WHERE name=%s', ('public.resources',))
    assert seen == [('SELECT * FROM resources WHERE name=%s', ('public.resources',))]
    assert store._writer_identity() < 0 and store._writer_identity() != WRITER_LOCK
    assert store._ann_available() is store._lexical_available() is False
    assert store._schema_namespace() == 'ac_b2a_'+'a'*24


def test_default_runtime_keeps_public_namespace_and_writer_lock():
    store = object.__new__(PostgresApplicationStore)
    assert store._schema_namespace() == 'public'
    assert store._writer_identity() == WRITER_LOCK
    default = '\n'.join(_invariant_ddl())
    assert 'public.test_report_subject_claims' in default
    private = '\n'.join(_invariant_ddl('ac_b2a_'+'a'*24))
    assert 'public.test_report_subject_claims' not in private
    assert '"ac_b2a_'+'a'*24+'".test_report_subject_claims' in private
    with pytest.raises(ValueError):
        _invariant_ddl('public; DROP TABLE resources')
