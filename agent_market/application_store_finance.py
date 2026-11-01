"""Native PostgreSQL repositories for existing virtual credits and credentials.

These methods preserve the legacy Store result shapes. They only update the
virtual ledger; they do not submit payments, withdrawals or provider requests.
Credential encryption requires the caller's explicit stable workflow key.
"""
import hashlib
import hmac
import json
import math
import time
import uuid

from .credential_vault import CredentialVault

MAX_INTEGER = 2**63 - 1
MAX_AMOUNT = 10**12
MAX_SWEEP = 1000
KEY_PURPOSE = b'agent-concierge:postgres-platform-credentials:v1'


def _text(value, *, limit=256, empty=False):
    if type(value) is not str or '\0' in value or (not value and not empty):
        raise ValueError('Invalid bounded text value.')
    try:
        if len(value.encode('utf-8')) > limit:
            raise ValueError('Text value exceeds its storage limit.')
    except UnicodeError:
        raise ValueError('Invalid text encoding.') from None
    return value


def _amount(value, action):
    if type(value) is not int or not 1 <= value <= MAX_AMOUNT:
        raise ValueError(action + ' amount must be positive.')
    return value


def _receipt(value):
    if value is not None and type(value) is not dict:
        raise ValueError('A receipt must be a bounded JSON object.')
    try:
        pending, count = [(value, 0)], 0
        while pending:
            current, depth = pending.pop()
            count += 1
            if count > 1024 or depth > 16:
                raise ValueError
            if type(current) is dict:
                if any(type(key) is not str for key in current):
                    raise ValueError
                pending.extend((item, depth + 1) for pair in current.items() for item in pair)
            elif type(current) is list:
                pending.extend((item, depth + 1) for item in current)
            elif type(current) is str:
                if '\0' in current:
                    raise ValueError
                current.encode('utf-8')
            elif type(current) is int:
                if not -MAX_INTEGER - 1 <= current <= MAX_INTEGER:
                    raise ValueError
            elif type(current) is float:
                if not math.isfinite(current):
                    raise ValueError
            elif current is not None and type(current) is not bool:
                raise ValueError
        packed = json.dumps(value or {}, allow_nan=False)
        if len(packed.encode('utf-8')) > 65536:
            raise ValueError
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ValueError('A receipt must be a bounded JSON object.') from None
    return packed


