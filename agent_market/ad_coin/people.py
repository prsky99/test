"""Who is acting: an invited signed-in customer, or an agent holding that customer's key.

- A person is a customer account (the workspace sign-in). Only accounts an
  operator invited may use AI AD Coin; revoking the invitation stops their
  agents too.
- An agent acts for a person with an agent key the person created. The key is
  shown once, stored only as a hash, names one agent and can be revoked.
- Legacy visitor-token invitations remain for closed tests without sign-in.
"""
import hashlib
import hmac
import re
import secrets

from .db import now

CUSTOMER = re.compile(r'[A-Za-z0-9_:-]{3,100}\Z')
AGENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
KEY = re.compile(r'ack_[A-Za-z0-9_-]{43}\Z')
MAX_KEYS = 10


class PeopleError(ValueError):
    pass


def user_ref_for_customer(customer_id):
    return 'c_' + hashlib.sha256(('customer:' + customer_id).encode()).hexdigest()[:24]


def _hash(key):
    return hashlib.sha256(('ad-coin-agent-key:' + key).encode()).hexdigest()


class People:
    def __init__(self, database):
        self.db = database

    # ---- invitations (operator) ----
    def invite(self, customer_id, note=''):
        if type(customer_id) is not str or not CUSTOMER.fullmatch(customer_id):
            raise PeopleError('Use the account id the person sees on the AI AD Coin page.')
        with self.db.transaction() as db:
            db.execute('INSERT INTO invites VALUES (?,?,?,NULL) ON CONFLICT(customer_id) DO UPDATE SET '
                       'revoked_at=NULL, note=excluded.note', (customer_id, str(note or '')[:120], now()))
        return {'customer_id': customer_id, 'status': 'invited'}

    def revoke_invite(self, customer_id):
        with self.db.transaction() as db:
            if not db.execute('UPDATE invites SET revoked_at=? WHERE customer_id=? AND revoked_at IS NULL',
                              (now(), customer_id)).rowcount:
                raise PeopleError('No active invitation for that account.')
            db.execute('UPDATE agent_keys SET revoked_at=? WHERE customer_id=? AND revoked_at IS NULL',
                       (now(), customer_id))
        return {'customer_id': customer_id, 'status': 'revoked'}

    def invites(self):
        rows = self.db.all('SELECT * FROM invites ORDER BY created_at')
        return [{'customer_id': r['customer_id'], 'note': r['note'],
                 'status': 'revoked' if r['revoked_at'] else 'invited'} for r in rows]

    def invited(self, customer_id):
        return bool(self.db.one('SELECT 1 FROM invites WHERE customer_id=? AND revoked_at IS NULL', (customer_id,)))

    # ---- agent keys (the person) ----
    def create_key(self, customer_id, agent_ref):
        if type(agent_ref) is not str or not AGENT.fullmatch(agent_ref):
            raise PeopleError('Name the agent with letters, numbers, dots, dashes or underscores.')
        if not self.invited(customer_id):
            raise PeopleError('This account is not invited.')
        active = self.db.one('SELECT COUNT(*) AS n FROM agent_keys WHERE customer_id=? AND revoked_at IS NULL',
                             (customer_id,))['n']
        if active >= MAX_KEYS:
            raise PeopleError('Revoke an agent key before adding another (at most 10).')
        key = 'ack_' + secrets.token_urlsafe(32)[:43]
        with self.db.transaction() as db:
            db.execute('UPDATE agent_keys SET revoked_at=? WHERE customer_id=? AND agent_ref=? AND revoked_at IS NULL',
                       (now(), customer_id, agent_ref))
            db.execute('INSERT INTO agent_keys VALUES (?,?,?,?,NULL,NULL)', (_hash(key), customer_id, agent_ref, now()))
        return {'agent': agent_ref, 'agent_key': key, 'shown_once': True,
                'use': 'Send it as the X-Ad-Coin-Agent-Key header. It acts only for you and only as this agent.'}

    def keys(self, customer_id):
        rows = self.db.all('SELECT agent_ref, created_at, last_used_at FROM agent_keys WHERE customer_id=? '
                           'AND revoked_at IS NULL ORDER BY created_at', (customer_id,))
        return [{'agent': r['agent_ref'], 'created_at': int(r['created_at']),
                 'last_used_at': int(r['last_used_at']) if r['last_used_at'] else None} for r in rows]

    def revoke_keys(self, customer_id, agent_ref):
        with self.db.transaction() as db:
            changed = db.execute('UPDATE agent_keys SET revoked_at=? WHERE customer_id=? AND agent_ref=? '
                                 'AND revoked_at IS NULL', (now(), customer_id, agent_ref)).rowcount
        return changed

    def agent_for_key(self, key):
        """Returns (customer_id, agent_ref) for a live key of an invited account, else None."""
        if type(key) is not str or not KEY.fullmatch(key):
            return None
        digest = _hash(key)
        row = self.db.one('SELECT k.customer_id, k.agent_ref FROM agent_keys k JOIN invites i '
                          'ON i.customer_id=k.customer_id WHERE k.key_hash=? AND k.revoked_at IS NULL '
                          'AND i.revoked_at IS NULL', (digest,))
        if not row:
            return None
        with self.db.transaction() as db:
            db.execute('UPDATE agent_keys SET last_used_at=? WHERE key_hash=?', (now(), digest))
        return row['customer_id'], row['agent_ref']


def customer_session(identity, request, write):
    """customer_id of the signed-in customer making this same-origin request, or None.
    Writes also need the session's CSRF proof."""
    if identity is None:
        return None
    token = request.cookies.get('__Host-ac_customer_session')
    if not token:
        return None
    from ..workflow_publication_service import same_origin
    from ..workspace_access import WorkspaceDenied
    if not same_origin(request):
        return None
    try:
        actor = identity.actor(token)
    except (WorkspaceDenied, ValueError, TypeError):
        return None
    if write:
        proof = request.headers.get('x-customer-csrf', '')
        if not re.fullmatch(r'[0-9a-f]{64}', proof) or not hmac.compare_digest(proof, identity.csrf(token)):
            return None
    return actor.customer_id
