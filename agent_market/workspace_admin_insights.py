"""Bounded, content-free console evidence and narrow operational assignment."""

import json
import math
import re
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request

from .workflow_publication_service import read_object, same_origin
from .workspace_admin_events import execute, register, rows, transaction
from .workspace_service import WorkspaceRoute

BASE = "/admin/api/v2/insights"
register(
    {
        "insight_attempts": """SELECT a.id,a.resource_id,a.protocol,a.status,a.error_code,a.created,a.dispatched,a.finished,a.elapsed_ms,o.source
        FROM platform_attempts a JOIN platform_operations o ON o.id=a.operation_id
        WHERE a.created>? ORDER BY a.created DESC,a.id DESC LIMIT 5001""",
        "insight_agent_calls": """SELECT a.id,a.status,a.error_code,a.protocol,a.created,a.dispatched,a.finished,a.elapsed_ms,o.source
        FROM platform_attempts a JOIN platform_operations o ON o.id=a.operation_id
        WHERE a.resource_id=? ORDER BY a.created DESC,a.id DESC LIMIT 50""",
        "insight_versions": """SELECT id,profile_version,schema_complete,created FROM connection_versions
        WHERE resource_id=? ORDER BY created DESC,id DESC LIMIT 50""",
        "insight_evidence": """SELECT e.id,e.version_id,e.scope,e.outcome,e.finished,e.expires,e.code,e.contract_id
        FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
        WHERE v.resource_id=? ORDER BY e.finished DESC,e.id DESC LIMIT 50""",
        "insight_audit": """SELECT id,at,action,status,details FROM admin_audit_logs WHERE target=?
        ORDER BY at DESC,id DESC LIMIT 50""",
        "insight_case_queue": """SELECT id,status,priority,assigned_to,revision,updated FROM workspace_admin_cases
        WHERE id>? ORDER BY id LIMIT 51""",
        "insight_case": "SELECT id,revision FROM workspace_admin_cases WHERE id=?",
        "insight_case_assign": """UPDATE workspace_admin_cases SET assigned_to=?,revision=revision+1,updated=?
        WHERE id=? AND revision=?""",
        "insight_graph_agent": "SELECT id,kind,active,health_status,eval_grade FROM resources WHERE id=?",
        "insight_graph_run": """SELECT id,status,digest,created FROM workflow_runs WHERE workflow_id=? ORDER BY created DESC,id DESC LIMIT 1""",
        "insight_graph_steps": "SELECT node_id,status,started,finished FROM workflow_node_runs WHERE run_id=? ORDER BY node_id LIMIT 50",
        "insight_staff": "SELECT id,role,active FROM admin_users WHERE id=?",
    }
)


def percentile(values, share=0.95):
    values = sorted(
        x for x in values if type(x) in (int, float) and math.isfinite(x) and x >= 0
    )
    return values[max(0, math.ceil(len(values) * share) - 1)] if values else None


