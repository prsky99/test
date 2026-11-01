"""Typed runs return to the engine that admitted them (production since executor-fix r2, 11-01).

The code lived only in releases until 11-02; a release built from a copy without it sent customer
and customer-app runs to the staff engine, whose membership check rejects their identity.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agent_market import customer_authoring, service_host
from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_platform import typed_engine_for


class Db:
    def __init__(self, linked):
        self.linked, self.sql = linked, []

    def execute(self, sql, params):
        self.sql.append(sql)
        return SimpleNamespace(fetchone=lambda: {'ticket_id': params[0]} if self.linked else None)


def world(monkeypatch, run, claims, linked=False):
    db = Db(linked)

    @contextmanager
    def internal():
        yield db

    admin = SimpleNamespace(name='admin', execution=SimpleNamespace(_internal=internal),
                            _run=lambda d, ws, flow, identity: (run, {'id': 't1'}, claims))
    customer = SimpleNamespace(name='customer')
    monkeypatch.setattr(customer_authoring, 'authoring_for', lambda platform: SimpleNamespace(typed=customer))
    return SimpleNamespace(typed_flows=admin, app_typed_flows=SimpleNamespace(name='customer_app')), db


@pytest.mark.parametrize('executor', ['admin', 'customer_app', 'customer'])
def test_recorded_executor_picks_its_engine(monkeypatch, executor):
    platform, db = world(monkeypatch, {'executor': executor}, {'actor_kind': 'customer'})
    assert typed_engine_for(platform, 'id', 'ws', 'flow').name == executor
    assert db.sql == []


@pytest.mark.parametrize('claims,linked,expected', [
    ({'actor_kind': 'staff'}, False, 'admin'),
    ({}, True, 'admin'),
    ({'actor_kind': 'customer'}, True, 'customer_app'),
    ({'actor_kind': 'customer'}, False, 'customer'),
])
def test_runs_admitted_before_the_engine_was_recorded(monkeypatch, claims, linked, expected):
    platform, _ = world(monkeypatch, {}, claims, linked)
    assert typed_engine_for(platform, 'id', 'ws', 'flow').name == expected


def test_unknown_executor_is_denied(monkeypatch):
    platform, _ = world(monkeypatch, {'executor': 'someone_else'}, {})
    with pytest.raises(WorkspaceDenied):
        typed_engine_for(platform, 'id', 'ws', 'flow')


def test_service_host_runs_through_the_admitting_engine(monkeypatch):
    calls = []
    engine = SimpleNamespace(execute_admitted=lambda *a: calls.append(a) or 'done')
    monkeypatch.setattr('agent_market.workspace_platform.typed_engine_for', lambda platform, *item: engine)
    assert service_host.execute_typed(object(), 'id', 'ws', 'flow') == 'done'
    assert calls == [('id', 'ws', 'flow')]


def test_lookup_sql_is_registered():
    import json
    from pathlib import Path
    registered = Path(service_host.__file__).with_name('application_store_sql.json').read_text()
    assert json.dumps('SELECT * FROM workspace_app_run_links WHERE ticket_id=?') in registered
