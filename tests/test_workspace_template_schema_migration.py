"""Additive migration cannot alter an existing schema or reject PG18 NOT NULL."""
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from scripts.migrate_workspace_template_hub import migrate, TABLE
from agent_market.application_store_postgres import _CATALOG, PROFILE, PostgresApplicationStore


class Connection:
    def __init__(self, present=True, valid=True):
        self.present=present;self.valid=valid;self.commands=[]
    def transaction(self):return nullcontext()
    def execute(self, query, values=()):
        self.commands.append(query)
        if query.startswith('CREATE TABLE'):self.present=True
        if query.startswith('SELECT profile'):value=[(PROFILE,)]
        elif query.startswith('SELECT to_regclass'):value=[(TABLE if self.present else None,)]
        elif query.startswith('SELECT column_name'):value=PostgresApplicationStore._expected_columns(None,TABLE) if self.valid else []
        elif query.startswith('SELECT array_agg'):value=[(['id'],)]
        elif query.startswith('SELECT contype'):
            value=[('p',)] if "contype<>'n'" in query else [('p',),('n',)]
        elif query.startswith('SELECT indexdef'):value=[('CREATE INDEX idx_workspace_template_records_scope ON public.workspace_template_records USING btree (workspace_id, kind, parent, created)',)]
        else:value=[]
        return SimpleNamespace(fetchone=lambda:value[0] if value else None,fetchall=lambda:value)


def test_read_only_schema_check_accepts_postgresql18_not_null_metadata():
    connection=Connection();assert migrate(connection,_CATALOG)['ready']
    assert not any(q.startswith(('CREATE','ALTER','DROP','INSERT','UPDATE','DELETE')) for q in connection.commands)


def test_missing_template_table_is_reported_without_implicit_creation():
    connection=Connection(False);assert not migrate(connection,_CATALOG)['ready']
    assert not any(q.startswith('CREATE') for q in connection.commands)


def test_apply_creates_only_the_reviewed_table_and_index():
    connection=Connection(False);result=migrate(connection,_CATALOG,apply=True)
    assert result['table_created'] and result['ready']
    commands=[q for q in connection.commands if q.startswith('CREATE')]
    assert len(commands)==2 and all(TABLE in q for q in commands)
    assert not any(q.startswith(('ALTER','DROP','INSERT','UPDATE','DELETE')) for q in connection.commands)


def test_existing_schema_difference_never_triggers_automatic_alteration():
    connection=Connection(valid=False)
    with pytest.raises(ValueError,match='differs'):migrate(connection,_CATALOG)
    assert not any(q.startswith(('ALTER','DROP','CREATE')) for q in connection.commands)
