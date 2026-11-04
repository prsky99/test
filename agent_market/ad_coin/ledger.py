"""Double-entry ledger in won. Coins are won / COIN_VALUE_WON.

Every account is a claim on one segregated pool, except `external:*`, which
stands for money outside it (virtual advertiser deposits and payouts in test
mode). Each journal sums to zero, no claim may go negative, and the backing
invariant is: claims held for others (escrow, holds, wallets, vouchers,
in-flight work, payables) <= the pool's recorded trust balance. If it breaks,
the circuit opens and no new offer is made.
"""
import uuid

from . import db as _db
from .db import dumps


def now():
    return _db.now()

EXTERNAL_FUNDING = 'external:funding'
EXTERNAL_PAYOUT = 'external:payout'
PLATFORM_DIRECT = 'platform:direct'
PLATFORM_REVENUE = 'platform:revenue'
PROMOTION_RESERVE = 'reserve:promotion'
OBLIGATION_PREFIXES = ('escrow:', 'hold:', 'wallet:', 'voucher:', 'inflight:', 'payable:', 'reserve:')
COIN_PREFIXES = ('wallet:',)
_EXTERNAL = ('external:',)


class LedgerError(ValueError):
    pass


class Duplicate(Exception):
    def __init__(self, journal_id):
        super().__init__(journal_id)
        self.journal_id = journal_id


def escrow(campaign_id):
    return 'escrow:' + campaign_id


def hold(reservation_id):
    return 'hold:' + reservation_id


def user_wallet(user_ref):
    return 'wallet:user:' + user_ref


def agent_wallet(user_ref, agent_ref):
    return 'wallet:agent:' + user_ref + ':' + agent_ref


def voucher(voucher_id):
    return 'voucher:' + voucher_id


def inflight(execution_id):
    return 'inflight:' + execution_id


def provider_payable(provider):
    return 'payable:provider:' + provider


def operator_payable(operator_ref):
    return 'payable:operator:' + operator_ref


class Ledger:
    def __init__(self, database):
        self.database = database

    def balance(self, account):
        row = self.database.one('SELECT amount FROM ad_coin_balances WHERE account=?', (account,))
        return row['amount'] if row else 0

    def has(self, idem):
        return bool(self.database.one('SELECT id FROM ad_coin_journals WHERE idem=?', (idem,)))

    def post(self, kind, idem, postings, detail=None):
        """Write one balanced journal. `postings` is [(account, amount_won)].

        A repeated `idem` raises Duplicate with the earlier journal id instead of
        posting twice, so callers can make every money move idempotent."""
        if not postings or any(type(amount) is not int for _, amount in postings):
            raise LedgerError('Postings need integer won amounts.')
        if sum(amount for _, amount in postings) != 0:
            raise LedgerError('A journal must balance to zero.')
        if any(amount == 0 for _, amount in postings):
            raise LedgerError('Zero postings are not allowed.')
        with self.database.transaction() as db:
            earlier = db.execute('SELECT id FROM ad_coin_journals WHERE idem=?', (idem,)).fetchone()
            if earlier:
                raise Duplicate(earlier['id'])
            journal_id = 'j_' + uuid.uuid4().hex
            db.execute('INSERT INTO ad_coin_journals VALUES (?,?,?,?,?)',
                       (journal_id, now(), kind, idem, dumps(detail or {})))
            for account, amount in postings:
                db.execute('INSERT INTO ad_coin_postings VALUES (?,?,?)', (journal_id, account, amount))
                row = db.execute('SELECT amount FROM ad_coin_balances WHERE account=?', (account,)).fetchone()
                value = (row['amount'] if row else 0) + amount
                if value < 0 and not account.startswith(_EXTERNAL):
                    raise LedgerError('Insufficient balance in ' + account.split(':', 1)[0] + '.')
                db.execute('INSERT INTO ad_coin_balances VALUES (?,?) ON CONFLICT(account) DO UPDATE SET amount=excluded.amount',
                           (account, value))
            return journal_id

    def journal(self, journal_id):
        row = self.database.one('SELECT * FROM ad_coin_journals WHERE id=?', (journal_id,))
        if not row:
            return None
        postings = self.database.all('SELECT account, amount FROM ad_coin_postings WHERE journal_id=?', (journal_id,))
        return {'id': row['id'], 'kind': row['kind'], 'created_at': row['created_at'],
                'postings': [(p['account'], p['amount']) for p in postings]}

    def totals(self):
        rows = self.database.all('SELECT account, amount FROM ad_coin_balances')
        pool = sum(r['amount'] for r in rows if not r['account'].startswith(_EXTERNAL))
        obligations = sum(r['amount'] for r in rows if r['account'].startswith(OBLIGATION_PREFIXES))
        coins = sum(r['amount'] for r in rows if r['account'].startswith(COIN_PREFIXES))
        trust = -sum(r['amount'] for r in rows if r['account'].startswith(_EXTERNAL))
        negative = [r['account'] for r in rows if r['amount'] < 0 and not r['account'].startswith(_EXTERNAL)]
        unbalanced = self.database.one(
            'SELECT COUNT(*) AS n FROM (SELECT journal_id FROM ad_coin_postings GROUP BY journal_id HAVING SUM(amount) != 0) AS unbalanced')['n']
        return {'pool_won': pool, 'obligations_won': obligations, 'coin_liability_won': coins,
                'trust_balance_won': trust, 'negative_accounts': negative, 'unbalanced_journals': unbalanced}

    def invariant(self, trust_statement_won=None):
        """`trust_statement_won` is the segregated account's statement balance.
        In test mode it defaults to the ledger's own record of virtual deposits
        less payouts; at the grand opening it must come from the bank statement."""
        totals = self.totals()
        trust = totals['trust_balance_won'] if trust_statement_won is None else trust_statement_won
        problems = []
        if totals['unbalanced_journals']:
            problems.append('unbalanced_journal')
        if totals['negative_accounts']:
            problems.append('negative_claim')
        if totals['obligations_won'] > trust:
            problems.append('obligations_exceed_trust')
        return {**totals, 'trust_statement_won': trust, 'ok': not problems, 'problems': problems,
                'coverage': None if not totals['obligations_won'] else round(trust / totals['obligations_won'], 4)}
