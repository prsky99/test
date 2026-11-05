"""Double-entry ledger in won. Coins are won / COIN_VALUE_WON.

Every account is a claim on one segregated pool, except `external:*`, which
stands for money outside it (virtual advertiser deposits and payouts in test
mode). Each journal sums to zero, no claim may go negative, and the backing
invariant is: claims held for others (escrow, holds, wallets, vouchers,
in-flight work, payables) <= the pool's recorded trust balance. If it breaks,
the circuit opens and no new offer is made.
"""
import random
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
BUCKETS = ('external', 'obligation', 'coin', 'pool')


TOTAL_STRIPES = 16


def buckets_of(account):
    if account.startswith(_EXTERNAL):
        return ('external',)
    found = ['pool']
    if account.startswith(OBLIGATION_PREFIXES):
        found.append('obligation')
    if account.startswith(COIN_PREFIXES):
        found.append('coin')
    return tuple(found)


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
        # Refuse before writing: on PostgreSQL an error raised inside a transaction fails the
        # whole request even if a caller catches it, so duplicates and overdrafts are caught here.
        change = {}
        for account, amount in postings:
            change[account] = change.get(account, 0) + amount
        accounts = sorted(change)
        if not getattr(self.database, 'savepoints', False):
            # Without savepoints a failed write would fail the whole outer transaction, so refuse first.
            earlier = self.database.one('SELECT id FROM ad_coin_journals WHERE idem=?', (idem,))
            if earlier:
                raise Duplicate(earlier['id'])
            read = 'SELECT account, amount FROM ad_coin_balances WHERE account IN (' + ','.join('?' * len(accounts)) + ')'
            held = {r['account']: r['amount'] for r in self.database.all(read, tuple(accounts))}
            for account, amount in change.items():
                if amount < 0 and not account.startswith(_EXTERNAL) and held.get(account, 0) + amount < 0:
                    raise LedgerError('Insufficient balance in ' + account.split(':', 1)[0] + '.')
        delta = {}
        for account, amount in postings:
            for bucket in buckets_of(account):
                delta[bucket] = delta.get(bucket, 0) + amount
        # Running totals are striped over TOTAL_STRIPES rows per bucket, so concurrent writers never
        # queue on one hot row; running_totals() adds the stripes up.
        stripe = random.randrange(TOTAL_STRIPES)
        delta = sorted((bucket + '#%d' % stripe, amount) for bucket, amount in delta.items() if amount)
        journal_id = 'j_' + uuid.uuid4().hex
        try:
            # Four statements whatever the number of postings. Balances change atomically in place
            # (in account order, so concurrent writers cannot deadlock on them) and a claim that would
            # go negative undoes this journal only: on PostgreSQL the nested transaction is a savepoint.
            with self.database.transaction() as db:
                db.execute('INSERT INTO ad_coin_journals VALUES (?,?,?,?,?)',
                           (journal_id, now(), kind, idem, dumps(detail or {})))
                db.execute('INSERT INTO ad_coin_postings VALUES ' + ','.join(['(?,?,?)'] * len(postings)),
                           tuple(v for account, amount in postings for v in (journal_id, account, amount)))
                rows = db.execute('INSERT INTO ad_coin_balances VALUES ' + ','.join(['(?,?)'] * len(accounts)) +
                                  ' ON CONFLICT(account) DO UPDATE SET amount=ad_coin_balances.amount+excluded.amount'
                                  ' RETURNING account, amount',
                                  tuple(v for account in accounts for v in (account, change[account]))).fetchall()
                for row in rows:
                    if row['amount'] < 0 and not row['account'].startswith(_EXTERNAL):
                        raise LedgerError('Insufficient balance in ' + row['account'].split(':', 1)[0] + '.')
                if delta:
                    db.execute('INSERT INTO ad_coin_totals VALUES ' + ','.join(['(?,?)'] * len(delta)) +
                               ' ON CONFLICT(bucket) DO UPDATE SET amount=ad_coin_totals.amount+excluded.amount',
                               tuple(v for pair in delta for v in pair))
        except LedgerError:
            raise
        except Exception as exc:
            if type(exc).__name__ in ('UniqueViolation', 'IntegrityError'):
                # the same idempotency key committed by a concurrent writer
                earlier = self.database.one('SELECT id FROM ad_coin_journals WHERE idem=?', (idem,))
                if earlier:
                    raise Duplicate(earlier['id']) from None
            raise
        return journal_id

    def journal(self, journal_id):
        row = self.database.one('SELECT * FROM ad_coin_journals WHERE id=?', (journal_id,))
        if not row:
            return None
        postings = self.database.all('SELECT account, amount FROM ad_coin_postings WHERE journal_id=?', (journal_id,))
        return {'id': row['id'], 'kind': row['kind'], 'created_at': row['created_at'],
                'postings': [(p['account'], p['amount']) for p in postings]}

    def totals(self):
        """Full recount by SQL aggregation: one row back however many accounts exist."""
        row = self.database.one(
            "SELECT COALESCE(SUM(CASE WHEN account NOT LIKE 'external:%' THEN amount ELSE 0 END), 0) AS pool, "
            "COALESCE(SUM(CASE WHEN account LIKE 'escrow:%' OR account LIKE 'hold:%' OR account LIKE 'wallet:%' "
            "OR account LIKE 'voucher:%' OR account LIKE 'inflight:%' OR account LIKE 'payable:%' "
            "OR account LIKE 'reserve:%' THEN amount ELSE 0 END), 0) AS obligations, "
            "COALESCE(SUM(CASE WHEN account LIKE 'wallet:%' THEN amount ELSE 0 END), 0) AS coins, "
            "COALESCE(SUM(CASE WHEN account LIKE 'external:%' THEN amount ELSE 0 END), 0) AS external "
            "FROM ad_coin_balances")
        negative = [r['account'] for r in self.database.all(
            "SELECT account FROM ad_coin_balances WHERE amount < 0 AND account NOT LIKE 'external:%' LIMIT 20")]
        unbalanced = self.database.one(
            'SELECT COUNT(*) AS n FROM (SELECT journal_id FROM ad_coin_postings GROUP BY journal_id HAVING SUM(amount) != 0) AS unbalanced')['n']
        return {'pool_won': row['pool'], 'obligations_won': row['obligations'], 'coin_liability_won': row['coins'],
                'trust_balance_won': -row['external'], 'negative_accounts': negative, 'unbalanced_journals': unbalanced}

    def running_totals(self):
        values = {}
        for r in self.database.all('SELECT bucket, amount FROM ad_coin_totals'):
            name = r['bucket'].split('#', 1)[0]
            values[name] = values.get(name, 0) + r['amount']
        return {bucket: values.get(bucket, 0) for bucket in BUCKETS}

    def rebuild_running_totals(self):
        """Recompute the running totals from the balances (once, for ledgers written before them)."""
        full = self.totals()
        values = {'external': -full['trust_balance_won'], 'obligation': full['obligations_won'],
                  'coin': full['coin_liability_won'], 'pool': full['pool_won']}
        exclusive = getattr(self.database, 'exclusive', None) or self.database.transaction
        with exclusive() as db:
            db.execute('DELETE FROM ad_coin_totals')
            for bucket, amount in values.items():
                db.execute('INSERT INTO ad_coin_totals VALUES (?,?)', (bucket, amount))
        return values

    def fast_invariant(self, trust_statement_won=None):
        """O(1) check after every money move. Per-journal balance and non-negative claims are
        enforced when each journal is written; this checks backing from the running totals."""
        t = self.running_totals()
        trust = -t['external'] if trust_statement_won is None else trust_statement_won
        problems = []
        if t['pool'] + t['external'] != 0:
            problems.append('unbalanced_totals')
        if t['obligation'] > trust:
            problems.append('obligations_exceed_trust')
        return {'ok': not problems, 'problems': problems, 'obligations_won': t['obligation'],
                'trust_statement_won': trust, 'coin_liability_won': t['coin'],
                'coverage': None if not t['obligation'] else round(trust / t['obligation'], 4)}

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
        fast = self.running_totals()
        if (fast['obligation'], fast['coin'], -fast['external']) != (totals['obligations_won'],
                                                                    totals['coin_liability_won'],
                                                                    totals['trust_balance_won']):
            problems.append('running_totals_drift')
        return {**totals, 'trust_statement_won': trust, 'ok': not problems, 'problems': problems,
                'coverage': None if not totals['obligations_won'] else round(trust / totals['obligations_won'], 4)}
