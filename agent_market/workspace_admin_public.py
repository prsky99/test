"""Reviewed public-service changes; no administrator can mint visitor consent."""

import base64
import hashlib
import hmac
import ipaddress
import json
import math
import re
import time
from contextlib import contextmanager

from .gateway import sns
from .workspace_admin_accounts import AccountChanges
from .workspace_admin_events import (
    canonical,
    execute,
    register,
    rows,
    signature,
    transaction,
)
from .workflows import public_template, sensitive

FIELDS = ("name", "description", "category", "trigger_type", "tags", "nodes", "edges")
register(
    {
        "public_rule": "SELECT ip,action,reason,created_at,expires_at FROM security_ip_rules WHERE ip=?",
        "public_rule_delete": "DELETE FROM security_ip_rules WHERE ip=?",
        "public_rule_write": """INSERT INTO security_ip_rules(ip,action,reason,created_at,expires_at,blocked_hits,last_hit_at)
        VALUES(?,?,?,?,?,0,?) ON CONFLICT(ip) DO UPDATE SET action=excluded.action,reason=excluded.reason,
        created_at=excluded.created_at,expires_at=excluded.expires_at""",
        "public_meta": "SELECT key,value FROM meta WHERE key IN ('security_under_attack_mode','security_rate_multiplier') ORDER BY key",
        "public_meta_write": "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        "public_sns_post": "SELECT * FROM sns_posts WHERE id=? AND deleted=0",
    }
)


def text(value, maximum=300):
    if (
        not isinstance(value, str)
        or not 4 <= len(value.strip()) <= maximum
        or not value.isprintable()
    ):
        raise ValueError("변경 사유를 4~300자로 입력하세요.")
    return value.strip()


def public_copy(value, maximum):
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= maximum
        or re.search(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]", value)
        or re.search(
            r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|/Users/|/home/|-----BEGIN .*PRIVATE KEY)",
            value,
        )
    ):
        raise ValueError("공개 콘텐츠는 비밀값·개인 경로 없는 영어로 작성하세요.")
    return value.strip()


