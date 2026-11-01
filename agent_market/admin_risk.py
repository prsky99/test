"""Shared rules for reviewed (two-person) administrator commands (design 4.3).

A risky change is requested by one administrator and applied by a different superadmin
within REVIEW_TTL. The only exception is an installation with a single active superadmin:
that person may review their own request after a fresh login and an explicit acknowledgment,
and the audit trail records it as a single-approver application.

This module is policy only. Callers read the facts through their own registered queries
(PostgreSQL statement allowlist) and pass them in.
"""
import time

REVIEW_TTL = 15 * 60
FRESH_LOGIN = 10 * 60
# Fixed statements callers register in their own query catalog.
QUERIES = {
    'risk_superadmins': "SELECT COUNT(*) AS n FROM admin_users WHERE role='superadmin' AND active=1",
    'risk_session_age': 'SELECT created_at FROM admin_sessions WHERE token=? AND user_id=?',
}


def clock():
    return time.time()


class ReviewDenied(Exception):
    """The reviewer may not apply this command."""


class ReviewExpired(Exception):
    """The review window closed; the request must be made again."""


def expires_at(created):
    return created + REVIEW_TTL


def is_expired(created, now=None):
    return (clock() if now is None else now) >= expires_at(created)


def project(record, now=None):
    """Return a stored command with its effective status and review deadline."""
    value = dict(record)
    value['expires'] = expires_at(value['created'])
    if value.get('status') == 'pending' and is_expired(value['created'], now):
        value['status'] = 'expired'
    return value


def check_reviewer(*, requested_by, reviewer_id, created, acknowledged, superadmins, session_created, now=None):
    """Raise unless the reviewer may apply the request; return True for a single-approver application."""
    now = clock() if now is None else now
    if is_expired(created, now):
        raise ReviewExpired()
    if requested_by != reviewer_id:
        return False
    if acknowledged is not True or superadmins != 1 or session_created is None or now - session_created > FRESH_LOGIN:
        raise ReviewDenied()
    return True
