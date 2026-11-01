"""Reject operating schema names before any PostgreSQL connection can be used."""
import pytest

from scripts.rehearse_recommendation_circuit_existing_postgres import require_schema, ScopedConsumer


@pytest.mark.parametrize('name', ['public', 'pg_catalog', 'pg_temp', '', None,
    'ax_circuit_check_'+'a'*23, 'ax_circuit_check_'+'a'*25,
    'ax_circuit_check_'+'g'*24, 'ax_circuit_check_'+'a'*24+';DROP SCHEMA public'])
def test_rehearsal_refuses_non_owned_schema_names_before_database_access(name):
    with pytest.raises(ValueError, match='invalid_rehearsal_schema'):
        ScopedConsumer(object(), name)


def test_rehearsal_accepts_only_generated_schema_namespace():
    name = 'ax_circuit_check_'+'a'*24
    assert require_schema(name) == name
