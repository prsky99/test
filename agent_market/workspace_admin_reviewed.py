"""Reviewed (two-person) administrator commands outside a single customer (design 4.3).

Requests live in the explicitly migrated workspace-admin store and are signed with its key.
Without that migration the queue reports itself unavailable and risky actions stay blocked;
nothing here creates tables on a request path. Approval follows admin_risk: a different
superadmin within 15 minutes, or the sole active superadmin after a fresh login.
"""
import json
import re
import secrets
import time

from . import admin_risk
from .workspace_admin_events import audit, canonical, execute, register, rows, signature, transaction

KINDS = {'execution_release': '실행 킬스위치 해제', 'retention_policy': '보존 기간 변경', 'admin_account_change': '관리자 계정 변경',
         'public_service_change': '공개 서비스·보안 변경', 'finance_change': '금융 장부 변경'}

register({
    'reviewed_insert': "INSERT INTO admin_reviewed_commands VALUES(?,?,?,1,'pending',?,NULL,?,?,?,?,NULL)",
    'reviewed_list': 'SELECT * FROM admin_reviewed_commands ORDER BY created DESC,id DESC LIMIT ?',
    'reviewed_list_kind': 'SELECT * FROM admin_reviewed_commands WHERE kind=? ORDER BY created DESC,id DESC LIMIT ?',
    'reviewed_get': 'SELECT * FROM admin_reviewed_commands WHERE id=?',
    'reviewed_open': "SELECT id FROM admin_reviewed_commands WHERE kind=? AND target=? AND status='pending' AND created>?",
    'reviewed_approve': '''UPDATE admin_reviewed_commands SET status='approved',revision=revision+1,approved_by=?,updated=?
        WHERE id=? AND revision=? AND status='pending' ''',
    'reviewed_finish': '''UPDATE admin_reviewed_commands SET status=?,revision=revision+1,result=?,updated=?
        WHERE id=? AND status='approved' ''',
    'reviewed_cancel': '''UPDATE admin_reviewed_commands SET status='cancelled',revision=revision+1,updated=?
        WHERE id=? AND revision=? AND status='pending' ''',
    'reviewed_superadmins': admin_risk.QUERIES['risk_superadmins'],
    'reviewed_session_age': admin_risk.QUERIES['risk_session_age'],
})


class ReviewUnavailable(Exception):
    """The workspace-admin migration that holds reviewed commands has not run."""


class ReviewConflict(Exception):
    """The command changed, expired or was already handled."""


class ReviewDenied(Exception):
    """This administrator may not perform the review step."""


