"""Small, bounded read models for renewal work queues and storage evidence.

No private customer bodies, execution inputs or deployment credentials are read.
Storage samples are written by the existing operations worker, never by GET.
"""

import csv
import base64
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import time

from fastapi import HTTPException, Request
from .workspace_admin_events import register, rows, execute, transaction
from .workflow_publication_service import same_origin

register(
    {
        "completion_orgs": "SELECT COUNT(*) AS n FROM customer_organizations WHERE active=1",
        "completion_cases": "SELECT COUNT(*) AS n FROM workspace_admin_cases WHERE status NOT IN ('resolved','closed')",
        "completion_incidents": "SELECT COUNT(*) AS n FROM workspace_admin_incidents WHERE status NOT IN ('resolved','closed')",
        "completion_reviews": "SELECT (SELECT COUNT(*) FROM admin_reviewed_commands WHERE status='pending' AND created>?) + (SELECT COUNT(*) FROM workspace_admin_commands WHERE status='pending' AND created>?) AS n",
        "completion_verified": "SELECT COUNT(*) AS n FROM capability_eligibility e JOIN connection_versions v ON v.id=e.version_id JOIN resources r ON r.id=e.resource_id WHERE e.outcome='succeeded' AND e.expires>? AND v.schema_complete=1 AND r.active=1",
        "completion_audit": "SELECT id,at,action,action_name,status FROM admin_audit_logs ORDER BY at DESC,id DESC LIMIT 10",
        "completion_search_drafts": "SELECT d.id,d.workspace_id,d.name,d.revision FROM workspace_drafts d JOIN workspace_memberships m ON m.workspace_id=d.workspace_id WHERE m.user_id=? AND m.active=1 AND d.active=1 AND (d.id=? OR d.name LIKE ? ESCAPE '!') ORDER BY d.updated DESC,d.id DESC LIMIT 21",
        "completion_storage": "SELECT value FROM workspace_admin_state WHERE id='admin_completion.storage'",
        "completion_storage_put": "INSERT INTO workspace_admin_state(id,value) VALUES('admin_completion.storage',?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
    }
)

REQUESTS = {
    "inquiries": (
        "SELECT * FROM customer_inquiries WHERE (?='' OR status=?) AND (?='' OR inquiry_id LIKE ? ESCAPE '!' OR name LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!' OR subject LIKE ? ESCAPE '!' OR message LIKE ? ESCAPE '!') AND (CAST(? AS DOUBLE PRECISION) IS NULL OR created_at<? OR (created_at=? AND id<?)) ORDER BY created_at DESC,id DESC LIMIT ?",
        "SELECT COUNT(*) AS n FROM customer_inquiries WHERE (?='' OR status=?) AND (?='' OR inquiry_id LIKE ? ESCAPE '!' OR name LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!' OR subject LIKE ? ESCAPE '!' OR message LIKE ? ESCAPE '!')",
    ),
    "privacy": (
        "SELECT * FROM privacy_requests WHERE (?='' OR status=?) AND (?='' OR request_id LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!' OR visitor_token_masked LIKE ? ESCAPE '!' OR details LIKE ? ESCAPE '!' OR proof_hash LIKE ? ESCAPE '!') AND (CAST(? AS DOUBLE PRECISION) IS NULL OR created_at<? OR (created_at=? AND id<?)) ORDER BY created_at DESC,id DESC LIMIT ?",
        "SELECT COUNT(*) AS n FROM privacy_requests WHERE (?='' OR status=?) AND (?='' OR request_id LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!' OR visitor_token_masked LIKE ? ESCAPE '!' OR details LIKE ? ESCAPE '!' OR proof_hash LIKE ? ESCAPE '!')",
    ),
    "cancellations": (
        "SELECT * FROM cancellation_requests WHERE (?='' OR status=?) AND (?='' OR request_id LIKE ? ESCAPE '!' OR token_masked LIKE ? ESCAPE '!' OR reason LIKE ? ESCAPE '!' OR source LIKE ? ESCAPE '!' OR visitor_id LIKE ? ESCAPE '!') AND (CAST(? AS DOUBLE PRECISION) IS NULL OR created_at<? OR (created_at=? AND id<?)) ORDER BY created_at DESC,id DESC LIMIT ?",
        "SELECT COUNT(*) AS n FROM cancellation_requests WHERE (?='' OR status=?) AND (?='' OR request_id LIKE ? ESCAPE '!' OR token_masked LIKE ? ESCAPE '!' OR reason LIKE ? ESCAPE '!' OR source LIKE ? ESCAPE '!' OR visitor_id LIKE ? ESCAPE '!')",
    ),
}
register(
    {
        ("completion_requests_" + kind + suffix): sql
        for kind, pair in REQUESTS.items()
        for suffix, sql in zip(("_page", "_count"), pair)
    }
)


