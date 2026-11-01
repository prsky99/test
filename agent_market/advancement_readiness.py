"""Audited declarations and trusted current-evidence readiness, never activation."""
from dataclasses import dataclass
import math
import re
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceInvalid, _canonical, _rows

PROFILE = 'workspace-commercial-readiness-v1'
NOTICE = 'workspace-readiness-declaration-v1'
CATEGORIES = ('identity', 'provider_ownership', 'quality', 'storage_dr', 'support',
              'ledger', 'contract', 'payment', 'operations')
SCHEMA = ('''CREATE TABLE IF NOT EXISTS workspace_readiness_declarations (
    id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,category TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',)


def _finite_number(value):
    if type(value) not in (int, float): return False
    try: return math.isfinite(value)
    except (OverflowError, ValueError): return False


@dataclass(frozen=True)
class CurrentEvidence:
    """Only a trusted server adapter may create this after checking its source.

    This is not accepted from HTTP JSON. References are not opened or fetched by
    the checklist. An isolated test is never operating evidence.
    """
    workspace_id: str
    category: str
    source: str
    content_hash: str
    observed_at: float
    expires: float
    environment: str
    audit_hash: str | None = None


class AdvancementReadiness(SignedWorkspaceModule):
    def __init__(self, access, *, evidence_sources=None):
        super().__init__(access, PROFILE, SCHEMA)
        if evidence_sources is not None and (type(evidence_sources) is not dict
                or set(evidence_sources)-set(CATEGORIES) or any(not callable(f) for f in evidence_sources.values())):
            raise WorkspaceInvalid()
        self.evidence_sources = dict(evidence_sources or {})

    def record(self, ws, body, actor):
        exact(body, ('category', 'reference', 'sha256', 'expires', 'authorized', 'notice'))
        if (body['category'] not in CATEGORIES or type(body['reference']) is not str
                or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', body['reference'])
                or type(body['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', body['sha256'])
                or type(body['expires']) not in (int, float) or not math.isfinite(body['expires'])
                or not clock() < body['expires'] <= clock()+30*86400
                or body['authorized'] is not True or body['notice'] != NOTICE):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            if db.execute('SELECT COUNT(*) FROM workspace_readiness_declarations WHERE workspace_id=?', (ws,)).fetchone()[0] >= 200:
                raise WorkspaceConflict()
            value = {'profile': PROFILE, 'id': 'wre_'+secrets.token_hex(16), 'workspace_id': ws,
                'category': body['category'], 'reference': body['reference'], 'sha256': body['sha256'],
                'created': clock(), 'expires': body['expires'], 'actor_user_id': actor.user_id,
                'verification': 'declared_unverified'}
            db.execute('INSERT INTO workspace_readiness_declarations VALUES(?,?,?,?,?)',
                (value['id'], ws, value['category'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'readiness.declare', value['id'], None)
            return {'id': value['id'], 'category': value['category'], 'verification': 'declared_unverified',
                    'commercial_enabled': False}

    @staticmethod
    def _evidence(value, ws, category, now):
        return (type(value) is CurrentEvidence and value.workspace_id == ws and value.category == category
            and type(value.source) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value.source) is not None
            and type(value.content_hash) is str and re.fullmatch(r'[0-9a-f]{64}', value.content_hash) is not None
            and _finite_number(value.observed_at)
            and 0 < value.observed_at <= now+5 and _finite_number(value.expires)
            and value.observed_at <= value.expires and now < value.expires
            and value.environment == 'operating' and type(value.audit_hash) is str
            and re.fullmatch(r'[0-9a-f]{64}', value.audit_hash) is not None)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            member, user = self.scope(ws, actor)
            scope = (member['revision'], member['member_revision'], member['member_role'], user['role'])
            rows = _rows(db, 'SELECT * FROM workspace_readiness_declarations WHERE workspace_id=? ORDER BY rowid DESC LIMIT 201', (ws,))
            if len(rows) > 200: raise WorkspaceConflict()
            declarations = {}
            for row in rows:
                value = self.opened(row)
                if (value['workspace_id'] != ws or value['id'] != row['id'] or value['category'] != row['category']
                        or value['verification'] != 'declared_unverified'): raise WorkspaceConflict()
                declarations.setdefault(value['category'], value)
        # Source adapters are trusted readonly application code, never request
        # fields, and run outside a DB lock. Missing adapters fail closed.
        samples = {}
        for category in CATEGORIES:
            evidence = None
            if category in self.evidence_sources:
                try:
                    evidence = self.evidence_sources[category](ws, actor)
                except Exception:
                    # No raw source error/credential/body is a readiness result.
                    evidence = None
            samples[category] = evidence
        with self.access._tx(actor) as (db, _):
            member, user = self.scope(ws, actor)
            if scope != (member['revision'], member['member_revision'], member['member_role'], user['role']):
                raise WorkspaceConflict()
        # Validate every sample against the response-time clock, after all
        # adapters and the current membership recheck have returned.
        now, checks = clock(), []
        for category in CATEGORIES:
            evidence = samples[category]
            verified = self._evidence(evidence, ws, category, now)
            declaration = declarations.get(category)
            checks.append({'category': category, 'state': 'current_evidence' if verified else
                'declared_unverified' if declaration and declaration['expires'] > now else 'missing_current_evidence',
                'verified': verified, 'source_configured': category in self.evidence_sources,
                'expires': evidence.expires if verified else None})
        ready = all(check['verified'] is True for check in checks)
        return {'profile': PROFILE, 'notice': NOTICE, 'checks': checks,
            'status': 'evidence_complete_review_required' if ready else 'not_ready',
            'required_current_evidence_complete': ready, 'commercial_enabled': False,
            'payment_enabled': False, 'provider_payout_enabled': False,
            'declarations_are_verified': False, 'automatic_gate_promotion': False,
            'can_declare': member['member_role'] == 'owner' and user['role'] != 'operator'}
