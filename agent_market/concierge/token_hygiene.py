"""Credential-safe persistence and an explicit, idempotent legacy token scrubber."""

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

VISITOR_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])vt_[A-Za-z0-9_-]{16,128}(?![A-Za-z0-9_-])")
HASH = re.compile(r"^[0-9a-f]{64}$")
MARKER = "[REDACTED_VISITOR_TOKEN]"
FIELDS = {
    "agent_messages": ("text", "data"),
    "customer_inquiries": ("visitor_token", "message", "admin_response"),
    "agent_test_reports": ("input_wire", "output_wire", "content_md"),
}


def redact_visitor_tokens(value: str) -> str:
    return VISITOR_TOKEN.sub(MARKER, value)


def token_reference(token):
    if not token:
        return None
    return token if HASH.fullmatch(token) else hashlib.sha256(token.encode()).hexdigest()


def inventory_and_scrub(path, *, apply=False, backup_dir=None):
    """Default to read-only counts. Applying masks token text and preserves identity hashes.

    The rollback file contains credentials and must remain private and untracked.
    No credential value or row content is included in the returned report.
    """
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True, timeout=10)
    changes, counts = [], {}
    backup_path = None
    try:
        if apply:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, fields in FIELDS.items():
            if table not in tables:
                continue
            columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            for column in fields:
                if column not in columns:
                    continue
                count = 0
                for rowid, value in db.execute(f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" LIKE ?', ("%vt_%",)):
                    if not isinstance(value, str):
                        continue
                    new_value = token_reference(value) if column == "visitor_token" else redact_visitor_tokens(value)
                    if value != new_value:
                        changes.append((table, column, rowid, value, new_value))
                        count += 1
                counts[f"{table}.{column}"] = count
        if apply and changes:
            if backup_dir is None:
                raise ValueError("A private backup directory is required before applying changes")
            backup_dir = Path(backup_dir).resolve()
            backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if backup_dir.stat().st_mode & 0o077:
                raise ValueError("Backup directory must only be accessible by its owner")
            backup_path = backup_dir / f"token-scrub-{path.name}-{time.time_ns()}.json"
            fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as backup:
                json.dump({"database": str(path), "changes": [
                    {"table": t, "column": c, "rowid": rid, "original": old,
                     "replacement_sha256": hashlib.sha256(new.encode()).hexdigest()}
                    for t, c, rid, old, new in changes]}, backup)
                backup.flush()
                os.fsync(backup.fileno())
            for table, column, rowid, old, new in changes:
                db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (new, rowid))
            db.commit()
        elif apply:
            db.rollback()
        legacy_admin_sessions = (db.execute("SELECT COUNT(*) FROM admin_sessions WHERE token NOT LIKE 'sha256:%'").fetchone()[0]
                                 if "admin_sessions" in tables else 0)
        return {"database": str(path), "applied": apply, "changed_fields": len(changes),
                "counts": counts, "legacy_admin_session_rows": legacy_admin_sessions,
                "private_backup": str(backup_path) if backup_path else None}
    except Exception:
        if apply:
            db.rollback()
        raise
    finally:
        db.close()
