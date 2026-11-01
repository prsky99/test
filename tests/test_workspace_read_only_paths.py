"""11-01: workspace pages that only read must not take the PostgreSQL global writer lock.

A busy background writer made the session check and Support reads time out (lock_timeout 1s, 500).
These checks keep every page read on a read-only transaction and every write where it was.
"""
import ast
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'agent_market'


def _methods(path):
    tree = ast.parse((ROOT / path).read_text())
    found = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef):
                found[(cls.name, fn.name)] = ast.unparse(fn)
    return found


def _body(path, cls, name):
    return _methods(path)[(cls, name)]


def test_page_reads_use_read_only_transactions():
    expected = {
        ('customer_credits.py', 'CustomerCredits', 'status'): 'self.identity.read_tx()',
        ('customer_credits.py', 'CustomerCredits', 'quote'): 'self.identity.read_tx()',
        ('workspace_typed_flows.py', 'TypedFlows', 'options'): 'self.access._tx(actor, readonly=True)',
        ('workspace_typed_flows.py', 'TypedFlows', 'listing'): 'self.access._tx(actor, readonly=True)',
        ('workspace_typed_flows.py', 'TypedFlows', 'runs'): 'self.access._tx(actor, readonly=True)',
    }
    for (path, cls, name), marker in expected.items():
        assert marker in _body(path, cls, name), (path, name)
    organizations = _methods('customer_organizations.py')
    reads = {name for (_, name), body in organizations.items() if 'self._read(actor)' in body}
    assert reads == {'list', 'detail', 'members', 'audit', 'runtime_actor', 'invitations'}
    connections = [body for (_, name), body in _methods('workspace_provider_connections.py').items() if name == 'listing']
    assert len(connections) == 1 and 'readonly=True' in connections[0]


def test_read_only_paths_contain_no_writes():
    """A read-only transaction would reject a write in production, so none of these may write."""
    organizations = _methods('customer_organizations.py')
    for (_, name), body in organizations.items():
        # invitations reads first and takes the writer lock only when an invitation has lapsed.
        if 'self._read(actor)' in body and name != 'invitations':
            assert not any(word in body for word in ('INSERT', 'UPDATE', 'DELETE', '_audit(', 'emit(')), name
    for name in ('options', 'listing', 'runs'):
        body = _body('workspace_typed_flows.py', 'TypedFlows', name)
        assert not any(word in body for word in ('INSERT', 'UPDATE', 'DELETE', '_audit(', 'emit(')), name


def test_access_read_only_transaction_uses_store_read_mode(monkeypatch):
    from agent_market.workspace_access import WorkspaceAccess
    calls = []

    class Store:
        backend = 'postgresql'

        @contextmanager
        def tx(self, readonly=False):
            calls.append(readonly)
            yield 'db'

    access = WorkspaceAccess.__new__(WorkspaceAccess)
    access.store = Store()
    monkeypatch.setattr(WorkspaceAccess, '_actor', lambda self, actor, write, highest: 'user')
    with access._tx(object(), readonly=True) as (db, user):
        assert (db, user) == ('db', 'user')
    assert calls == [True]


def test_every_access_transaction_accepts_readonly():
    """Typed flows and provider listings run with any access object; each must accept readonly."""
    for path, cls in (('workspace_access.py', 'WorkspaceAccess'), ('customer_workspace_runtime.py', 'CustomerWorkspaceAccess'),
                      ('workspace_machine_automation.py', 'GrantAccess')):
        tree = ast.parse((ROOT / path).read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        tx = next(f for f in node.body if isinstance(f, ast.FunctionDef) and f.name == '_tx')
        assert 'readonly' in [a.arg for a in tx.args.args], cls


def test_customer_access_read_only_transaction_uses_store_read_mode(monkeypatch):
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    calls = []

    class Store:
        backend = 'postgresql'

        @contextmanager
        def tx(self, readonly=False):
            calls.append(readonly)
            yield 'db'

    access = CustomerWorkspaceAccess.__new__(CustomerWorkspaceAccess)
    access.store = Store()
    monkeypatch.setattr(CustomerWorkspaceAccess, '_actor', lambda self, actor, write, highest: 'customer')
    with access._tx(object(), readonly=True) as (db, user):
        assert (db, user) == ('db', 'customer')
    assert calls == [True]


def test_invitations_take_the_writer_lock_only_to_expire(monkeypatch):
    from agent_market import customer_organizations as module
    calls = []

    @contextmanager
    def tracked(kind):
        calls.append(kind)
        yield 'db'
    orgs = module.CustomerOrganizations.__new__(module.CustomerOrganizations)
    monkeypatch.setattr(orgs, '_read', lambda actor: tracked('read'), raising=False)
    monkeypatch.setattr(orgs, '_tx', lambda actor: tracked('write'), raising=False)
    now = 1000.0
    monkeypatch.setattr(module, '_time', lambda: now)
    rows = [{'status': 'pending', 'expires': now + 60}]
    monkeypatch.setattr(orgs, '_invitation_rows', lambda db, actor, ws: rows, raising=False)
    assert orgs.invitations(object()) == rows and calls == ['read']
    calls.clear(); rows[0]['expires'] = now - 1

    class Db:
        def execute(self, *args):
            calls.append('update')

    @contextmanager
    def write(actor):
        calls.append('write')
        yield Db()
    monkeypatch.setattr(orgs, '_tx', write, raising=False)
    from types import SimpleNamespace
    orgs.invitations(SimpleNamespace(customer_id='cu_x'))
    assert calls == ['read', 'write', 'update']


def test_customer_options_label_candidates_without_the_writer_lock():
    body = _body('customer_authoring.py', 'CustomerOwnedTypedFlows', 'options')
    assert 'self.access._tx(actor, readonly=True)' in body
    assert not any(word in body for word in ('INSERT', 'UPDATE', 'DELETE', '_audit(', 'emit('))


def test_every_typed_flow_engine_names_its_executor():
    """11-01: a release once shipped without EXECUTOR; runs must record which engine re-checks them."""
    from agent_market.workspace_typed_flows import TypedFlows
    from agent_market.customer_authoring import CustomerOwnedTypedFlows
    from agent_market.workspace_typed_release import CustomerTypedFlows as ReleaseTypedFlows
    assert (TypedFlows.EXECUTOR, CustomerOwnedTypedFlows.EXECUTOR, ReleaseTypedFlows.EXECUTOR) == ('admin', 'customer', 'customer_app')
    assert "run['executor'] = self.EXECUTOR" in (ROOT / 'workspace_typed_flows.py').read_text()