def request_page(reader, kind, status, q, cursor, limit):
    marker = [None, None]
    if cursor:
        try:
            if len(cursor) > 120:
                raise ValueError()
            marker = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if (
                type(marker) is not list
                or len(marker) != 2
                or type(marker[0]) not in (int, float)
                or not math.isfinite(marker[0])
                or marker[0] < 0
                or type(marker[1]) is not int
                or not 0 < marker[1] < 2**62
            ):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, "목록 커서를 확인하세요.") from None
    pattern = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    params = (status, status, q, *([pattern] * 5))
    with reader() as db:
        found = rows(
            db,
            "completion_requests_" + kind + "_page",
            (*params, marker[0], marker[0], marker[0], marker[1], limit + 1),
        )
        total = (
            rows(db, "completion_requests_" + kind + "_count", params)[0]["n"]
            if not cursor
            else None
        )
    more = len(found) > limit
    found = found[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps([found[-1]["created_at"], found[-1]["id"]]).encode()
        )
        .decode()
        .rstrip("=")
        if more
        else None
    )
    return found, total, next_cursor


def csv_bytes(items):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["ID", "Name", "Protocol", "Status", "Grade"])
    for item in items:
        values = [
            item.get(k, "")
            for k in ("id", "name", "kind", "health_status", "eval_grade")
        ]
        writer.writerow(
            [
                (
                    "'" + str(v)
                    if str(v).lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                    else str(v or "")
                )
                for v in values
            ]
        )
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def sample_storage(store, now=None):
    if getattr(store, "backend", None) != "postgresql":
        return False
    now = time.time() if now is None else now
    with transaction(store, True) as db:
        found = rows(db, "completion_storage")
    previous = json.loads(found[0]["value"]) if found else {"samples": []}
    if now - previous.get("captured_at", 0) < 3600:
        return False
    from .admin_next import _STORAGE_PG, _DATABASE_PG

    with store.tx(readonly=True):
        sizes = [dict(row) for row in store._execute(_STORAGE_PG).fetchall()]
        database = dict(store._execute(_DATABASE_PG).fetchone())
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    samples = [s for s in previous.get("samples", []) if s["day"] != day][-8:]
    samples.append(
        {
            "day": day,
            "at": now,
            "database_bytes": database["bytes"],
            "tables": {s["name"]: s["bytes"] for s in sizes},
        }
    )
    with transaction(store) as db:
        execute(
            db,
            "completion_storage_put",
            (json.dumps({"captured_at": now, "samples": samples}),),
        )
    return True


