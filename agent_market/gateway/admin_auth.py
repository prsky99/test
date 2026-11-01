"""관리자 계정 인증, 세션 관리, 사용자 관리 및 감사 로그(Audit Log)."""

import hashlib
import os
import hmac
import json
import logging
import secrets
import sqlite3
import time
from typing import Any
from functools import lru_cache

from .admin_policy import ROLES

log = logging.getLogger("agent_market.gateway.admin_auth")

ADMIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',  -- 'superadmin' | 'admin' | 'operator' | 'viewer'
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_login_at REAL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS admin_sessions_user ON admin_sessions(user_id);
CREATE INDEX IF NOT EXISTS admin_sessions_exp ON admin_sessions(expires_at);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    action_name TEXT NOT NULL,
    target TEXT,
    ip TEXT,
    status TEXT NOT NULL DEFAULT 'SUCCESS',  -- 'SUCCESS' | 'FAILED'
    details TEXT
);
CREATE INDEX IF NOT EXISTS admin_audit_logs_at ON admin_audit_logs(at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_logs_user ON admin_audit_logs(username, at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_logs_action ON admin_audit_logs(action, at DESC);
"""


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 해시를 생성한다."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000).hex()
    return "pbkdf2_sha256$600000$" + hashed, salt


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    """비밀번호 일치 여부를 안전하게 확인한다."""
    if not isinstance(password, str) or len(password) > 1024:
        return False
    password_hash = password_hash.removeprefix("bootstrap$")
    if password_hash.startswith("pbkdf2_sha256$600000$"):
        computed, _ = hash_password(password, salt)
    else:
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(computed, password_hash)


def validate_password(password):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ValueError("비밀번호는 최소 15자 이상, 최대 128자여야 합니다.")


def validate_role(role):
    if role not in ROLES:
        raise ValueError("Invalid administrator role")


@lru_cache(maxsize=128)
def password_change_required(password_hash: str, salt: str) -> bool:
    """Recognize bootstrap credentials, including historical unmarked defaults."""
    return password_hash.startswith('bootstrap$') or verify_password('sadmin', salt, password_hash)


def init_admin_auth_db(db: sqlite3.Connection) -> None:
    """관리자 테이블을 생성하고 기본 계정(sadmin/sadmin)을 생성한다."""
    db.executescript(ADMIN_SCHEMA)
    cur = db.execute("SELECT id FROM admin_users WHERE username = ?", ("sadmin",))
    if not cur.fetchone():
        now = time.time()
        bootstrap_password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
        if os.environ.get("DEPLOYMENT_MODE") == "production" and (not bootstrap_password or len(bootstrap_password) < 16):
            raise ValueError("Production initialization requires ADMIN_BOOTSTRAP_PASSWORD with at least 16 characters")
        pwd_hash, salt = hash_password(bootstrap_password or "sadmin")
        db.execute(
            """INSERT INTO admin_users (username, password_hash, salt, role, name, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sadmin", "bootstrap$" + pwd_hash, salt, "superadmin", "최고 관리자 (sadmin)", 1, now, now),
        )
        log.info("Default superadmin user 'sadmin' created successfully.")


def authenticate_user(db: sqlite3.Connection, username: str, password: str) -> dict | None:
    """사용자 이름과 비밀번호를 검증하여 활성화된 사용자 정보를 반환한다."""
    cur = db.execute(
        "SELECT id, username, password_hash, salt, role, name, active FROM admin_users WHERE username = ?",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        # Match the expensive path for unknown users, limiting account enumeration.
        hash_password(password, "authentication-dummy-salt")
        return None
    user = dict(row)
    if not verify_password(password, user["salt"], user["password_hash"]):
        return None
    if not user.get("active"):
        return None
    user["password_change_required"] = password_change_required(user["password_hash"], user["salt"])
    if not user["password_hash"].removeprefix("bootstrap$").startswith("pbkdf2_sha256$600000$"):
        upgraded, salt = hash_password(password)
        if user["password_change_required"]:
            upgraded = "bootstrap$" + upgraded
        db.execute("UPDATE admin_users SET password_hash=?,salt=? WHERE id=?", (upgraded,salt,user["id"]))
    return user


def session_reference(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: sqlite3.Connection,
    user_id: int,
    username: str,
    role: str,
    name: str,
    ip: str | None = None,
    user_agent: str | None = None,
    duration_days: float = 8 / 24,
) -> str:
    """새로운 관리자 세션 토큰을 생성하고 저장한다."""
    token = secrets.token_hex(32)
    now = time.time()
    expires_at = now + (duration_days * 86400)
    db.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))
    db.execute("""DELETE FROM admin_sessions WHERE user_id=? AND token NOT IN
                  (SELECT token FROM admin_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 9)""",
               (user_id, user_id))
    db.execute(
        """INSERT INTO admin_sessions (token, user_id, username, role, name, created_at, expires_at, ip, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_reference(token), user_id, username, role, name, now, expires_at, ip, (user_agent or "")[:300]),
    )
    db.execute("UPDATE admin_users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
    return token


def get_session_user(db: sqlite3.Connection, token: str, *, upgrade_legacy: bool = True, allow_password_change: bool = False) -> dict | None:
    """세션 토큰으로 활성화된 사용자 정보를 조회한다 (만료 확인)."""
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        return None
    reference = session_reference(token)
    now = time.time()
    cur = db.execute(
        """SELECT s.token, s.user_id, u.username, u.role, u.name, s.expires_at, u.active, u.password_hash, u.salt
           FROM admin_sessions s
           JOIN admin_users u ON u.id = s.user_id
           WHERE s.token IN (?, ?) AND s.expires_at > ? AND u.active = 1""",
        (reference, token, now),
    )
    row = cur.fetchone()
    if row is None:
        return None
    legacy = row['token'] == token
    if legacy and upgrade_legacy:
        # Upgrade legacy storage only when this version authenticates its owner.
        db.execute("UPDATE admin_sessions SET token=? WHERE token=?", (reference, token))
    result = dict(row)
    result.pop("token", None)
    result["password_change_required"] = password_change_required(result.pop("password_hash"), result.pop("salt"))
    if result["password_change_required"] and not allow_password_change:
        return None
    if legacy and not upgrade_legacy:
        result['_legacy_session'] = True
    return result


def delete_session(db: sqlite3.Connection, token: str) -> bool:
    """세션 토큰을 무효화(로그아웃)한다."""
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        return False
    cur = db.execute("DELETE FROM admin_sessions WHERE token IN (?, ?)", (session_reference(token), token))
    return cur.rowcount > 0


def change_user_password(db: sqlite3.Connection, user_id: int, old_password: str, new_password: str) -> bool:
    """기존 비밀번호 확인 후 새 비밀번호로 변경한다."""
    cur = db.execute("SELECT password_hash, salt FROM admin_users WHERE id = ? AND active = 1", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    if not verify_password(old_password, row["salt"], row["password_hash"]):
        return False
    validate_password(new_password)
    if verify_password(new_password, row["salt"], row["password_hash"]):
        raise ValueError("새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    new_hash, new_salt = hash_password(new_password)
    now = time.time()
    db.execute(
        "UPDATE admin_users SET password_hash = ?, salt = ?, updated_at = ? WHERE id = ?",
        (new_hash, new_salt, now, user_id),
    )
    db.execute("DELETE FROM admin_sessions WHERE user_id=?", (user_id,))
    return True


def record_audit(
    db: sqlite3.Connection,
    username: str,
    role: str,
    action: str,
    action_name: str,
    target: str | None = None,
    ip: str | None = None,
    status: str = "SUCCESS",
    details: Any = None,
) -> None:
    """관리자 활동 감사 로그를 기록한다."""
    now = time.time()
    det_str = ""
    if details is not None:
        det_str = json.dumps(details, ensure_ascii=False) if not isinstance(details, str) else details
    try:
        db.execute(
            """INSERT INTO admin_audit_logs (at, username, role, action, action_name, target, ip, status, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, username, role, action, action_name, target, ip, status, det_str),
        )
    except Exception as e:
        log.warning("Failed to record admin audit log: %s", e)


def list_audit_logs(
    db: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    username: str | None = None,
    status: str | None = None,
) -> tuple[list[dict], int]:
    """감사 로그 목록과 전체 건수를 반환한다."""
    conds = []
    params: list[Any] = []
    if action:
        conds.append("action = ?")
        params.append(action)
    if username:
        conds.append("username = ?")
        params.append(username)
    if status:
        conds.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    cur_count = db.execute(f"SELECT COUNT(*) FROM admin_audit_logs {where}", params)
    total = cur_count.fetchone()[0]

    cur_rows = db.execute(
        f"SELECT * FROM admin_audit_logs {where} ORDER BY at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    rows = [dict(r) for r in cur_rows.fetchall()]
    return rows, total


def list_admin_users(db: sqlite3.Connection) -> list[dict]:
    """관리자 목록을 조회한다 (비밀번호 제외)."""
    cur = db.execute(
        "SELECT id, username, role, name, active, created_at, updated_at, last_login_at FROM admin_users ORDER BY id ASC"
    )
    return [dict(r) for r in cur.fetchall()]


def create_admin_user(
    db: sqlite3.Connection, username: str, password: str, name: str, role: str = "admin"
) -> dict:
    """새 관리자 계정을 생성한다."""
    validate_password(password)
    validate_role(role)
    now = time.time()
    pwd_hash, salt = hash_password(password)
    cur = db.execute(
        """INSERT INTO admin_users (username, password_hash, salt, role, name, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (username.strip(), pwd_hash, salt, role, name.strip(), now, now),
    )
    return {"id": cur.lastrowid, "username": username.strip(), "role": role, "name": name.strip(), "active": 1}


def update_admin_user(
    db: sqlite3.Connection,
    user_id: int,
    name: str | None = None,
    role: str | None = None,
    active: int | None = None,
    new_password: str | None = None,
) -> bool:
    """관리자 정보를 수정하거나 비밀번호를 초기화한다."""
    users = list_admin_users(db)
    target = next((user for user in users if user['id'] == user_id), None)
    removing = active == 0 or (role is not None and role != 'superadmin')
    if target and target['active'] and target['role'] == 'superadmin' and removing:
        if not any(user['id'] != user_id and user['active'] and user['role'] == 'superadmin' for user in users):
            raise ValueError("마지막 활성 최고관리자는 비활성화하거나 권한을 낮출 수 없습니다.")
    fields = []
    params: list[Any] = []
    now = time.time()
    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if role is not None:
        validate_role(role)
        fields.append("role = ?")
        params.append(role)
    if active is not None:
        fields.append("active = ?")
        params.append(int(active))
    if new_password:
        validate_password(new_password)
        pwd_hash, salt = hash_password(new_password)
        fields.append("password_hash = ?")
        params.append(pwd_hash)
        fields.append("salt = ?")
        params.append(salt)
    if not fields:
        return False
    fields.append("updated_at = ?")
    params.append(now)
    params.append(user_id)
    cur = db.execute(f"UPDATE admin_users SET {', '.join(fields)} WHERE id = ?", params)
    if cur.rowcount and (new_password or role is not None or active is not None):
        db.execute("DELETE FROM admin_sessions WHERE user_id=?", (user_id,))
    return cur.rowcount > 0


def delete_admin_user(db: sqlite3.Connection, user_id: int) -> bool:
    """관리자 계정을 비활성화/삭제한다 (sadmin 계정 보호)."""
    cur = db.execute("SELECT username FROM admin_users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row or row["username"] == "sadmin":
        return False
    users = list_admin_users(db)
    target = next((user for user in users if user['id'] == user_id), None)
    if target and target['active'] and target['role'] == 'superadmin':
        if not any(user['id'] != user_id and user['active'] and user['role'] == 'superadmin' for user in users):
            return False
    db.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
    cur2 = db.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
    return cur2.rowcount > 0