def aggregate(attempts, hours, now):
    complete = len(attempts) <= 5000
    attempts = attempts[:5000]
    width = max(60, hours * 3600 / 60)
    buckets, protocols, agents, codes = {}, {}, {}, defaultdict(lambda: [0, 0])
    for a in attempts:
        ok = a["status"] == "succeeded"
        slot = math.floor(a["created"] / width) * width
        bucket = buckets.setdefault(slot, {"at": slot, "calls": 0, "succeeded": 0})
        bucket["calls"] += 1
        bucket["succeeded"] += ok
        for mapping, key in (
            (protocols, a["protocol"] or "unknown"),
            (agents, a["resource_id"]),
        ):
            item = mapping.setdefault(
                key,
                {
                    "key": key,
                    "calls": 0,
                    "succeeded": 0,
                    "latencies": [],
                    "pre_dispatch": [],
                },
            )
            item["calls"] += 1
            item["succeeded"] += ok
            item["latencies"].append(a["elapsed_ms"])
            if a["dispatched"] is not None and a["dispatched"] >= a["created"]:
                item["pre_dispatch"].append((a["dispatched"] - a["created"]) * 1000)
        if a["error_code"] and a["created"] >= now - 1200:
            codes[a["error_code"]][0 if a["created"] >= now - 600 else 1] += 1

    def finish(mapping):
        result = []
        for item in mapping.values():
            latency = item.pop("latencies")
            delay = item.pop("pre_dispatch")
            item.update(
                p95_ms=percentile(latency),
                pre_dispatch_p95_ms=percentile(delay),
                pre_dispatch_samples=len(delay),
                success_rate=item["succeeded"] / item["calls"],
            )
            result.append(item)
        return sorted(result, key=lambda x: (-x["calls"], str(x["key"])))

    recent = [a for a in attempts if a["created"] >= now - 300]
    alerts = []
    if (
        len(recent) >= 20
        and sum(a["status"] == "succeeded" for a in recent) / len(recent) < 0.9
    ):
        alerts.append(
            {"code": "LOW_SUCCESS_5M", "scope": "sample", "samples": len(recent)}
        )
    p95 = percentile([a["elapsed_ms"] for a in recent])
    if p95 is not None and p95 > 8000:
        alerts.append({"code": "HIGH_LATENCY_5M", "scope": "sample", "p95_ms": p95})
    if complete:
        alerts.extend(
            {
                "code": "ERROR_GROWTH_10M",
                "error_code": code,
                "current": n,
                "previous": old,
            }
            for code, (n, old) in codes.items()
            if old >= 3 and n >= 3 * old
        )
    return {
        "captured_at": now,
        "hours": hours,
        "available": True,
        "sample_size": len(attempts),
        "sample_limit": 5000,
        "sample_complete": complete,
        "buckets": sorted(buckets.values(), key=lambda x: x["at"]),
        "bucket_seconds": width,
        "protocols": finish(protocols),
        "agents": finish(agents)[:50],
        "alerts": alerts,
        "pacing": {
            "available": False,
            "reason": "No dedicated pacing duration is recorded across all execution paths.",
        },
        "pre_dispatch_scope": "Preparation-to-dispatch includes validation, scheduling and pacing; it is not dedicated pacing.",
        "eligibility_transition_scope": "Verification evidence is historical; it is not a complete candidate-admission transition log.",
    }


