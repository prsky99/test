"""Bounded virtual-finance inputs and explicit native credential key handling."""
import hashlib
import hmac
import math

import pytest

from agent_market.application_store_finance import PostgresFinanceMixin, KEY_PURPOSE, _receipt
from agent_market.credential_vault import CredentialVault


class NoDatabase(PostgresFinanceMixin):
    workflow_key = b'k' * 32

    def tx(self, **_kwargs):
        pytest.fail('Invalid input reached the database')


@pytest.mark.parametrize('key', [None, b'', b'x' * 31, b'x' * 33, 'x' * 32, bytearray(b'x' * 32)])
def test_explicit_vault_key_rejects_implicit_or_wrong_types_without_filesystem(key, monkeypatch):
    monkeypatch.setattr(CredentialVault, '_load_key', lambda *_: pytest.fail('Filesystem fallback'))
    with pytest.raises(ValueError): CredentialVault.from_key(key)


def test_native_vault_key_purpose_is_distinct_and_binds_name(monkeypatch):
    monkeypatch.setattr(CredentialVault, '_load_key', lambda *_: pytest.fail('Filesystem fallback'))
    store = NoDatabase()
    vault = store._vault()
    assert vault.key == hmac.new(store.workflow_key, KEY_PURPOSE, hashlib.sha256).digest()
    sealed = vault.seal('WORKFLOW_KEY', 'synthetic-private-secret')
    assert vault.open('WORKFLOW_KEY', sealed) == 'synthetic-private-secret'
    for name, key in [('OTHER_KEY', vault.key), ('WORKFLOW_KEY', store.workflow_key)]:
        with pytest.raises(ValueError): CredentialVault.from_key(key).open(name, sealed)
    store.workflow_key = b'z' * 32
    with pytest.raises(ValueError): store._vault().open('WORKFLOW_KEY', sealed)


@pytest.mark.parametrize('method,args', [('get_credential', ('KEY',)), ('list_credentials', ()),
                                        ('set_credential', ('KEY', 'value', 'fixture')),
                                        ('delete_credential', ('KEY',))])
def test_native_credentials_require_key_before_any_query(method, args):
    store = NoDatabase(); store.workflow_key = None
    with pytest.raises(ValueError, match='explicit stable'): getattr(store, method)(*args)


@pytest.mark.parametrize('amount', [True, False, 0, -1, 1.5, '10', 10**12 + 1, 2**63, math.nan])
def test_invalid_credit_amounts_cannot_reach_native_transaction(amount):
    store = NoDatabase()
    for method, args in [('deposit_credit', ('fixture', amount)), ('hold_credit', ('fixture', amount, 1, 'tool')),
                         ('withdraw_credit', ('fixture', amount, '0x' + '3' * 40))]:
        with pytest.raises(ValueError): getattr(store, method)(*args)


@pytest.mark.parametrize('account', ['', None, 1, 'x' * 257, 'bad\0account', '\ud800'])
def test_invalid_account_reference_cannot_query_or_mutate(account):
    store = NoDatabase()
    with pytest.raises(ValueError): store.get_credit(account)
    with pytest.raises(ValueError): store.deposit_credit(account, 1)


@pytest.mark.parametrize('value', [True, -1, math.inf, math.nan, '900', 31536001])
def test_hold_sweeper_retention_is_finite_and_bounded(value):
    with pytest.raises(ValueError): NoDatabase().sweep_orphaned_holds(value)


@pytest.mark.parametrize('value', [[], 'receipt', {'latency_ms': math.nan}, {'secret': 'x' * 65536},
                                  {'value': '\ud800'}, {'value': '\0'}, {'value': 2**63}, {1: 'value'},
                                  {'value': [None] * 1024}])
def test_receipt_is_bounded_and_finite_before_transaction(value):
    with pytest.raises(ValueError): _receipt(value)


def test_legacy_virtual_operations_do_not_import_payment_or_provider_clients():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('agent_market/application_store_finance.py').read_text())
    imported = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
    assert not any(name.startswith(('httpx', 'requests', 'web3', 'eth_account')) or 'payment' in name for name in imported)
    assert NoDatabase.legacy_finance_mode == 'virtual_ledger_only'


def test_native_finance_runner_requires_opt_in_and_rejects_operating_parameters(monkeypatch):
    from scripts import rehearse_application_finance_postgres as runner
    monkeypatch.setattr(runner, 'rehearse', lambda: pytest.fail('Invalid CLI reached a database'))
    with pytest.raises(SystemExit): runner.main([])
    with pytest.raises(SystemExit): runner.main(['--run', '--dsn', 'postgresql://operating.invalid/database'])