class ReviewedCommands:
    def __init__(self, store, appliers):
        # appliers: kind -> callable(payload, user_id) returning a JSON-safe result; it raises ValueError on drift.
        self.store, self.appliers = store, appliers

    def ready(self):
        if getattr(self.store, '_workspace_admin_event_key', None) is None:
            return False
        with transaction(self.store, True) as db:
            native = getattr(db, '_store', None)
            if native is not None:
                return native._execute("SELECT to_regclass('admin_reviewed_commands')").fetchone()[0] is not None
            return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_reviewed_commands'").fetchone() is not None

    def _key(self):
        if not self.ready():
            raise ReviewUnavailable()
        return self.store._workspace_admin_event_key

    def _verified(self, key, record):
        payload = json.loads(record['payload'])
        envelope = {'id': record['id'], 'kind': record['kind'], 'target': record['target'], 'payload': payload,
                    'requested_by': record['requested_by'], 'created': record['created']}
        if not secrets.compare_digest(signature(key, envelope), record['signature']):
            raise ReviewConflict()
        return payload

    def request(self, user_id, kind, target, payload, reason, identity=None):
        if kind not in self.appliers or kind not in KINDS:
            raise ValueError('unsupported reviewed command')
        key = self._key()
        if identity is not None and (type(identity) is not str or not re.fullmatch(r'arc_[a-f0-9]{32}', identity)):
            raise ValueError('invalid reviewed command identity')
        now = time.time()
        with transaction(self.store) as db:
            if identity is not None:
                existing = rows(db, 'reviewed_get', (identity,))
                if existing:
                    record = existing[0]
                    verified = self._verified(key, record)
                    if record['requested_by'] != user_id or record['kind'] != kind or record['target'] != target or canonical(verified) != canonical(payload):
                        raise ReviewConflict()
                    return self._view(key, record)
            # One open request per action and target keeps reviewers from approving a stale duplicate.
            if rows(db, 'reviewed_open', (kind, target, now - admin_risk.REVIEW_TTL)):
                raise ReviewConflict()
            identity = identity or 'arc_' + secrets.token_hex(16)
            envelope = {'id': identity, 'kind': kind, 'target': target, 'payload': payload,
                        'requested_by': user_id, 'created': now}
            execute(db, 'reviewed_insert', (identity, kind, target, user_id, now, now, canonical(payload), signature(key, envelope)))
            audit(db, user_id, 'reviewed.request.' + kind, identity, reason)
        return self.get(identity)

    def list(self, limit=50):
        key = self._key()
        with transaction(self.store, True) as db:
            found = rows(db, 'reviewed_list', (limit,))
        return [self._view(key, record) for record in found]

    def list_for(self, kind, limit=50):
        if kind not in KINDS or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('invalid reviewed list scope')
        key = self._key()
        with transaction(self.store, True) as db:
            found = rows(db, 'reviewed_list_kind', (kind, limit))
        return [self._view(key, record) for record in found]

    def _view(self, key, record):
        try:
            payload = self._verified(key, record)
        except (ReviewConflict, ValueError):
            payload, record = None, {**record, 'status': 'integrity_review_required'}
        value = admin_risk.project({k: v for k, v in record.items() if k not in ('payload', 'signature')})
        if payload is not None and record['kind'] == 'admin_account_change':
            from .workspace_admin_accounts import project
            payload = project(payload)
        value['payload'], value['label'] = payload, KINDS.get(record['kind'], record['kind'])
        return value

    def get(self, identity):
        key = self._key()
        with transaction(self.store, True) as db:
            found = rows(db, 'reviewed_get', (identity,))
            if not found:
                raise ReviewConflict()
            record = found[0]
            self._verified(key, record)
        return self._view(key, record)

    def approve(self, user_id, session_ref, identity, revision, reason, acknowledged):
        key = self._key()
        with transaction(self.store) as db:
            found = rows(db, 'reviewed_get', (identity,))
            if not found:
                raise ReviewConflict()
            record = found[0]
            payload = self._verified(key, record)
            if record['status'] != 'pending' or record['revision'] != revision:
                raise ReviewConflict()
            single = record['requested_by'] == user_id
            session = rows(db, 'reviewed_session_age', (session_ref, user_id)) if single else []
            try:
                admin_risk.check_reviewer(requested_by=record['requested_by'], reviewer_id=user_id, created=record['created'],
                    acknowledged=acknowledged, superadmins=rows(db, 'reviewed_superadmins')[0]['n'] if single else None,
                    session_created=session[0]['created_at'] if session else None)
            except admin_risk.ReviewExpired:
                raise ReviewConflict() from None
            except admin_risk.ReviewDenied:
                raise ReviewDenied() from None
            if execute(db, 'reviewed_approve', (user_id, time.time(), identity, revision)).rowcount != 1:
                raise ReviewConflict()
            audit(db, user_id, 'reviewed.approve.single_approver' if single else 'reviewed.approve', identity, reason)
        # The applier owns its own transaction and revision check; record exactly what happened.
        try:
            result, status = self.appliers[record['kind']](payload, user_id), 'applied'
        except ValueError as error:
            result, status = {'error': str(error)[:300]}, 'failed'
        except Exception:
            # The external effect or commit may already have happened. Never replay it.
            result, status = {'error': '적용 결과를 확인할 수 없습니다. 현재 기록을 점검하고 자동 재시도하지 마세요.'}, 'unknown'
        with transaction(self.store) as db:
            execute(db, 'reviewed_finish', (status, canonical(result), time.time(), identity))
            audit(db, user_id, 'reviewed.' + status, identity, reason)
        value = self.get(identity)
        value['same_person_review'] = single
        return value

    def cancel(self, user_id, role, identity, revision, reason):
        current = self.get(identity)
        if current['requested_by'] != user_id and role != 'superadmin':
            raise ReviewDenied()
        with transaction(self.store) as db:
            if execute(db, 'reviewed_cancel', (time.time(), identity, revision)).rowcount != 1:
                raise ReviewConflict()
            audit(db, user_id, 'reviewed.cancel', identity, reason)
        return self.get(identity)