def install(router, *, store, authorize, reader, log_op, reviews):
    api = APIRouter(route_class=WorkspaceRoute)

    def staff(request, roles=("superadmin", "admin", "operator")):
        if not same_origin(request):
            raise HTTPException(403, "동일 출처의 직원 화면에서 요청하세요.")
        user = authorize(
            request,
            request.headers.get("authorization"),
            request.headers.get("x-dashboard"),
        )
        if not user.get("is_authenticated_session") or user["role"] not in roles:
            raise HTTPException(403, "현재 개인 직원 권한이 필요합니다.")
        request.state.admin_user = user
        return user

    def query(name, params=()):
        with reader() as db:
            return rows(db, name, params)

    def resource(rid):
        if not 0 < rid < 2**62 or not store.resource(rid):
            raise HTTPException(404, "없는 에이전트입니다.")

    @api.get(BASE + "/gateway")
    def gateway(request: Request, hours: int = Query(24, ge=1, le=168)):
        staff(request)
        now = time.time()
        return aggregate(query("insight_attempts", (now - hours * 3600,)), hours, now)

    @api.get(BASE + "/agents/{rid}")
    def agent(rid: int, request: Request):
        user = staff(request)
        resource(rid)
        result = {
            "calls": query("insight_agent_calls", (rid,)),
            "versions": query("insight_versions", (rid,)),
            "evidence": query("insight_evidence", (rid,)),
            "captured_at": time.time(),
            "limit_per_section": 50,
        }
        if user["role"] in ("admin", "superadmin"):
            audit = query("insight_audit", ("agent:" + str(rid),))
            # Only dedicated note text is projected; arbitrary audit details may contain personal context.
            for row in audit:
                try:
                    details = json.loads(row.pop("details") or "{}")
                except (ValueError, TypeError):
                    details = {}
                row["note"] = (
                    (details.get("note") if isinstance(details, dict) else None)
                    if row["action"] == "ADMIN_AGENT_NOTE"
                    else None
                )
            result["audit"] = audit
        return result

    @api.post(BASE + "/agents/{rid}/notes")
    async def note(rid: int, request: Request):
        staff(request, ("admin", "superadmin"))
        resource(rid)
        body = await object_body(request)
        if (
            set(body) != {"reason", "note"}
            or not isinstance(body["note"], str)
            or not 1 <= len(body["note"].strip()) <= 1000
            or re.search(r"Bearer\s|sk-[\w-]{12,}|PRIVATE KEY", body["note"])
        ):
            raise HTTPException(400, "비밀값 없는 내부 메모를 1~1000자로 입력하세요.")
        request.state.audit_reason = reason(body["reason"])
        log_op(
            request,
            "ADMIN_AGENT_NOTE",
            "에이전트 내부 메모",
            target="agent:" + str(rid),
            details={"note": body["note"].strip()},
        )
        return {"ok": True, "invalidate": ["catalog:agent:" + str(rid)]}

    @api.get(BASE + "/workflows/{wid}/state")
    def graph_state(wid: int, request: Request):
        staff(request, ("admin", "superadmin"))
        if not 0 < wid < 2**62 or not store.get_workflow(wid):
            raise HTTPException(404, "없는 워크플로입니다.")
        found = query("insight_graph_run", (wid,))
        workflow = store.get_workflow(wid)
        ids = {
            node.get("resource_id")
            for node in workflow.get("nodes", [])
            if type(node.get("resource_id")) is int
        }
        agents = []
        with reader() as db:
            for rid in sorted(ids)[:50]:
                agents.extend(rows(db, "insight_graph_agent", (rid,)))
        return {
            "agents": agents,
            "run": found[0] if found else None,
            "steps": query("insight_graph_steps", (found[0]["id"],)) if found else [],
        }

    @api.get(BASE + "/assignments")
    def queue(request: Request, cursor: str = Query("", max_length=120)):
        staff(request)
        if not reviews.ready():
            return {"available": False, "items": [], "next_cursor": None}
        found = query("insight_case_queue", (cursor,))
        return {
            "available": True,
            "items": found[:50],
            "next_cursor": found[49]["id"] if len(found) > 50 else None,
        }

    @api.post(BASE + "/assignments/{case_id}")
    async def assign(case_id: str, request: Request):
        user = staff(request)
        body = await object_body(request)
        if not reviews.ready():
            raise HTTPException(409, "지원 관리 저장소를 먼저 준비하세요.")
        if (
            not re.fullmatch(r"[\w-]{1,120}", case_id)
            or set(body) != {"revision", "assigned_to", "reason"}
            or type(body["revision"]) is not int
            or body["revision"] < 1
            or body["assigned_to"] is not None
            and (type(body["assigned_to"]) is not int or body["assigned_to"] < 1)
        ):
            raise HTTPException(400, "대상·현재 버전·직원 ID를 확인하세요.")
        request.state.audit_reason = reason(body["reason"])
        log_op(
            request,
            "CASE_ASSIGN_INTENT",
            "지원 케이스 배정 의도",
            target=case_id,
            status="REQUESTED",
        )
        with transaction(store) as db:
            if getattr(store, "backend", "") != "postgresql" and not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            actor = rows(db, "insight_staff", (user["user_id"],))
            if (
                not actor
                or not actor[0]["active"]
                or actor[0]["role"] not in ("operator", "admin", "superadmin")
            ):
                raise HTTPException(403, "현재 직원 권한이 필요합니다.")
            if body["assigned_to"] is not None:
                target = rows(db, "insight_staff", (body["assigned_to"],))
                if (
                    not target
                    or not target[0]["active"]
                    or target[0]["role"] not in ("operator", "admin", "superadmin")
                ):
                    raise HTTPException(400, "활성 담당 직원을 선택하세요.")
            old = rows(db, "insight_case", (case_id,))
            if not old or old[0]["revision"] != body["revision"]:
                raise HTTPException(409, "케이스가 변경됐습니다. 다시 조회하세요.")
            if (
                execute(
                    db,
                    "insight_case_assign",
                    (body["assigned_to"], time.time(), case_id, body["revision"]),
                ).rowcount
                != 1
            ):
                raise HTTPException(409, "케이스가 변경됐습니다.")
        log_op(
            request,
            "CASE_ASSIGN",
            "지원 케이스 담당자 변경",
            target=case_id,
            details={"assigned_to": body["assigned_to"]},
        )
        return {
            "ok": True,
            "revision": body["revision"] + 1,
            "invalidate": ["customers"],
        }

    router.include_router(api)


async def object_body(request):
    try:
        return await read_object(request, 8192)
    except (ValueError, TimeoutError):
        raise HTTPException(400, "제한된 JSON 객체를 입력하세요.") from None


def reason(value):
    if (
        not isinstance(value, str)
        or not 4 <= len(value.strip()) <= 300
        or not value.isprintable()
    ):
        raise HTTPException(400, "변경 사유를 4~300자로 입력하세요.")
    return value.strip()