def file_evidence():
    result = {"backup": {"configured": False}, "archive": {"configured": False}}
    backup_root = os.environ.get("AGENTCON_ADMIN_BACKUP_ROOT")
    archive = os.environ.get("AGENTCON_ADMIN_SQLITE_ARCHIVE")
    if backup_root:
        result["backup"] = {"configured": True, "available": False}
        try:
            root = Path(backup_root).expanduser()
            if root.resolve() != root.absolute():
                raise ValueError()
            manifest = root / "manifest.json"
            if manifest.is_symlink() or manifest.stat().st_size > 131072:
                raise ValueError()
            data = json.loads(manifest.read_text())
            created = data.get("created")
            digest = data.get("files", {}).get("database.dump", {}).get(
                "sha256"
            ) or data.get("database_sha256")
            if (
                type(created) not in (int, float)
                or not math.isfinite(created)
                or created > time.time() + 5
                or created <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", digest or "")
            ):
                raise ValueError()
            result["backup"].update(
                available=True,
                created=created,
                age_seconds=max(0, time.time() - created),
                stale=time.time() - created > 86400,
                integrity="not_checked_by_web",
                restore_verified=False,
            )
            report = root / "restore-report.json"
            if (
                report.is_file()
                and not report.is_symlink()
                and report.stat().st_size <= 131072
            ):
                restored = json.loads(report.read_text())
                at = restored.get("completed")
                if (
                    restored.get("backup_sha256") == digest
                    and restored.get("restore_rehearsed") is True
                    and restored.get("isolated_cluster") is True
                    and restored.get("production_modified") is False
                    and type(at) in (int, float)
                    and created <= at <= time.time() + 5
                ):
                    result["backup"].update(restore_verified=True, restore_completed=at)
        except (OSError, ValueError, TypeError, AttributeError):
            if result["backup"].get("available"):
                result["backup"]["restore_record_unavailable"] = True
    if archive:
        result["archive"] = {"configured": True, "available": False}
        try:
            path = Path(archive).expanduser()
            if path.resolve() != path.absolute() or not path.is_file():
                raise ValueError()
            stat = path.stat()
            result["archive"].update(
                available=True,
                bytes=stat.st_size,
                modified=stat.st_mtime,
                contents_inspected=False,
            )
        except (OSError, ValueError):
            pass
    return result


def install(router, *, store, authorize, reader):
    def staff(request, roles=("superadmin", "admin", "operator", "viewer")):
        if not same_origin(request):
            raise HTTPException(403, "동일 출처에서 요청하세요.")
        user = authorize(
            request,
            request.headers.get("authorization"),
            request.headers.get("x-dashboard"),
        )
        if not user.get("is_authenticated_session") or user.get("role") not in roles:
            raise HTTPException(403, "현재 개인 직원 권한이 필요합니다.")
        return user

    def query(name, params=()):
        with reader() as db:
            return rows(db, name, params)

    @router.get("/admin/api/v2/home/work")
    def work(request: Request):
        user = staff(request)
        values = {}
        for key, name, params in [
            ("organizations", "completion_orgs", ()),
            ("cases", "completion_cases", ()),
            ("incidents", "completion_incidents", ()),
            ("reviews", "completion_reviews", (time.time() - 900, time.time() - 900)),
            ("verified_agents", "completion_verified", (time.time(),)),
        ]:
            try:
                values[key] = query(name, params)[0]["n"]
            except Exception:
                values[key] = None
        audit = []
        if user["role"] in ("superadmin", "admin"):
            audit = query("completion_audit")
        return {
            **values,
            "audit": audit,
            "audit_allowed": user["role"] in ("superadmin", "admin"),
            "captured_at": time.time(),
        }

    @router.get("/admin/api/v2/home/workflows")
    def workflows(request: Request, q: str = ""):
        user = staff(request, ("superadmin", "admin"))
        if not 1 <= len(q.strip()) <= 120:
            raise HTTPException(400, "워크플로 이름 또는 ID를 입력하세요.")
        pattern = (
            "%"
            + q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            + "%"
        )
        found = query("completion_search_drafts", (user["user_id"], q.strip(), pattern))
        return {
            "items": found[:20],
            "next_cursor": None,
            "truncated": len(found) > 20,
            "captured_at": time.time(),
            "scope": "현재 직원 멤버십으로 접근 가능한 활성 초안. 고객 비공개 본문은 검색하지 않습니다.",
        }

    @router.get("/admin/api/v2/system/evidence")
    def evidence(request: Request):
        staff(request, ("superadmin",))
        try:
            found = query("completion_storage")
        except Exception:
            return {
                **file_evidence(),
                "storage": {
                    "available": False,
                    "samples": [],
                    "captured_at": None,
                    "reason": "용량 기록 저장소를 확인할 수 없습니다. 마이그레이션과 작업자 상태를 확인하세요.",
                },
                "captured_at": time.time(),
            }
        sampling = (
            json.loads(found[0]["value"])
            if found
            else {"samples": [], "captured_at": None}
        )
        return {**file_evidence(), "storage": sampling, "captured_at": time.time()}
