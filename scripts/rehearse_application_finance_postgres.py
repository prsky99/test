"""Verify native credentials and virtual credit/clearing contracts in a private DB.

Only --run is accepted. No database address, operating path, account, secret or
provider destination may be supplied. No payment or payout is submitted.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from scripts.rehearse_storage_adapter_postgres import _driver, _private_cluster, _tools, PORT

PROFILE = 'native-virtual-finance-credentials-v1'
CHECKS = frozenset('''
all_virtual_accounts_conserve_deposits_and_escrow bounded_sweeper_refunds_only_expired_held_rows
all_fresh_mutators_reject_inconsistent_accounts orphan_ledger_account_not_recreated
ciphertext_preserved_after_rejected_keys clearing_exact_lookup_and_absent_parity
clearing_filters_pagination_and_result_parity concurrent_deposits_have_no_lost_update
corrupted_reservation_amount_denies_mutation corrupted_reservation_status_denies_mutation
concurrent_holds_never_overreserve concurrent_settle_refund_has_one_terminal_winner
concurrent_virtual_withdrawals_never_overdraw credential_ciphertext_tamper_denied
credential_delete_existing_and_absent_parity credential_key_purpose_separated
credential_name_swap_denied credentials_encrypted_name_bound_and_masked
empty_ciphertext_list_denied_without_repair wrong_key_cannot_overwrite_delete_or_mix_ciphertext
explicit_stable_key_reopens_without_filesystem integer_overflow_denied_before_mutation
hostile_latency_samples_safe_without_receipt_rewrite malformed_stored_receipt_fails_closed_without_rewrite
ledger_unique_collision_rolls_back_prior_reservation legacy_account_aliases_and_case_filter_parity
legacy_balance_and_account_result_parity legacy_overview_integer_and_sla_parity
legacy_sla_json_boolean_and_string_coercion_parity missing_key_fails_without_ciphertext_rewrite
native_admin_credential_permission_and_origin_boundary native_admin_credential_response_has_no_plaintext
native_admin_virtual_finance_requires_superadmin native_readonly_denies_virtual_finance_write
native_admin_sla_summary_is_finite
overdraft_is_atomic python_tcp_network_creation_blocked_and_unused
terminal_escrow_duplicate_commands_never_debit_twice wrong_key_fails_without_ciphertext_rewrite
'''.split())


def require(value, message):
    if value is not True: raise AssertionError(message)


def _contracts(connect):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.application_store_postgres import PostgresApplicationStore, ApplicationStoreError
    from agent_market.application_store_finance import PostgresFinanceMixin
    from agent_market.credential_vault import CredentialVault, PREFIX
    from agent_market.gateway.store import Store
    from agent_market.gateway import admin_auth
    from agent_market.gateway.dashboard import dashboard_router

    pg = connect()
    store = PostgresApplicationStore(pg, initialize=True, workflow_key=b'k' * 32)
    reference = Store()
    checks = {}
    try:
        require(isinstance(store, PostgresFinanceMixin), 'native finance mixin integrated')
        store.set_credential('FIXTURE_KEY', 'synthetic-private-value-1234', 'fixture', 'Bounded metadata')
        reference.set_credential('FIXTURE_KEY', 'synthetic-private-value-1234', 'fixture', 'Bounded metadata')
        with pg.cursor() as cursor:
            cursor.execute('SELECT key_value FROM platform_credentials WHERE key_name=%s', ('FIXTURE_KEY',))
            sealed = cursor.fetchone()[0]
        checks['credentials_encrypted_name_bound_and_masked'] = (sealed.startswith(PREFIX)
            and 'synthetic-private' not in sealed and store.get_credential('FIXTURE_KEY') == 'synthetic-private-value-1234'
            and [{k: row[k] for k in ('key_name', 'masked_value', 'has_value', 'provider', 'description')}
                 for row in store.list_credentials()] == [{k: row[k] for k in ('key_name', 'masked_value', 'has_value', 'provider', 'description')}
                 for row in reference.list_credentials()])
        reopened = PostgresApplicationStore(pg, workflow_key=b'k' * 32)
        checks['explicit_stable_key_reopens_without_filesystem'] = reopened.get_credential('FIXTURE_KEY') == 'synthetic-private-value-1234'
        reopened.close()
        for key, label in [(None, 'missing_key'), (b'z' * 32, 'wrong_key')]:
            other = PostgresApplicationStore(pg, workflow_key=key)
            try: other.get_credential('FIXTURE_KEY')
            except ValueError: checks[label + '_fails_without_ciphertext_rewrite'] = True
            else: checks[label + '_fails_without_ciphertext_rewrite'] = False
            finally: other.close()
        other = PostgresApplicationStore(pg, workflow_key=b'z' * 32)
        rejected = 0
        try:
            for operation in (lambda: other.set_credential('FIXTURE_KEY', 'replacement', 'fixture'),
                              lambda: other.set_credential('MIXED_KEY', 'replacement', 'fixture'),
                              lambda: other.delete_credential('FIXTURE_KEY')):
                try: operation()
                except ValueError: rejected += 1
        finally: other.close()
        checks['wrong_key_cannot_overwrite_delete_or_mix_ciphertext'] = rejected == 3 and store.get_credential('MIXED_KEY') is None and store.get_credential('FIXTURE_KEY') == 'synthetic-private-value-1234'
        try: CredentialVault.from_key(b'k' * 32).open('FIXTURE_KEY', sealed)
        except ValueError: checks['credential_key_purpose_separated'] = True
        else: checks['credential_key_purpose_separated'] = False
        with pg.cursor() as cursor:
            cursor.execute('UPDATE platform_credentials SET key_name=%s WHERE key_name=%s', ('SWAPPED_KEY', 'FIXTURE_KEY'))
        try: store.get_credential('SWAPPED_KEY')
        except ValueError: checks['credential_name_swap_denied'] = True
        else: checks['credential_name_swap_denied'] = False
        with pg.cursor() as cursor:
            cursor.execute('UPDATE platform_credentials SET key_name=%s,key_value=%s WHERE key_name=%s',
                           ('FIXTURE_KEY', sealed[:-4] + 'AAAA', 'SWAPPED_KEY'))
        try: store.get_credential('FIXTURE_KEY')
        except ValueError: checks['credential_ciphertext_tamper_denied'] = True
        else: checks['credential_ciphertext_tamper_denied'] = False
        with pg.cursor() as cursor:
            cursor.execute('UPDATE platform_credentials SET key_value=%s WHERE key_name=%s', (sealed, 'FIXTURE_KEY'))
        with pg.cursor() as cursor:
            cursor.execute('UPDATE platform_credentials SET key_value=%s WHERE key_name=%s', ('', 'FIXTURE_KEY'))
        try: store.list_credentials()
        except ValueError:
            with pg.cursor() as cursor:
                cursor.execute('SELECT key_value FROM platform_credentials WHERE key_name=%s', ('FIXTURE_KEY',))
                checks['empty_ciphertext_list_denied_without_repair'] = cursor.fetchone()[0] == ''
        else: checks['empty_ciphertext_list_denied_without_repair'] = False
        with pg.cursor() as cursor:
            cursor.execute('UPDATE platform_credentials SET key_value=%s WHERE key_name=%s', (sealed, 'FIXTURE_KEY'))
        checks['ciphertext_preserved_after_rejected_keys'] = store.get_credential('FIXTURE_KEY') == 'synthetic-private-value-1234'
        store.set_credential('DELETE_KEY', 'temporary', 'fixture')
        checks['credential_delete_existing_and_absent_parity'] = store.delete_credential('DELETE_KEY') is True and store.delete_credential('DELETE_KEY') is False

        for current in (store, reference):
            current.deposit_credit('parity', 1000)
            first = current.hold_credit('parity', 200, 1, 'search')
            current.settle_credit(first, {'latency_ms': 12.5, 'sla_verified': True})
            second = current.hold_credit('parity', 150, 2, 'docs')
            current.refund_credit(second, 'Synthetic cancellation')
            current.withdraw_credit('parity', 100, '0x' + '3' * 40)
        checks['legacy_balance_and_account_result_parity'] = store.get_credit('parity') == reference.get_credit('parity')
        checks['legacy_overview_integer_and_sla_parity'] = store.get_clearing_overview() == reference.get_clearing_overview()
        left, total = store.list_clearing_transactions(status='settled', account_id='PARITY')
        right, expected = reference.list_clearing_transactions(status='settled', account_id='PARITY')
        checks['clearing_filters_pagination_and_result_parity'] = (total == expected == 1
            and [{k: row[k] for k in ('account_id', 'resource_id', 'tool_name', 'amount', 'status', 'sla_verified', 'receipt')} for row in left]
            == [{k: row[k] for k in ('account_id', 'resource_id', 'tool_name', 'amount', 'status', 'sla_verified', 'receipt')} for row in right]
            and store.list_clearing_transactions(offset=100)[0] == [])
        left, total = store.list_agent_credits(q='PARITY'); right, expected = reference.list_agent_credits(q='PARITY')
        checks['legacy_account_aliases_and_case_filter_parity'] = total == expected == 1 and all(left[0][key] == right[0][key] for key in left[0] if key != 'updated_at')
        first = store.list_clearing_transactions(status='settled')[0][0]['tx_id']
        before = store.get_credit('parity')
        denied = 0
        for action in (lambda: store.settle_credit(first), lambda: store.refund_credit(first)):
            try: action()
            except ValueError: denied += 1
        checks['terminal_escrow_duplicate_commands_never_debit_twice'] = denied == 2 and store.get_credit('parity') == before
        checks['clearing_exact_lookup_and_absent_parity'] = store.get_clearing_tx(first)['status'] == 'settled' and store.get_clearing_tx('absent') is None
        for latency in (True, False, ' 23.5ms', None, {}, [], '1e2tail'):
            for current in (store, reference):
                tx_id = current.hold_credit('parity', 1, 1, 'latency-coercion')
                current.settle_credit(tx_id, {'latency_ms': latency})
        checks['legacy_sla_json_boolean_and_string_coercion_parity'] = store.get_clearing_overview() == reference.get_clearing_overview()
        baseline = store.get_clearing_overview()['sla']['avg_latency_ms']
        store.deposit_credit('hostile-latency', 10)
        preserved = True
        for latency in ('1e999999999', '9' * 20000, 1e308, -1e308):
            receipt = {'latency_ms': latency, 'note': 'Preserve the original fixture receipt'}
            tx_id = store.hold_credit('hostile-latency', 1, 1, 'synthetic')
            store.settle_credit(tx_id, receipt)
            preserved &= json.loads(store.get_clearing_tx(tx_id)['receipt']) == receipt
        sample = store.get_clearing_overview()['sla']['avg_latency_ms']
        checks['hostile_latency_samples_safe_without_receipt_rewrite'] = preserved and math.isfinite(sample) and sample == baseline
        store.deposit_credit('reservation-integrity', 50)
        reserved = store.hold_credit('reservation-integrity', 10, 1, 'synthetic')
        before = store.get_credit('reservation-integrity')
        with pg.cursor() as cursor: cursor.execute('UPDATE clearing_ledger SET amount=1 WHERE tx_id=%s', (reserved,))
        try: store.settle_credit(reserved)
        except ValueError: checks['corrupted_reservation_amount_denies_mutation'] = store.get_credit('reservation-integrity') == before and store.get_clearing_tx(reserved)['amount'] == 1
        else: checks['corrupted_reservation_amount_denies_mutation'] = False
        with pg.cursor() as cursor:
            cursor.execute("UPDATE clearing_ledger SET amount=10,status='settled' WHERE tx_id=%s", (reserved,))
        try: store.refund_credit(reserved)
        except ValueError: checks['corrupted_reservation_status_denies_mutation'] = store.get_credit('reservation-integrity') == before and store.get_clearing_tx(reserved)['status'] == 'settled'
        else: checks['corrupted_reservation_status_denies_mutation'] = False
        with pg.cursor() as cursor: cursor.execute("UPDATE clearing_ledger SET status='held' WHERE tx_id=%s", (reserved,))
        store.refund_credit(reserved, 'Restore the synthetic corruption fixture')
        original = store.get_clearing_tx(first)['receipt']
        with pg.cursor() as cursor: cursor.execute('UPDATE clearing_ledger SET receipt=%s WHERE tx_id=%s', ('not-json', first))
        try: store.get_clearing_overview()
        except ApplicationStoreError: checks['malformed_stored_receipt_fails_closed_without_rewrite'] = store.get_clearing_tx(first)['receipt'] == 'not-json'
        else: checks['malformed_stored_receipt_fails_closed_without_rewrite'] = False
        with pg.cursor() as cursor: cursor.execute('UPDATE clearing_ledger SET receipt=%s WHERE tx_id=%s', (original, first))
        store.deposit_credit('fresh-write-integrity', 100)
        guarded = store.hold_credit('fresh-write-integrity', 10, 1, 'synthetic')
        with pg.cursor() as cursor:
            cursor.execute('SELECT balance,held,total_deposited,total_spent,updated_at FROM agent_credits WHERE account_id=%s', ('fresh-write-integrity',))
            original_account = cursor.fetchone()
        original_ledger = store.get_clearing_tx(guarded)
        valid = original_account
        corruptions = [(valid[0], -100, valid[2], valid[3], valid[4]),
                       (valid[0], 9, valid[2], valid[3], valid[4]),
                       (valid[0], valid[1], valid[2] + 1, valid[3], valid[4]),
                       (-1, valid[1], valid[2], valid[3], valid[4]),
                       (valid[0], valid[1], valid[2], -1, valid[4])]
        intact = True
        for corrupted in corruptions:
            with pg.cursor() as cursor:
                cursor.execute('UPDATE agent_credits SET balance=%s,held=%s,total_deposited=%s,total_spent=%s,updated_at=%s WHERE account_id=%s', corrupted + ('fresh-write-integrity',))
            rejected = 0
            for operation in (lambda: store.deposit_credit('fresh-write-integrity', 1),
                              lambda: store.hold_credit('fresh-write-integrity', 1, 1, 'synthetic'),
                              lambda: store.withdraw_credit('fresh-write-integrity', 1, '0x' + '3' * 40),
                              lambda: store.settle_credit(guarded), lambda: store.refund_credit(guarded)):
                try: operation()
                except ValueError: rejected += 1
            with pg.cursor() as cursor:
                cursor.execute('SELECT balance,held,total_deposited,total_spent,updated_at FROM agent_credits WHERE account_id=%s', ('fresh-write-integrity',))
                current_account = cursor.fetchone()
                cursor.execute('SELECT COUNT(*) FROM clearing_ledger WHERE account_id=%s', ('fresh-write-integrity',))
                retained = cursor.fetchone()[0]
            intact &= rejected == 5 and current_account == corrupted and retained == 1 and store.get_clearing_tx(guarded) == original_ledger
            require(intact, 'all mutations refuse inconsistent account without partial writes')
        checks['all_fresh_mutators_reject_inconsistent_accounts'] = intact
        with pg.cursor() as cursor: cursor.execute('DELETE FROM agent_credits WHERE account_id=%s', ('fresh-write-integrity',))
        try: store.deposit_credit('fresh-write-integrity', 1)
        except ValueError:
            with pg.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM agent_credits WHERE account_id=%s', ('fresh-write-integrity',))
                checks['orphan_ledger_account_not_recreated'] = cursor.fetchone()[0] == 0 and store.get_clearing_tx(guarded) == original_ledger
        else: checks['orphan_ledger_account_not_recreated'] = False
        with pg.cursor() as cursor:
            cursor.execute('INSERT INTO agent_credits(account_id,balance,held,total_deposited,total_spent,updated_at) VALUES(%s,%s,%s,%s,%s,%s)', ('fresh-write-integrity',) + original_account)
        store.refund_credit(guarded, 'Restore the synthetic invalid-state fixture')
        before = store.get_credit('parity')
        try: store.withdraw_credit('parity', 1000, '0x' + '3' * 40)
        except ValueError: checks['overdraft_is_atomic'] = store.get_credit('parity') == before
        else: checks['overdraft_is_atomic'] = False

        def concurrent(function, count=8):
            barrier = threading.Barrier(count)
            def task(index):
                connection = connect(); current = PostgresApplicationStore(connection, workflow_key=b'k' * 32)
                try:
                    barrier.wait(timeout=10)
                    try: return ('ok', function(current, index))
                    except ValueError: return ('rejected', None)
                finally: current.close(); connection.close()
            with ThreadPoolExecutor(max_workers=count) as pool: return list(pool.map(task, range(count)))

        store.deposit_credit('concurrent-deposit', 1)
        results = concurrent(lambda current, _: current.deposit_credit('concurrent-deposit', 10))
        checks['concurrent_deposits_have_no_lost_update'] = all(status == 'ok' for status, _ in results) and store.get_credit('concurrent-deposit')['balance'] == 81
        store.deposit_credit('concurrent-hold', 100)
        results = concurrent(lambda current, _: current.hold_credit('concurrent-hold', 30, 1, 'synthetic'))
        held = [value for status, value in results if status == 'ok']
        checks['concurrent_holds_never_overreserve'] = len(held) == 3 and store.get_credit('concurrent-hold')['held'] == 90
        for tx_id in held: store.refund_credit(tx_id, 'Cleanup fixture reservation')
        store.deposit_credit('concurrent-finalize', 100)
        tx_id = store.hold_credit('concurrent-finalize', 30, 1, 'synthetic')
        results = concurrent(lambda current, index: current.settle_credit(tx_id, {'latency_ms': 2}) if index == 0 else current.refund_credit(tx_id, 'Race fixture'), 2)
        balance = store.get_credit('concurrent-finalize')
        checks['concurrent_settle_refund_has_one_terminal_winner'] = (sum(status == 'ok' for status, _ in results) == 1
            and balance['held'] == 0 and (balance['balance'], balance['total_spent']) in ((70, 30), (100, 0)))
        store.deposit_credit('concurrent-withdraw', 100)
        results = concurrent(lambda current, _: current.withdraw_credit('concurrent-withdraw', 30, '0x' + '3' * 40))
        checks['concurrent_virtual_withdrawals_never_overdraw'] = sum(status == 'ok' for status, _ in results) == 3 and store.get_credit('concurrent-withdraw')['balance'] == 10
        store.deposit_credit('collision', 100)
        with patch('agent_market.application_store_finance.uuid.uuid4', return_value=SimpleNamespace(hex='f' * 32)):
            store.hold_credit('collision', 20, 1, 'synthetic')
            try: store.hold_credit('collision', 20, 1, 'synthetic')
            except ApplicationStoreError: checks['ledger_unique_collision_rolls_back_prior_reservation'] = store.get_credit('collision')['held'] == 20
            else: checks['ledger_unique_collision_rolls_back_prior_reservation'] = False
        store.deposit_credit('sweep', 100)
        old = store.hold_credit('sweep', 25, 1, 'synthetic')
        fresh = store.hold_credit('sweep', 25, 1, 'synthetic')
        with pg.cursor() as cursor:
            cursor.execute('UPDATE clearing_ledger SET created_at=%s WHERE tx_id=%s', (time.time() - 3600, old))
        swept = store.sweep_orphaned_holds(900)
        checks['bounded_sweeper_refunds_only_expired_held_rows'] = old in swept and fresh not in swept and store.get_credit('sweep')['held'] == 25
        with pg.cursor() as cursor:
            cursor.execute('INSERT INTO agent_credits VALUES(%s,%s,0,%s,0,%s)', ('overflow', 2**63 - 1, 2**63 - 1, time.time()))
        try: store.deposit_credit('overflow', 1)
        except ValueError: checks['integer_overflow_denied_before_mutation'] = store.get_credit('overflow')['balance'] == 2**63 - 1
        else: checks['integer_overflow_denied_before_mutation'] = False
        with pg.cursor() as cursor:
            cursor.execute("SELECT a.account_id,a.balance,a.held,a.total_deposited,a.total_spent,COALESCE(SUM(CASE WHEN l.status='held' THEN l.amount ELSE 0 END),0) FROM agent_credits a LEFT JOIN clearing_ledger l USING(account_id) GROUP BY a.account_id")
            rows = cursor.fetchall()
        checks['all_virtual_accounts_conserve_deposits_and_escrow'] = all(balance >= held >= 0 and deposited == balance + spent and held == reserved for _, balance, held, deposited, spent, reserved in rows)
        before = store.get_credit('parity')
        try:
            with store.tx(readonly=True): store.deposit_credit('parity', 1)
        except ApplicationStoreError: checks['native_readonly_denies_virtual_finance_write'] = store.get_credit('parity') == before
        else: checks['native_readonly_denies_virtual_finance_write'] = False

        with store.tx() as db:
            owner = admin_auth.create_admin_user(db, 'finance-owner', 'Synthetic-owner-password-42', 'Fixture owner', 'superadmin')
            viewer = admin_auth.create_admin_user(db, 'finance-viewer', 'Synthetic-viewer-password-42', 'Fixture viewer', 'operator')
            owner_token = admin_auth.create_session(db, owner['id'], owner['username'], owner['role'], owner['name'])
            viewer_token = admin_auth.create_session(db, viewer['id'], viewer['username'], viewer['role'], viewer['name'])
        app = FastAPI(); app.include_router(dashboard_router(store, ':memory:', 'synthetic-system-token', None))
        headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + owner_token}
        readonly_headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + viewer_token}
        with TestClient(app, base_url='https://admin.example') as client:
            listed = client.get('/admin/api/credentials', headers=headers)
            denied_read = client.get('/admin/api/credentials', headers=readonly_headers)
            denied_write = client.post('/admin/api/credentials', headers=readonly_headers, json={'key_name': 'FORBIDDEN', 'key_value': 'secret'})
            unauthorized = client.get('/admin/api/credentials', headers={'X-Dashboard': '1'})
            cross_origin = client.post('/admin/api/credentials', headers={**headers, 'Origin': 'https://outside.example'}, json={'key_name': 'FORBIDDEN', 'key_value': 'secret'})
            checks['native_admin_credential_permission_and_origin_boundary'] = (listed.status_code == 200
                and denied_read.status_code == denied_write.status_code == cross_origin.status_code == 403
                and unauthorized.status_code == 401 and store.get_credential('FORBIDDEN') is None)
            checks['native_admin_credential_response_has_no_plaintext'] = 'synthetic-private-value-1234' not in listed.text and 'key_value' not in listed.text
            overview = client.get('/admin/api/payments/overview', headers=headers)
            checks['native_admin_sla_summary_is_finite'] = overview.status_code == 200 and math.isfinite(overview.json()['clearinghouse']['sla']['avg_latency_ms'])
            rejected_credit = client.post('/admin/api/payments/deposit', headers=readonly_headers, json={'account_id': 'forbidden', 'amount': 1})
            checks['native_admin_virtual_finance_requires_superadmin'] = rejected_credit.status_code == 403 and store.get_credit('forbidden')['balance'] == 0
        require(all(value is True for value in checks.values()), 'native virtual finance contracts')
        return checks
    finally:
        store.close(); pg.close(); reference._db.close()


def _worker():
    cluster = json.loads(sys.stdin.read(4096)); root = Path(cluster['root'])
    require(root.parent == Path('/private/tmp') and root.name.startswith('a2a-adapter-pg-')
            and cluster['socket'] == str(root / 'socket'), 'owned private cluster')
    require(not any(key.startswith('PG') and key not in ('PGPASSFILE', 'PGSERVICEFILE', 'PGSYSCONFDIR')
                    for key in os.environ), 'clean libpq environment')
    driver = _driver()
    import socket
    forbidden_network = []
    def deny_network(event, arguments):
        if event == 'socket.__new__' and arguments[1] in (socket.AF_INET, socket.AF_INET6):
            import traceback
            forbidden_network.append(''.join(traceback.format_stack(limit=14)))
            raise AssertionError('Only private Unix transport and in-process HTTP are allowed.')
    sys.addaudithook(deny_network)
    # urllib3 otherwise probes IPv6 by binding a temporary loopback socket at
    # import time. This offline fixture needs no IP transport capabilities.
    with patch.object(socket, 'has_ipv6', False):
        import urllib3  # noqa: F401
    from agent_market.infra.redis_hub import RedisHub
    offline_cache = RedisHub(); offline_cache._closed = True
    RedisHub._instance = offline_cache
    def connect():
        connection = driver.connect(host=cluster['socket'], hostaddr='', port=PORT, dbname='postgres', user='postgres',
                                    password='synthetic-unused-password', passfile=str(root / 'no-password-file'),
                                    connect_timeout=3, autocommit=True, sslmode='disable', gssencmode='disable')
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
                require(cursor.fetchone() == ('', None, None) and connection.info.host == cluster['socket'], 'Unix-only transport before initialization')
            return connection
        except BaseException: connection.close(); raise
    checks = _contracts(connect)
    require(not forbidden_network, 'no unexpected Python TCP socket attempts: ' + '\n'.join(forbidden_network))
    checks['python_tcp_network_creation_blocked_and_unused'] = True
    print(json.dumps(checks, allow_nan=False, sort_keys=True))


def rehearse():
    driver = _driver()
    source = ['agent_market/application_store_finance.py', 'agent_market/credential_vault.py',
              'agent_market/application_store_postgres.py', 'agent_market/application_store_sql.json',
              'scripts/rehearse_application_finance_postgres.py']
    before = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source}
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment']); environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c', 'from scripts.rehearse_application_finance_postgres import _worker; _worker()'],
                                env=environment, input=json.dumps({'root': cluster['root'], 'socket': cluster['socket']}),
                                capture_output=True, text=True, timeout=180)
        if result.returncode: raise RuntimeError('Synthetic native finance contract failed: ' + result.stderr[-5000:])
        checks = json.loads(result.stdout)
    after = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source}
    require(before == after and set(checks) == CHECKS and all(value is True for value in checks.values()), 'frozen source and complete native contracts')
    return {'profile': PROFILE, 'checks': checks, 'source_sha256': after, 'source_unchanged_during_run': True,
            'synthetic': True, 'temporary_cluster_removed': True, 'operating_database_writes': 0,
            'external_provider_calls': 0, 'payment_submissions': 0, 'payout_submissions': 0, 'production_cutover': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true'); args = parser.parse_args(argv)
    if not args.run: parser.error('--run is required')
    print(json.dumps(rehearse(), allow_nan=False, sort_keys=True)); return 0


if __name__ == '__main__': raise SystemExit(main())