class PublicChanges:
    def __init__(self, store, security, updates, validate):
        self.store, self.security, self.updates, self.validate = (
            store,
            security,
            updates,
            validate,
        )

    def definition(self, fields, existing=None):
        from fastapi import HTTPException

        try:
            return self.validate(fields, existing)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from None

    @contextmanager
    def locked(self):
        with transaction(self.store) as db:
            # Acquire the SQLite writer fence before comparing the reviewed state.
            if (
                getattr(self.store, "backend", "") != "postgresql"
                and not db.in_transaction
            ):
                db.execute("BEGIN IMMEDIATE")
            yield db

    def stamp(self, value):
        key = getattr(self.store, "_workspace_admin_event_key", None) or getattr(
            self.updates, "key", None
        )
        if key is None:
            raise ValueError("공통 승인 저장소를 먼저 준비하세요.")
        return signature(key, ["admin-public-state-v1", value])

    def workflow(self, identity):
        if type(identity) is not int or identity <= 0:
            raise ValueError("워크플로 ID를 확인하세요.")
        row = self.store.get_workflow(identity)
        if not row:
            raise ValueError("워크플로를 찾을 수 없습니다.")
        graph = row.get("nodes", [])
        if sensitive(graph) or any(
            n.get("data", {}).get("credential_refs") for n in graph
        ):
            raise ValueError(
                "비공개 자격증명이 바인딩된 정의는 공개 편집기로 열 수 없습니다."
            )
        value = {k: row.get(k) for k in (*FIELDS, "is_template", "is_active")}
        return row, value

    def template(self, identity):
        row, value = self.workflow(identity)
        return {"id": row["id"], **value, "revision": self.stamp(value)}

    def security_state(self, db, action, target):
        if action in ("block", "allow", "remove"):
            return rows(db, "public_rule", (target,))
        if action == "remove_blocks":
            result = []
            for ip in target:
                rule = rows(db, "public_rule", (ip,))
                if len(rule) != 1 or rule[0]["action"] != "block":
                    raise ValueError("선택한 차단 규칙이 변경됐습니다.")
                result.extend(rule)
            return result
        return rows(db, "public_meta")

    def prepare(self, user, domain, body):
        if not isinstance(body, dict) or set(body) - {
            "action",
            "target",
            "fields",
            "revision",
            "reason",
        }:
            raise ValueError("정확한 변경 항목을 입력하세요.")
        reason = text(body.get("reason"))
        action, target, fields = (
            body.get("action"),
            body.get("target"),
            body.get("fields", {}),
        )
        if not isinstance(fields, dict):
            raise ValueError("변경 항목은 객체여야 합니다.")
        uid = user["user_id"]
        with self.locked() as db:
            AccountChanges.highest(db, uid)
            before = None
            if domain == "security":
                if action in ("block", "allow", "remove"):
                    target = str(ipaddress.ip_address(target))
                elif action == "remove_blocks":
                    if not isinstance(target, list) or not 1 <= len(target) <= 100:
                        raise ValueError(
                            "명시적으로 선택한 IP 1~100개만 해제할 수 있습니다."
                        )
                    target = sorted(set(str(ipaddress.ip_address(ip)) for ip in target))
                elif action not in ("under_attack", "rate"):
                    raise ValueError("지원하지 않는 보안 변경입니다.")
                else:
                    target = "defense"
                if action in ("block", "allow"):
                    if set(fields) - {"duration"}:
                        raise ValueError("규칙 입력을 확인하세요.")
                    duration = fields.get("duration")
                    if duration is not None and (
                        type(duration) not in (int, float)
                        or not math.isfinite(duration)
                        or not 60 <= duration <= 30 * 86400
                    ):
                        raise ValueError("차단 기간은 60초~30일 또는 영구입니다.")
                    fields = {"duration": duration if action == "block" else None}
                elif action == "under_attack":
                    if (
                        set(fields) != {"enabled"}
                        or type(fields["enabled"]) is not bool
                    ):
                        raise ValueError("긴급 방어 값을 확인하세요.")
                elif action == "rate":
                    if (
                        set(fields) != {"multiplier"}
                        or type(fields["multiplier"]) not in (int, float)
                        or not math.isfinite(fields["multiplier"])
                        or not 0.05 <= fields["multiplier"] <= 2
                    ):
                        raise ValueError("요청 배율은 0.05~2 사이여야 합니다.")
                elif fields:
                    raise ValueError("추가 변경 항목은 허용하지 않습니다.")
                before = self.security_state(db, action, target)
            elif domain == "sns":
                if action == "create":
                    if set(fields) - {
                        "body",
                        "protocol",
                        "parent_key",
                        "resource_id",
                        "role",
                        "author",
                        "client",
                        "rating",
                    }:
                        raise ValueError("지원하지 않는 게시 항목입니다.")
                    fields = {
                        "body": public_copy(fields.get("body"), sns.MAX_BODY),
                        "role": fields.get("role", "developer"),
                        "protocol": fields.get("protocol") or None,
                        "parent_key": fields.get("parent_key") or None,
                        "resource_id": fields.get("resource_id"),
                        "rating": fields.get("rating"),
                    }
                    if fields["role"] not in sns.WRITER_ROLES or fields[
                        "protocol"
                    ] not in (None, *sns.PROTOCOLS):
                        raise ValueError(
                            "공식 글을 에이전트나 검증된 고객 글로 위장할 수 없습니다."
                        )
                    if fields["rating"] is not None and (
                        type(fields["rating"]) is not int
                        or not 1 <= fields["rating"] <= 5
                    ):
                        raise ValueError("평점은 1~5 정수입니다.")
                    if fields["resource_id"] is not None and (
                        type(fields["resource_id"]) is not int
                        or not self.store.resource(fields["resource_id"])
                    ):
                        raise ValueError("등록된 에이전트를 선택하세요.")
                    if fields["parent_key"] is not None and not re.fullmatch(
                        r"[a-z]+:[\w:.\-]{1,120}", fields["parent_key"]
                    ):
                        raise ValueError("원본 글 참조를 확인하세요.")
                    target = fields.get("parent_key") or "post"
                elif action == "delete":
                    if (
                        not isinstance(target, str)
                        or not re.fullmatch(r"p:[1-9][0-9]*", target)
                        or fields
                    ):
                        raise ValueError(
                            "직접 작성된 글 한 개만 검토 후 보관할 수 있습니다."
                        )
                    before = rows(db, "public_sns_post", (int(target[2:]),))
                    if not before:
                        raise ValueError("글이 없거나 이미 보관됐습니다.")
                else:
                    raise ValueError("지원하지 않는 공개 글 변경입니다.")
            elif domain == "template":
                if set(fields) - set(FIELDS):
                    raise ValueError("공개 편집 항목만 저장할 수 있습니다.")
                if action not in (
                    "create",
                    "create_public",
                    "update",
                    "publish",
                    "unpublish",
                ):
                    raise ValueError("지원하지 않는 템플릿 변경입니다.")
                existing = None
                if action not in ("create", "create_public"):
                    existing, before = self.workflow(target)
                    if body.get("revision") != self.stamp(before):
                        raise ValueError("워크플로가 변경됐습니다. 다시 조회하세요.")
                candidate = self.definition(
                    {
                        **fields,
                        "is_template": int(
                            action in ("publish", "create_public")
                            or action == "update"
                            and bool(existing and existing["is_template"])
                        ),
                        "is_active": 1 if action != "unpublish" else 0,
                        "trigger_type": "manual",
                    },
                    existing,
                )
                if candidate.get("is_template") and candidate.get("is_active"):
                    public_copy(candidate.get("name"), 200)
                    if (
                        re.search(
                            r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]",
                            json.dumps(
                                {k: candidate.get(k) for k in FIELDS},
                                ensure_ascii=False,
                            ),
                        )
                        or public_template(candidate) is None
                    ):
                        raise ValueError("공개 정의는 안전한 영어 그래프여야 합니다.")
                if sensitive(candidate.get("nodes", [])) or any(
                    n.get("data", {}).get("credential_refs")
                    for n in candidate.get("nodes", [])
                ):
                    raise ValueError(
                        "공개 편집기는 자격증명 바인딩을 저장하지 않습니다."
                    )
                fields = {
                    k: candidate.get(k)
                    for k in (*FIELDS, "is_template", "is_active")
                    if k in candidate
                }
            else:
                raise ValueError("지원하지 않는 변경 영역입니다.")
        return {
            "domain": domain,
            "action": action,
            "target": target,
            "fields": fields,
            "requester": uid,
            "before": self.stamp(before),
            "reason": reason,
        }, reason

    def restrictive(self, payload):
        if payload["domain"] != "security":
            return False
        with transaction(self.store, True) as db:
            before = self.security_state(db, payload["action"], payload["target"])
        if self.stamp(before) != payload["before"]:
            raise ValueError("규칙이 변경됐습니다. 다시 조회하세요.")
        action, f = payload["action"], payload["fields"]
        if action == "block":
            old = before[0] if before else None
            return (
                not old
                or old["action"] == "allow"
                or f["duration"] is None
                or old["expires_at"] is not None
                and time.time() + f["duration"] >= old["expires_at"]
            )
        if action == "remove":
            return bool(before and before[0]["action"] == "allow")
        if action == "under_attack":
            current = {r["key"]: json.loads(r["value"]) for r in before}
            default = (
                0.2
                if current.get("security_under_attack_mode", {}).get("enabled")
                else 1
            )
            rate = current.get("security_rate_multiplier", {}).get(
                "multiplier", default
            )
            return f["enabled"] is True and 0.2 <= rate
        if action == "rate":
            current = {r["key"]: json.loads(r["value"]) for r in before}
            default = (
                0.2
                if current.get("security_under_attack_mode", {}).get("enabled")
                else 1
            )
            return f["multiplier"] <= current.get("security_rate_multiplier", {}).get(
                "multiplier", default
            )
        return False

    def apply(self, payload, reviewer):
        if payload["domain"] == "task":
            return self.apply_task(payload, reviewer)
        with self.locked() as db:
            AccountChanges.highest(db, payload["requester"])
            AccountChanges.highest(db, reviewer)
            domain, action, target, fields = (
                payload[k] for k in ("domain", "action", "target", "fields")
            )
            if domain == "security":
                current = self.security_state(db, action, target)
            elif domain == "sns":
                current = (
                    rows(db, "public_sns_post", (int(target[2:]),))
                    if action == "delete"
                    else None
                )
            else:
                current = (
                    self.workflow(target)[1]
                    if action not in ("create", "create_public")
                    else None
                )
            if self.stamp(current) != payload["before"]:
                raise ValueError("승인 이후 대상이 변경됐습니다. 새 요청을 검토하세요.")
            if domain == "sns":
                if action == "create":
                    result = sns.create_post(
                        self.store,
                        fields["body"],
                        "Agent Concierge",
                        fields["role"],
                        "staff:" + str(payload["requester"]),
                        fields["protocol"],
                        fields["rating"],
                        fields["parent_key"],
                        fields["resource_id"],
                    )
                else:
                    sns.delete_post(self.store, target, current[0]["client_id"])
                    result = {"archived": target}
            elif domain == "template":
                # Revalidate against current capabilities at application, not just request creation.
                self.definition(
                    fields,
                    self.store.get_workflow(target)
                    if action not in ("create", "create_public")
                    else None,
                )
                if action in ("create", "create_public"):
                    target = self.store.create_workflow(
                        {**fields, "author": "Agent Concierge"}
                    )
                elif not self.store.update_workflow(target, fields):
                    raise ValueError("정의를 저장하지 못했습니다.")
                result = {
                    "workflow_id": target,
                    "published": bool(
                        fields.get("is_template") and fields.get("is_active")
                    ),
                }
            else:
                now = time.time()
                if action in ("block", "allow"):
                    expiry = now + fields["duration"] if fields["duration"] else None
                    execute(
                        db,
                        "public_rule_write",
                        (target, action, payload["reason"], now, expiry, now),
                    )
                elif action in ("remove", "remove_blocks"):
                    for ip in target if action == "remove_blocks" else [target]:
                        execute(db, "public_rule_delete", (ip,))
                elif action == "under_attack":
                    execute(
                        db,
                        "public_meta_write",
                        (
                            "security_under_attack_mode",
                            canonical(
                                {"enabled": fields["enabled"], "updated_at": now}
                            ),
                        ),
                    )
                    execute(
                        db,
                        "public_meta_write",
                        (
                            "security_rate_multiplier",
                            canonical({"multiplier": 0.2 if fields["enabled"] else 1}),
                        ),
                    )
                else:
                    execute(
                        db,
                        "public_meta_write",
                        ("security_rate_multiplier", canonical(fields)),
                    )
                result = {"action": action, "target": target, **fields}
        if domain == "security":
            self.security.reload_rules()
            if action in ("allow", "remove", "remove_blocks"):
                with self.security._lock:
                    for ip in target if action == "remove_blocks" else [target]:
                        self.security._violation_hits.pop(ip, None)
            if self.security.redis.is_available() and action in (
                "block",
                "allow",
                "remove",
                "remove_blocks",
            ):
                for ip in target if action == "remove_blocks" else [target]:
                    if action == "block":
                        self.security.redis.jail_ip(
                            ip,
                            payload["reason"],
                            duration_seconds=fields["duration"],
                            prefix=self.security.redis_prefix,
                        )
                    else:
                        self.security.redis.unban_ip(
                            ip, prefix=self.security.redis_prefix
                        )
        return result

    def task_request(self, user, visitor, watch, token, reason):
        if self.updates is None:
            raise ValueError("작업 알림이 준비되지 않았습니다.")
        try:
            if not isinstance(token, str) or len(token) > 3000:
                raise ValueError()
            raw, signed = token.rsplit(".", 1)
            expected = hmac.new(
                self.updates.key, ("admin-preview:" + raw).encode(), hashlib.sha256
            ).hexdigest()
            claims = json.loads(base64.urlsafe_b64decode(raw))
            if (
                not hmac.compare_digest(expected, signed)
                or claims["visitor"] != visitor
                or claims["watch"] != watch
                or claims["actor"] != user["username"]
                or claims["expires"] <= time.time()
            ):
                raise ValueError()
        except (AttributeError, ValueError, KeyError, TypeError):
            raise ValueError("정확한 작업 미리보기를 다시 확인하세요.") from None
        current = self.updates.preview(visitor, watch, user["username"])
        if (
            not current["can_process"]
            or claims["fingerprint"] != current["fingerprint"]
        ):
            raise ValueError("작업 동의 또는 추천 증거가 변경됐습니다.")
        return {
            "domain": "task",
            "requester": user["user_id"],
            "actor": user["username"],
            "visitor": visitor,
            "watch": watch,
            "fingerprint": current["fingerprint"],
            "expires_at": claims["expires"],
            "reason": text(reason),
        }

    def apply_task(self, payload, reviewer):
        with transaction(self.store, True) as db:
            AccountChanges.highest(db, payload["requester"])
            AccountChanges.highest(db, reviewer)
        if time.time() >= payload["expires_at"]:
            raise ValueError("5분 미리보기가 만료됐습니다. 새로 검토하세요.")
        current = self.updates.preview(
            payload["visitor"], payload["watch"], payload["actor"]
        )
        if (
            not current["can_process"]
            or current["fingerprint"] != payload["fingerprint"]
        ):
            raise ValueError("인증·동의·추천 또는 대기 이벤트가 변경됐습니다.")
        return self.updates.process_preview(
            payload["visitor"],
            payload["watch"],
            payload["actor"],
            current["preview_token"],
        )