class PostgresFinanceMixin:
    """Fixed SQL repositories using the Store's native transaction boundary."""

    legacy_finance_mode = 'virtual_ledger_only'

    def _vault(self):
        key = getattr(self, 'workflow_key', None)
        if type(key) is not bytes or len(key) != 32:
            raise ValueError('An explicit stable credential encryption key is required.')
        # The signing key is not used directly as an AES key. Purpose separation
        # also prevents another use of the same root key from decrypting a row.
        return CredentialVault.from_key(hmac.new(key, KEY_PURPOSE, hashlib.sha256).digest())

    def get_credential(self, key_name):
        _text(key_name)
        vault = self._vault()
        with self.tx(readonly=True):
            row = self._execute('SELECT key_value FROM platform_credentials WHERE key_name=%s',
                                (key_name,)).fetchone()
        return vault.open(key_name, row['key_value']) if row else None

    def list_credentials(self):
        vault = self._vault()
        with self.tx(readonly=True):
            rows = self._execute('SELECT id,key_name,key_value,provider,description,updated_at '
                                 'FROM platform_credentials ORDER BY updated_at DESC').fetchall()
        result = []
        for row in rows:
            value = vault.open(row['key_name'], row['key_value'])
            masked = value[:3] + '...' + value[-4:] if len(value) > 7 else '*' * len(value)
            result.append({'id': row['id'], 'key_name': row['key_name'], 'masked_value': masked,
                           'has_value': bool(value), 'provider': row['provider'],
                           'description': row['description'] or '', 'updated_at': row['updated_at']})
        return result

    def set_credential(self, key_name, key_value, provider, description=''):
        _text(key_name)
        _text(key_value, limit=65536, empty=True)
        _text(provider, limit=256, empty=True)
        _text(description, limit=4096, empty=True)
        vault = self._vault()
        sealed = vault.seal(key_name, key_value)
        with self.tx():
            # Reject a wrong root key before replacing or mixing ciphertext.
            # Native storage never migrates plaintext or repairs failed tags.
            rows = self._execute('SELECT key_name,key_value FROM platform_credentials').fetchall()
            for row in rows:
                vault.open(row['key_name'], row['key_value'])
            self._execute('INSERT INTO platform_credentials(key_name,key_value,provider,description,updated_at) '
                          'VALUES(%s,%s,%s,%s,%s) ON CONFLICT(key_name) DO UPDATE SET '
                          'key_value=EXCLUDED.key_value,provider=EXCLUDED.provider,'
                          'description=EXCLUDED.description,updated_at=EXCLUDED.updated_at',
                          (key_name, sealed, provider, description, time.time()))

    def delete_credential(self, key_name):
        _text(key_name)
        vault = self._vault()
        with self.tx():
            row = self._execute('SELECT key_value FROM platform_credentials WHERE key_name=%s', (key_name,)).fetchone()
            if row is None:
                return False
            vault.open(key_name, row['key_value'])
            return self._execute('DELETE FROM platform_credentials WHERE key_name=%s',
                                 (key_name,)).rowcount > 0

    def deposit_credit(self, account_id, amount):
        _text(account_id)
        _amount(amount, 'Deposit')
        with self.tx():
            current = self._credit_account(account_id)
            if current and (current['balance'] + amount > MAX_INTEGER
                            or current['total_deposited'] + amount > MAX_INTEGER):
                raise ValueError('Credit account exceeds integer storage limit.')
            self._execute('INSERT INTO agent_credits(account_id,balance,held,total_deposited,total_spent,updated_at) '
                          'VALUES(%s,%s,0,%s,0,%s) ON CONFLICT(account_id) DO UPDATE SET '
                          'balance=agent_credits.balance+EXCLUDED.balance,'
                          'total_deposited=agent_credits.total_deposited+EXCLUDED.total_deposited,'
                          'updated_at=EXCLUDED.updated_at', (account_id, amount, amount, time.time()))
        return self.get_credit(account_id)

    def get_credit(self, account_id):
        _text(account_id)
        with self.tx(readonly=True):
            row = self._execute('SELECT * FROM agent_credits WHERE account_id=%s', (account_id,)).fetchone()
        if not row:
            return {'account_id': account_id, 'balance': 0, 'held': 0, 'available': 0,
                    'total_deposited': 0, 'total_spent': 0}
        return {'account_id': account_id, 'balance': row['balance'], 'held': row['held'],
                'available': max(0, row['balance'] - row['held']),
                'total_deposited': row['total_deposited'], 'total_spent': row['total_spent']}

    def hold_credit(self, account_id, amount, resource_id, tool_name):
        _text(account_id)
        _amount(amount, 'Hold')
        _text(tool_name, limit=1024, empty=True)
        if type(resource_id) is not int or not 0 <= resource_id <= MAX_INTEGER:
            raise ValueError('Invalid resource reference.')
        tx_id, now = 'clr_' + uuid.uuid4().hex, time.time()
        with self.tx():
            row = self._credit_account(account_id)
            available = row['balance'] - row['held'] if row else 0
            if not row or available < amount:
                raise ValueError(f'Insufficient available credits: needed {amount}, available {available}')
            changed = self._execute('UPDATE agent_credits SET held=held+%s,updated_at=%s '
                                    'WHERE account_id=%s AND balance-held>=%s',
                                    (amount, now, account_id, amount)).rowcount
            if changed != 1:
                raise ValueError('Credit account changed before reservation.')
            self._execute('INSERT INTO clearing_ledger(tx_id,account_id,resource_id,tool_name,amount,status,sla_verified,created_at) '
                          "VALUES(%s,%s,%s,%s,%s,'held',0,%s)",
                          (tx_id, account_id, resource_id, tool_name, amount, now))
        return tx_id

    def _credit_account(self, account_id):
        """Reject inconsistent legacy state before any fresh financial write."""
        account = self._execute('SELECT a.balance,a.held,a.total_deposited,a.total_spent,'
                                "COALESCE(SUM(CASE WHEN l.status='held' THEN l.amount ELSE 0 END),0) AS reserved,"
                                "COUNT(l.tx_id) FILTER(WHERE l.amount<1 OR l.amount>1000000000000 "
                                "OR l.status NOT IN ('held','settled','refunded','withdrawn')) AS invalid_entries "
                                'FROM agent_credits a LEFT JOIN clearing_ledger l USING(account_id) '
                                'WHERE a.account_id=%s GROUP BY a.account_id', (account_id,)).fetchone()
        if account is None:
            retained = self._execute('SELECT COUNT(*) FROM clearing_ledger WHERE account_id=%s',
                                     (account_id,)).fetchone()[0]
            if retained:
                raise ValueError('Credit account is missing its retained ledger history.')
            return None
        if (any(type(account[field]) is not int or not 0 <= account[field] <= MAX_INTEGER
                for field in ('balance', 'held', 'total_deposited', 'total_spent', 'reserved'))
                or account['invalid_entries'] != 0
                or account['balance'] < account['held']
                or account['held'] != account['reserved']
                or account['total_deposited'] != account['balance'] + account['total_spent']):
            raise ValueError('Credit account does not match its reservations.')
        return account

    def _held_credit(self, tx_id):
        tx = self._execute('SELECT * FROM clearing_ledger WHERE tx_id=%s', (tx_id,)).fetchone()
        if not tx:
            raise ValueError(f'Clearing transaction {tx_id} not found.')
        if tx['status'] != 'held':
            raise ValueError(f"Transaction {tx_id} already finalized (status: {tx['status']}).")
        if type(tx['amount']) is not int or not 1 <= tx['amount'] <= MAX_AMOUNT:
            raise ValueError('Invalid reserved credit amount.')
        if self._credit_account(tx['account_id']) is None:
            raise ValueError('Credit account does not match its reservations.')
        return tx

    def settle_credit(self, tx_id, receipt=None):
        _text(tx_id, limit=128)
        packed, now = _receipt(receipt), time.time()
        with self.tx():
            tx = self._held_credit(tx_id)
            amount, account_id = tx['amount'], tx['account_id']
            changed = self._execute('UPDATE agent_credits SET held=held-%s,balance=balance-%s,'
                                    'total_spent=total_spent+%s,updated_at=%s WHERE account_id=%s '
                                    'AND held>=%s AND balance>=%s AND total_spent<=%s',
                                    (amount, amount, amount, now, account_id, amount, amount, MAX_INTEGER - amount)).rowcount
            if changed != 1:
                raise ValueError('Credit account does not match its reservation.')
            finalized = self._execute("UPDATE clearing_ledger SET status='settled',sla_verified=1,receipt=%s,settled_at=%s "
                                      "WHERE tx_id=%s AND status='held'", (packed, now, tx_id)).rowcount
            if finalized != 1:
                raise ValueError('Credit reservation changed before finalization.')
        return {'tx_id': tx_id, 'account_id': account_id, 'amount': amount, 'status': 'settled', 'receipt': receipt}

    def refund_credit(self, tx_id, reason=''):
        _text(tx_id, limit=128)
        _text(reason, limit=4096, empty=True)
        packed, now = _receipt({'refund_reason': reason}), time.time()
        with self.tx():
            tx = self._held_credit(tx_id)
            amount, account_id = tx['amount'], tx['account_id']
            changed = self._execute('UPDATE agent_credits SET held=held-%s,updated_at=%s '
                                    'WHERE account_id=%s AND held>=%s', (amount, now, account_id, amount)).rowcount
            if changed != 1:
                raise ValueError('Credit account does not match its reservation.')
            finalized = self._execute("UPDATE clearing_ledger SET status='refunded',receipt=%s,settled_at=%s "
                                      "WHERE tx_id=%s AND status='held'", (packed, now, tx_id)).rowcount
            if finalized != 1:
                raise ValueError('Credit reservation changed before finalization.')
        return {'tx_id': tx_id, 'account_id': account_id, 'amount': amount, 'status': 'refunded', 'reason': reason}

    def get_clearing_tx(self, tx_id):
        _text(tx_id, limit=128)
        with self.tx(readonly=True):
            row = self._execute('SELECT * FROM clearing_ledger WHERE tx_id=%s', (tx_id,)).fetchone()
        return dict(row) if row else None

    def withdraw_credit(self, account_id, amount, to_address):
        _text(account_id)
        _amount(amount, 'Withdrawal')
        if (type(to_address) is not str or len(to_address) != 42 or not to_address.startswith('0x')
                or any(char not in '0123456789abcdefABCDEF' for char in to_address[2:])
                or int(to_address[2:], 16) == 0):
            raise ValueError('Invalid withdrawal destination.')
        now, tx_id = time.time(), 'wdr_' + uuid.uuid4().hex
        receipt = {'to_address': to_address, 'network': 'base', 'withdrawn_at': now}
        with self.tx():
            row = self._credit_account(account_id)
            available = row['balance'] - row['held'] if row else 0
            if not row or available < amount:
                raise ValueError(f'Insufficient available credits to withdraw: needed {amount}, available {available}')
            changed = self._execute('UPDATE agent_credits SET balance=balance-%s,total_spent=total_spent+%s,updated_at=%s '
                                    'WHERE account_id=%s AND balance-held>=%s AND total_spent<=%s',
                                    (amount, amount, now, account_id, amount, MAX_INTEGER - amount)).rowcount
            if changed != 1:
                raise ValueError('Credit account changed before virtual withdrawal.')
            self._execute('INSERT INTO clearing_ledger(tx_id,account_id,resource_id,tool_name,amount,status,sla_verified,receipt,created_at,settled_at) '
                          "VALUES(%s,%s,0,'withdraw',%s,'withdrawn',1,%s,%s,%s)",
                          (tx_id, account_id, amount, _receipt(receipt), now, now))
        return {'tx_id': tx_id, 'account_id': account_id, 'amount': amount, 'to_address': to_address,
                'status': 'withdrawn', 'receipt': receipt}

    def sweep_orphaned_holds(self, ttl_seconds=900):
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or not 0 <= ttl_seconds <= 31536000:
            raise ValueError('Invalid hold retention period.')
        with self.tx(readonly=True):
            rows = self._execute("SELECT tx_id FROM clearing_ledger WHERE status='held' AND created_at<%s "
                                 'ORDER BY created_at,tx_id LIMIT %s', (time.time() - ttl_seconds, MAX_SWEEP)).fetchall()
        refunded = []
        for row in rows:
            try:
                self.refund_credit(row['tx_id'], reason=f'Hold TTL expired ({int(ttl_seconds)}s) - auto refunded')
                refunded.append(row['tx_id'])
            except ValueError:
                # Another worker may already have finalized this reservation.
                continue
        return refunded

    def list_clearing_transactions(self, limit=50, offset=0, status=None, account_id=None):
        self._page(limit, offset)
        if status is not None: _text(status, limit=64, empty=True)
        if account_id is not None: _text(account_id, empty=True)
        status = status or None
        pattern = '%' + account_id + '%' if account_id else None
        params = (status, status, pattern, pattern)
        with self.tx(readonly=True):
            total = self._execute('SELECT COUNT(*) FROM clearing_ledger WHERE '
                                  '(%s::text IS NULL OR status=%s) AND (%s::text IS NULL OR account_id ILIKE %s)', params).fetchone()[0]
            rows = self._execute('SELECT * FROM clearing_ledger WHERE '
                                 '(%s::text IS NULL OR status=%s) AND (%s::text IS NULL OR account_id ILIKE %s) '
                                 'ORDER BY created_at DESC LIMIT %s OFFSET %s', params + (limit, offset)).fetchall()
        return [dict(row) for row in rows], total

    def list_agent_credits(self, limit=50, offset=0, q=None):
        self._page(limit, offset)
        if q is not None: _text(q, empty=True)
        pattern = '%' + q + '%' if q else None
        with self.tx(readonly=True):
            total = self._execute('SELECT COUNT(*) FROM agent_credits WHERE (%s::text IS NULL OR account_id ILIKE %s)',
                                  (pattern, pattern)).fetchone()[0]
            rows = self._execute('SELECT * FROM agent_credits WHERE (%s::text IS NULL OR account_id ILIKE %s) '
                                 'ORDER BY balance DESC,updated_at DESC LIMIT %s OFFSET %s',
                                 (pattern, pattern, limit, offset)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.update(available=max(0, item['balance'] - item['held']), agent_id=item['account_id'],
                        balance_credits=item['balance'], held_credits=item['held'],
                        total_credits=item['balance'] + item['held'])
            item['total_usd'] = round(item['total_credits'] * .001, 3)
            result.append(item)
        return result, total

    def get_clearing_overview(self):
        with self.tx(readonly=True):
            accounts = dict(self._execute('SELECT COUNT(*) AS total_accounts,COALESCE(SUM(balance),0) AS total_balance,'
                                         'COALESCE(SUM(held),0) AS total_held,COALESCE(SUM(total_deposited),0) AS total_deposited,'
                                         'COALESCE(SUM(total_spent),0) AS total_spent FROM agent_credits').fetchone())
            rows = self._execute('SELECT status,COUNT(*) AS count,COALESCE(SUM(amount),0) AS total_amount '
                                 'FROM clearing_ledger GROUP BY status').fetchall()
            # SQLite AVG converts JSON booleans and the numeric prefix of JSON
            # strings, ignores JSON null, and treats other JSON values as zero.
            sla = self._execute("WITH documents AS (SELECT receipt::jsonb AS document FROM clearing_ledger "
                                "WHERE status='settled' AND sla_verified=1), prefixes AS (SELECT document,"
                                "substring(document->>'latency_ms' FROM "
                                "'^[[:space:]]*[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?') AS prefix "
                                "FROM documents), samples AS (SELECT CASE jsonb_typeof(document->'latency_ms') "
                                "WHEN 'number' THEN (document->>'latency_ms')::numeric "
                                "WHEN 'boolean' THEN CASE WHEN document->>'latency_ms'='true' THEN 1 ELSE 0 END "
                                "WHEN 'string' THEN CASE WHEN prefix IS NULL THEN 0 "
                                "WHEN length(prefix)<=64 AND prefix !~ '[eE][+-]?[0-9]{4,}' THEN prefix::numeric ELSE NULL END "
                                "WHEN 'null' THEN NULL ELSE CASE WHEN document->'latency_ms' IS NULL THEN NULL ELSE 0 END END AS sample "
                                'FROM prefixes) SELECT COALESCE(AVG(CASE WHEN abs(sample)<=1e300::numeric THEN sample ELSE NULL END),0) '
                                'AS avg_latency FROM samples').fetchone()
        accounts['total_settled'] = accounts['total_spent']
        accounts['available_balance'] = max(0, accounts['total_balance'] - accounts['total_held'])
        statuses = {row['status']: {'count': row['count'], 'total_amount': row['total_amount']} for row in rows}
        settled, refunded = statuses.get('settled', {}).get('count', 0), statuses.get('refunded', {}).get('count', 0)
        return {'accounts': accounts, 'by_status': statuses, 'ledger_by_status': statuses,
                'sla': {'settled_count': settled, 'refunded_count': refunded,
                        'success_rate': round(settled / (settled + refunded) * 100, 1) if settled + refunded else 100.0,
                        'avg_latency_ms': round(float(sla['avg_latency']), 1)}}
