"""게이트웨이 저장소 (SQLite + FTS5 검색 색인)."""

import hashlib
import json
import logging
import math
import random
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from urllib.parse import urlparse

log = logging.getLogger("agent_market.gateway.store")

from ..storage_security import private_sqlite_file
from ..legacy_vector_index import install as install_vector_index, register as register_vector_index
from ..observation_guards import (FIELDS as OBSERVATION_FIELDS, OWNERS as OBSERVATION_OWNERS,
                                  GuardError, ObservationToken, fingerprint, issue, validate)
from ..broker.categories import CATEGORIES, LEGACY_ALIASES
from .classify import VERSION as CLASSIFIER_VERSION
from .classify import OTHER as OTHER_CATEGORY, classify_listing, query_terms
from . import constraints as cons
from .admin_auth import init_admin_auth_db
from .rag import ensure_vec_table, load_sqlite_vec
from .sanitizer import sanitize_text, sanitize_email

CONSTRAINTS_VERSION = 2  # 추출 규칙이 바뀌면 올린다 → 저장된 에이전트의 제약 정보를 다시 채움
FTS_TOOLS_VERSION = 2  # Include normalized tool tags in existing FTS rows.


def extract_tool_search_text(tools_json: str | None) -> str:
    """usage_tools (또는 skills) JSON에서 FTS5 검색용 도구 이름과 설명을 추출한다."""
    if not tools_json:
        return ""
    try:
        tools = json.loads(tools_json)
        if not isinstance(tools, list):
            return ""
        parts = []
        for t in tools:
            if isinstance(t, dict):
                name = str(t.get("name") or t.get("id") or "").strip()
                desc = str(t.get("description") or t.get("title") or "").strip()
                tag_values = t.get("tags")
                if isinstance(tag_values, str):
                    tags = tag_values[:2000]
                elif isinstance(tag_values, list):
                    tags = " ".join(tag[:200] for tag in tag_values[:50] if isinstance(tag, str))
                else:
                    tags = ""
                if name:
                    parts.append(name)
                if desc:
                    parts.append(desc[:300])
                if tags:
                    parts.append(tags)
        # Keep raw tool evidence intact; PostgreSQL text cannot contain NUL.
        # Separate tokens in the derived search projection instead of joining them.
        return " ".join(parts).replace("\0", " ")
    except (ValueError, TypeError):
        return ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
    url TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
    networks TEXT NOT NULL, price_usdc INTEGER, pay_to TEXT, method TEXT, details TEXT NOT NULL,
    calls_30d INTEGER, payers_30d INTEGER, last_called REAL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    probe_ok INTEGER NOT NULL DEFAULT 0, probe_fail INTEGER NOT NULL DEFAULT 0,
    probe_latency_ms INTEGER, probed_at REAL
);
CREATE INDEX IF NOT EXISTS resources_cat ON resources(category, active);
CREATE VIRTUAL TABLE IF NOT EXISTS resources_fts USING fts5(name, description);
CREATE VIRTUAL TABLE IF NOT EXISTS resources_vocab USING fts5vocab(resources_fts, 'row');
CREATE TABLE IF NOT EXISTS needs (
    need_id TEXT PRIMARY KEY, client TEXT NOT NULL, task TEXT NOT NULL, category TEXT NOT NULL,
    max_price INTEGER, networks TEXT NOT NULL, kinds TEXT NOT NULL, webhook TEXT,
    status TEXT NOT NULL, current_resource INTEGER, current_score REAL,
    free_used INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL, ip TEXT
);
CREATE INDEX IF NOT EXISTS needs_client ON needs(client, category);
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY, need_id TEXT NOT NULL, resource_id INTEGER NOT NULL, prev_resource_id INTEGER,
    score REAL NOT NULL, prev_score REAL, teaser TEXT NOT NULL, fee INTEGER NOT NULL, free INTEGER NOT NULL,
    status TEXT NOT NULL, created REAL NOT NULL, decided_at REAL, payer TEXT, tx_hash TEXT
);
CREATE INDEX IF NOT EXISTS offers_need ON offers(need_id, status);
CREATE TABLE IF NOT EXISTS feedback (
    need_id TEXT NOT NULL, resource_id INTEGER NOT NULL, success INTEGER NOT NULL, rating INTEGER,
    created REAL NOT NULL, PRIMARY KEY (need_id, resource_id)
);
CREATE INDEX IF NOT EXISTS feedback_res ON feedback(resource_id);
CREATE TABLE IF NOT EXISTS fee_state (
    category TEXT PRIMARY KEY, fee INTEGER NOT NULL, window_offers INTEGER NOT NULL DEFAULT 0,
    window_accepted INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fee_history (
    category TEXT NOT NULL, old_fee INTEGER NOT NULL, new_fee INTEGER NOT NULL, conversion REAL NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health_checks (
    resource_id INTEGER NOT NULL, at REAL NOT NULL, outcome TEXT NOT NULL, status_code INTEGER,
    latency_ms INTEGER, error TEXT, observed_price INTEGER
);
CREATE INDEX IF NOT EXISTS health_checks_res ON health_checks(resource_id, at);
CREATE INDEX IF NOT EXISTS health_checks_at ON health_checks(at);
CREATE TABLE IF NOT EXISTS erc8004_tokens (
    chain TEXT NOT NULL, agent_id INTEGER NOT NULL, uri_hash TEXT, uri TEXT, host TEXT,
    status TEXT NOT NULL,  -- pending | resolved | no_service | error | empty
    services TEXT, checked_at REAL, next_at REAL, error TEXT,
    PRIMARY KEY (chain, agent_id)
);
CREATE INDEX IF NOT EXISTS erc8004_pending ON erc8004_tokens(status, next_at);
CREATE TABLE IF NOT EXISTS wellknown_hosts (
    host TEXT PRIMARY KEY, checked_at REAL NOT NULL, found TEXT
);
CREATE TABLE IF NOT EXISTS sns_posts (  -- 관리 화면 SNS: 사용자·개발자·에이전트가 쓴 글과 댓글 (gateway/sns.py)
    id INTEGER PRIMARY KEY, created REAL NOT NULL, author TEXT NOT NULL, handle TEXT NOT NULL, role TEXT NOT NULL,
    client_id TEXT NOT NULL, protocol TEXT, resource_id INTEGER, rating INTEGER, body TEXT NOT NULL, tags TEXT,
    parent_key TEXT, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sns_posts_created ON sns_posts(parent_key, created);
CREATE TABLE IF NOT EXISTS sns_likes (post_key TEXT NOT NULL, client_id TEXT NOT NULL, created REAL NOT NULL,
    PRIMARY KEY (post_key, client_id));
-- 에이전트 전용 프론트(컨시어지): 방문 에이전트 기억·대화·관심사·연락처·알림 (agent_market/concierge, AGENT_FRONT.md)
CREATE TABLE IF NOT EXISTS agent_visitors (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT, channel TEXT, user_agent TEXT, fingerprint TEXT,
    lang TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL, visits INTEGER NOT NULL DEFAULT 1,
    visit_days INTEGER NOT NULL DEFAULT 1, messages INTEGER NOT NULL DEFAULT 0, tier TEXT NOT NULL DEFAULT 'new',
    notify INTEGER NOT NULL DEFAULT 1, last_notified REAL, last_offset INTEGER NOT NULL DEFAULT 0, last_results TEXT,
    nurture_stage TEXT NOT NULL DEFAULT 'onboarded', last_nurture_at REAL
);
CREATE INDEX IF NOT EXISTS agent_visitors_fp ON agent_visitors(fingerprint, last_seen);
CREATE TABLE IF NOT EXISTS agent_contexts (context_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, created REAL NOT NULL,
    fingerprint TEXT, issued INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL, at REAL NOT NULL, role TEXT NOT NULL, channel TEXT,
    text TEXT NOT NULL, data TEXT
);
CREATE INDEX IF NOT EXISTS agent_messages_visitor ON agent_messages(visitor_id, id);
CREATE INDEX IF NOT EXISTS agent_messages_retention ON agent_messages(at, id);
CREATE TABLE IF NOT EXISTS agent_interests (
    id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL, task TEXT NOT NULL, task_norm TEXT NOT NULL, category TEXT,
    kind TEXT, auth_pref TEXT, created REAL NOT NULL, updated REAL NOT NULL, last_checked REAL,
    recommended TEXT, best_score REAL, active INTEGER NOT NULL DEFAULT 1, hint TEXT, UNIQUE (visitor_id, task_norm)
);
CREATE INDEX IF NOT EXISTS agent_interests_retention ON agent_interests(updated, id);
CREATE TABLE IF NOT EXISTS agent_outcomes (
    visitor_id TEXT NOT NULL, resource_id INTEGER NOT NULL, success INTEGER NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (visitor_id, resource_id)
);
CREATE TABLE IF NOT EXISTS agent_contacts (
    id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL, type TEXT NOT NULL, url TEXT NOT NULL, endpoint TEXT,
    status TEXT NOT NULL, code_hash TEXT, code_expires REAL, created REAL NOT NULL, verified_at REAL,
    failures INTEGER NOT NULL DEFAULT 0, last_error TEXT
);
CREATE INDEX IF NOT EXISTS agent_contacts_visitor ON agent_contacts(visitor_id, status);
CREATE TABLE IF NOT EXISTS agent_task_watches (
    id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, task TEXT NOT NULL, protocol TEXT,
    channel TEXT NOT NULL, state TEXT NOT NULL, sealed TEXT, code_hash TEXT,
    code_expires REAL, verify_failures INTEGER NOT NULL DEFAULT 0,
    verification_sent INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, expires REAL NOT NULL,
    last_event REAL, baseline TEXT, notice_version TEXT NOT NULL, authority INTEGER NOT NULL,
    revoked_at REAL, last_checked REAL NOT NULL DEFAULT 0, verified_at REAL
);
CREATE INDEX IF NOT EXISTS task_watches_owner ON agent_task_watches(visitor_id, created);
CREATE TABLE IF NOT EXISTS agent_task_destination_checks (
    watch_id TEXT PRIMARY KEY, notice_version TEXT NOT NULL, confirmed_at REAL NOT NULL,
    verified_at REAL, destination_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_marketing_permissions (
    watch_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, notice_version TEXT NOT NULL,
    requested_at REAL NOT NULL, verified_at REAL, withdrawn_at REAL, expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS marketing_permission_owner ON agent_marketing_permissions(visitor_id,watch_id);
CREATE TABLE IF NOT EXISTS agent_task_permissions (
    id INTEGER PRIMARY KEY, watch_id TEXT NOT NULL, visitor_id TEXT NOT NULL,
    action TEXT NOT NULL, purpose TEXT NOT NULL, notice_version TEXT NOT NULL, at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS task_permissions_watch_time ON agent_task_permissions(watch_id,at DESC,id DESC);
CREATE TABLE IF NOT EXISTS agent_task_events (
    id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL,
    evidence TEXT NOT NULL, error TEXT, UNIQUE(watch_id, evidence)
);
CREATE INDEX IF NOT EXISTS task_events_due ON agent_task_events(status, next_attempt);
CREATE TABLE IF NOT EXISTS agent_task_budgets (
    key TEXT PRIMARY KEY, started REAL NOT NULL, n INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_visitor_cases (
    visitor_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'new', owner TEXT NOT NULL DEFAULT '',
    next_followup REAL, updated REAL NOT NULL, updated_by TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS agent_visitor_case_notes (
    id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL, at REAL NOT NULL,
    actor TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS visitor_case_notes_owner ON agent_visitor_case_notes(visitor_id,id);
CREATE TABLE IF NOT EXISTS agent_notifications (
    id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL, contact_id INTEGER, at REAL NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, detail TEXT, items TEXT
);
CREATE INDEX IF NOT EXISTS agent_notifications_visitor ON agent_notifications(visitor_id, at);
CREATE TABLE IF NOT EXISTS agent_hits (  -- 토큰 없이 읽기만 한 방문 (익명, 지문별 집계)
    fingerprint TEXT PRIMARY KEY, user_agent TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 1, last_path TEXT
);
CREATE TABLE IF NOT EXISTS crawl_runs (
    at REAL NOT NULL, source TEXT NOT NULL, ok INTEGER NOT NULL, seen INTEGER, new INTEGER,
    deactivated INTEGER, seconds REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS public_availability_checks (
    checked_at REAL PRIMARY KEY, ok INTEGER NOT NULL, status_code INTEGER, latency_ms REAL
);
CREATE TABLE IF NOT EXISTS tool_inertia (
    from_resource_id INTEGER NOT NULL,
    from_tool TEXT NOT NULL,
    to_resource_id INTEGER NOT NULL,
    to_tool TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    last_transition REAL NOT NULL,
    PRIMARY KEY (from_resource_id, from_tool, to_resource_id, to_tool)
);
CREATE INDEX IF NOT EXISTS tool_inertia_from ON tool_inertia (from_resource_id, from_tool, count DESC);
CREATE TABLE IF NOT EXISTS agent_credits (
    account_id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    held INTEGER NOT NULL DEFAULT 0,
    total_deposited INTEGER NOT NULL DEFAULT 0,
    total_spent INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clearing_ledger (
    tx_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL,
    sla_verified INTEGER NOT NULL DEFAULT 0,
    receipt TEXT,
    created_at REAL NOT NULL,
    settled_at REAL
);
CREATE INDEX IF NOT EXISTS clearing_ledger_acc ON clearing_ledger (account_id, created_at);
CREATE TABLE IF NOT EXISTS vec_outbox (
    resource_id INTEGER PRIMARY KEY,
    enqueued_at REAL NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vec_outbox_time ON vec_outbox(enqueued_at);
CREATE TABLE IF NOT EXISTS agent_test_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id INTEGER,
    title TEXT NOT NULL,
    slug TEXT UNIQUE,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_url TEXT NOT NULL,
    category TEXT NOT NULL,
    eval_grade TEXT,
    eval_score REAL,
    status_code INTEGER,
    latency_ms REAL,
    is_success INTEGER NOT NULL DEFAULT 1,
    test_method TEXT NOT NULL,
    tool_name TEXT,
    input_wire TEXT,
    output_wire TEXT,
    summary TEXT NOT NULL,
    content_md TEXT NOT NULL,
    pros TEXT NOT NULL,
    cons TEXT NOT NULL,
    workflow_recommendation TEXT,
    tags TEXT,
    author TEXT NOT NULL DEFAULT 'AI Verification Agent',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_test_reports_res ON agent_test_reports(resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_test_reports_kind ON agent_test_reports(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_test_reports_url ON agent_test_reports(agent_url,kind,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_agent_test_reports_resource_kind ON agent_test_reports(resource_id,kind,created_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS test_report_subject_claims (
    subject_key TEXT PRIMARY KEY,
    report_id INTEGER REFERENCES agent_test_reports(id)
);
CREATE TABLE IF NOT EXISTS agent_workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    trigger_type TEXT NOT NULL DEFAULT 'manual',
    steps TEXT NOT NULL,
    tags TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_template INTEGER NOT NULL DEFAULT 0,
    author TEXT NOT NULL DEFAULT 'Admin',
    author_wallet TEXT DEFAULT '',
    parent_workflow_id INTEGER,
    forks_count INTEGER NOT NULL DEFAULT 0,
    likes_count INTEGER NOT NULL DEFAULT 0,
    runs_count INTEGER NOT NULL DEFAULT 0,
    rating_avg REAL NOT NULL DEFAULT 5.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name TEXT NOT NULL UNIQUE,
    key_value TEXT NOT NULL,
    provider TEXT NOT NULL,
    description TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(workflow_id) REFERENCES agent_workflows(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS customer_inquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inquiry_id TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    visitor_token TEXT,
    ip TEXT,
    user_agent TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_response TEXT,
    resolved_at REAL,
    resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_customer_inquiries_status ON customer_inquiries(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_customer_inquiries_email ON customer_inquiries(email);
CREATE TABLE IF NOT EXISTS cancellation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL,
    visitor_id TEXT,
    visitor_token_hash TEXT,
    token_masked TEXT,
    source TEXT NOT NULL DEFAULT 'ftc_footer',
    reason TEXT,
    ip TEXT,
    user_agent TEXT,
    status TEXT NOT NULL DEFAULT 'cancelled',
    reactivated_at REAL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_cancellation_requests_created ON cancellation_requests(created_at DESC);
CREATE TABLE IF NOT EXISTS privacy_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL,
    request_type TEXT NOT NULL,
    visitor_token_masked TEXT,
    email TEXT,
    details TEXT,
    ip TEXT,
    user_agent TEXT,
    gpc_detected INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    statutory_deadline REAL,
    completed_at REAL,
    proof_hash TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_privacy_requests_created ON privacy_requests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_requests_type ON privacy_requests(request_type, status);
"""

# 헬스체크 상태 컬럼 (기존 DB에는 ALTER TABLE로 추가)
HEALTH_COLUMNS = {
    "health_status": "TEXT NOT NULL DEFAULT 'unknown'",  # unknown | healthy | reachable | failing | down | retired
    "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
    "failing_since": "REAL",  # 연속 실패가 시작된 시각 (성공하면 초기화)
    "last_check_at": "REAL",
    "last_ok_at": "REAL",
    "next_check_at": "REAL",
    "last_status_code": "INTEGER",
    "last_error": "TEXT",
    "health_ok_24h": "INTEGER NOT NULL DEFAULT 0",
    "health_n_24h": "INTEGER NOT NULL DEFAULT 0",
    "content_hash": "TEXT",  # 수집한 내용의 지문. 같으면 다시 쓰지 않고 last_seen만 갱신
    "host": "TEXT",  # URL의 호스트 (호스트별로 나눠 점검하기 위해)
    # 제약 정보 (gateway/constraints.py)
    "desc_lang": "TEXT",  # 설명문 언어
    "regions": "TEXT",  # 설명문에 나온 대상 나라·지역 (',br,us,')
    "auth_declared": "INTEGER",  # 레지스트리 헤더로 본 인증 필요 여부 (1/0/NULL=모름)
    "auth_observed": "INTEGER",  # 헬스체크로 본 인증 필요 여부 (MCP 401/403 → 1, 200 → 0)
    "cap_languages": "TEXT",  # 도구 파라미터로 본 지원 언어
    "cap_regions": "TEXT",  # 도구 파라미터로 본 지원 나라·지역
    "cap_currencies": "TEXT",
    "cap_tool_count": "INTEGER",
    "cap_tool_names": "TEXT",
    "cap_checked_at": "REAL",
    "cap_error": "TEXT",
    # 인증 방법 (collector/auth_discovery.py)
    "auth_method": "TEXT",  # oauth2 | api_key | bearer | basic | none | unknown
    "auth_autonomy": "TEXT",  # agent_autonomous | human_once | none_needed | unknown
    "auth_info": "TEXT",  # JSON: OAuth 주소·지원 방식, API 키 헤더·발급처, 안내 단계
    "auth_checked_at": "REAL",
    "auth_error": "TEXT",
    "auth_scope": "TEXT",  # connection(연결부터 인증) | tool(연결은 되지만 도구 호출에 인증 필요)
    # 사용 안내 (collector/usage.py)
    "usage_tools": "TEXT",  # 정리된 도구 정의 JSON (변경 비교용)
    "usage_tools_hash": "TEXT",
    "usage_full_tools": "TEXT",
    "usage_full_hash": "TEXT",
    "usage_guide": "TEXT",  # 연결 방법·도구별 사용법·검증된 예제 JSON
    "usage_updated_at": "REAL",  # 도구 목록(사용법)이 처음 만들어졌거나 바뀐 시각
    "usage_changes": "TEXT",  # 마지막 변경 내역 JSON (추가·삭제·변경된 도구)
    "trial_info": "TEXT",  # 마지막 실제 호출 결과 JSON
    "trial_ok": "INTEGER",
    # 품질 평가 (collector/evaluation.py)
    "eval_score": "REAL",  # 0~100 (정적 평가만 있으면 NULL)
    "eval_grade": "TEXT",  # A~F
    "eval_security": "TEXT",  # ok | review | quarantine | unknown
    "eval_coverage": "TEXT",  # full | definitions | static
    "eval_info": "TEXT",  # 축별 점수·발견 사항 JSON
    "eval_at": "REAL",
}


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
NEEDS_COLUMNS = {"language": "TEXT", "region": "TEXT", "auth_pref": "TEXT",  # 요청 조건 (언어·지역·인증)
                 "min_grade": "TEXT",  # 요청 조건: 최소 품질 등급 (A~F)
                 "usage_seen_at": "REAL",  # 고객에게 사용법 변경을 마지막으로 알린 시각
                 "rescanned_at": "REAL"}  # 마지막 재평가 시각 (오래된 것부터 나눠서 재평가)
CRAWL_RUN_COLUMNS = {"mode": "TEXT", "changed": "INTEGER", "unchanged": "INTEGER", "pages": "INTEGER",
                     'registry_missing': 'INTEGER'}
HEALTH_UP = ("healthy", "reachable")

RESOURCE_COLS = [
    "id", "key", "source", "kind", "url", "name", "description", "category", "networks", "price_usdc", "pay_to",
    "method", "details", "calls_30d", "payers_30d", "last_called", "first_seen", "last_seen", "active",
    "probe_ok", "probe_fail", "probe_latency_ms", "probed_at",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


def _steps_to_graph(steps: list[dict], trigger_type: str = "manual") -> tuple[list[dict], list[dict]]:
    """Converts a sequential list of steps into an interactive DAG nodes and edges graph."""
    if not isinstance(steps, list):
        steps = []
    nodes = [
        {
            "id": "node-trigger-1",
            "type": "trigger",
            "name": f"Trigger ({trigger_type.capitalize()})",
            "kind": "trigger",
            "position": {"x": 60, "y": 180},
            "data": {"trigger_type": trigger_type}
        }
    ]
    edges = []
    prev_node_id = "node-trigger-1"

    for idx, s in enumerate(steps, 1):
        node_id = s.get("id") or f"node-agent-{idx}"
        kind = s.get("kind", "mcp")
        rid = s.get("resource_id")
        name = s.get("name", f"Step {idx}")
        x = 60 + idx * 280
        y = 180
        is_active = s.get("is_active", True)
        disabled = s.get("disabled", False)
        status = s.get("status", "active")
        suspend_reason = s.get("suspend_reason", "")
        category = s.get("category", "")
        nodes.append({
            "id": node_id,
            "type": "agent",
            "name": name,
            "kind": kind,
            "resource_id": rid,
            "position": s.get("position") or {"x": x, "y": y},
            "is_active": is_active,
            "disabled": disabled,
            "data": {
                "step": idx,
                "resource_id": rid,
                "name": name,
                "kind": kind,
                "category": category,
                "action": s.get("action", "execute"),
                "input": s.get("input", {}),
                "description": s.get("description", ""),
                "sample_output": s.get("sample_output", ""),
                "mock_output": s.get("mock_output", ""),
                "is_active": is_active,
                "disabled": disabled,
                "status": status,
                "suspend_reason": suspend_reason
            }
        })
        edges.append({
            "id": f"e-{prev_node_id}-{node_id}",
            "source": prev_node_id,
            "target": node_id
        })
        prev_node_id = node_id

    return nodes, edges


def _graph_to_steps(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Converts a nodes & edges DAG into a linear steps array for backwards compatibility."""
    if not isinstance(nodes, list):
        return []

    agent_nodes = [n for n in nodes if n.get("type") == "agent" or n.get("kind") in ("mcp", "a2a", "x402")]
    if not agent_nodes:
        agent_nodes = [n for n in nodes if n.get("type") != "trigger"]

    steps = []
    for idx, n in enumerate(agent_nodes, 1):
        ndata = n.get("data") or {}
        steps.append({
            "step": idx,
            "id": n.get("id"),
            "resource_id": n.get("resource_id") or ndata.get("resource_id"),
            "name": n.get("name") or ndata.get("name", f"Step {idx}"),
            "kind": n.get("kind") or ndata.get("kind", "mcp"),
            "category": ndata.get("category") or n.get("category", ""),
            "action": ndata.get("action", "execute"),
            "input": ndata.get("input", {}),
            "description": ndata.get("description", ""),
            "sample_output": ndata.get("sample_output") or n.get("sample_output", ""),
            "mock_output": ndata.get("mock_output") or n.get("mock_output", ""),
            "position": n.get("position"),
            "is_active": n.get("is_active", ndata.get("is_active", True)),
            "disabled": n.get("disabled", ndata.get("disabled", False)),
            "status": ndata.get("status", "active"),
            "suspend_reason": ndata.get("suspend_reason", "")
        })
    return steps


# Positions in Store._upsert values: registry activity figures and our own category.
_ACTIVITY = {'category', 'calls_30d', 'payers_30d', 'last_called'}
_UPSERT_FIELDS = ('source', 'kind', 'url', 'name', 'description', 'category', 'networks', 'price_usdc',
                  'pay_to', 'method', 'details', 'calls_30d', 'payers_30d', 'last_called')


def _same_details(old, new) -> bool:
    if old is not None and not isinstance(old, str):
        old = json.dumps(old, sort_keys=True)
    return old == new


def _activity_only(stored, values) -> bool:
    """True when VALUES differ from the stored row only in activity figures (or category)."""
    if stored is None:
        return False
    for field, value in zip(_UPSERT_FIELDS, values):
        if field in _ACTIVITY:
            continue
        old = stored[field]
        if field == 'details' and not isinstance(old, str) and old is not None:
            old = json.dumps(old, sort_keys=True)
        if field == 'price_usdc' and old is not None and value is not None:
            # Compare with what the column kept: the PostgreSQL column is BIGINT (0.01 is stored as 0).
            if type(old) is int:
                value = round(float(value))
            if not math.isclose(float(old), float(value), rel_tol=1e-9, abs_tol=1e-12):
                return False
            continue
        if old != value:
            return False
    return True


class Store:
    # Legacy tx/query borrowers remain unguarded until observation setup is explicit.
    _observation_context = None

    def __init__(self, path: str = ":memory:"):
        self._path = path
        private_sqlite_file(path)
        self._db = self._open_connection()
        from ..application_writer_fence import assert_sqlite_writer_allowed
        try:
            assert_sqlite_writer_allowed(self._db)
        except BaseException:
            self._db.close()
            raise
        self._lock = threading.RLock()
        self._observation_issuer = secrets.token_hex(16)
        self._observation_context = None
        self._observation_savepoint = 0
        self._observation_broken = False
        with self._db:
            from ..capability_registry import SCHEMA as CONNECTION_SCHEMA
            from ..execution_authority import SCHEMA as AUTHORITY_SCHEMA
            self._db.executescript(SCHEMA + CONNECTION_SCHEMA + AUTHORITY_SCHEMA)
            init_admin_auth_db(self._db)
            existing = {r[1] for r in self._db.execute("PRAGMA table_info(resources)")}
            for col, decl in HEALTH_COLUMNS.items():
                if col not in existing:
                    self._db.execute(f"ALTER TABLE resources ADD COLUMN {col} {decl}")
            from ..managed_catalog import ensure_schema
            ensure_schema(self._db)
            from ..capability_registry import INVALIDATION
            self._db.executescript(INVALIDATION)
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_due ON resources(active, next_check_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_public_metrics ON resources(active,kind,health_status,last_check_at,first_seen)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_public_categories ON resources(active,kind,category)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_resources_kind_due ON resources(active, kind, health_status, next_check_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_host_due ON resources(host, next_check_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_eval_score ON resources(eval_score)")
            # SNS 피드: 최근 발견·평가·사용법 변경·시험 호출을 시간순으로 빨리 찾기 위해
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_first_seen ON resources(first_seen, kind)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_eval_at ON resources(eval_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_usage_updated ON resources(usage_updated_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_trial_at ON resources(json_extract(trial_info, '$.at'))")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_resources_status_kind ON resources(active, health_status, kind, first_seen)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_resources_cat_active ON resources(active, health_status, category, kind, first_seen)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_resources_verified_first_seen ON resources(active, health_status, trial_ok, kind, first_seen)")
            missing = self._db.execute("SELECT id, url FROM resources WHERE host IS NULL").fetchall()
            if missing:  # 기존 DB: 호스트 채우기
                self._db.executemany("UPDATE resources SET host=? WHERE id=?", [(host_of(r["url"]), r["id"]) for r in missing])
            self._reclassify_if_needed()
            self._backfill_constraints_if_needed()
            self._backfill_fts_tools_if_needed()
            self._backfill_trial_ok_if_needed()
            self._sync_fts_if_needed()
            need_cols = {r[1] for r in self._db.execute("PRAGMA table_info(needs)")}
            for col, decl in NEEDS_COLUMNS.items():
                if col not in need_cols:
                    self._db.execute(f"ALTER TABLE needs ADD COLUMN {col} {decl}")
            self._db.execute("CREATE INDEX IF NOT EXISTS needs_rescan ON needs(status, rescanned_at)")
            ctx_cols = {r[1] for r in self._db.execute("PRAGMA table_info(agent_contexts)")}
            if "issued" not in ctx_cols:  # 기존 DB: 가로채기 방지 이전에 기록된 contextId는 더 이상 그것만으로 신뢰하지 않음
                self._db.execute("ALTER TABLE agent_contexts ADD COLUMN fingerprint TEXT")
                self._db.execute("ALTER TABLE agent_contexts ADD COLUMN issued INTEGER NOT NULL DEFAULT 0")
            if "hint" not in {r[1] for r in self._db.execute("PRAGMA table_info(agent_interests)")}:  # 기존 DB
                self._db.execute("ALTER TABLE agent_interests ADD COLUMN hint TEXT")
            runs = {r[1] for r in self._db.execute("PRAGMA table_info(crawl_runs)")}
            for col, decl in CRAWL_RUN_COLUMNS.items():
                if col not in runs:
                    self._db.execute(f"ALTER TABLE crawl_runs ADD COLUMN {col} {decl}")
            from ..admin_query_indexes import ensure as ensure_admin_indexes
            ensure_admin_indexes(self._db)
            vis_cols = {r[1] for r in self._db.execute("PRAGMA table_info(agent_visitors)")}
            watch_cols = {r[1] for r in self._db.execute('PRAGMA table_info(agent_task_watches)')}
            if 'last_checked' not in watch_cols:
                self._db.execute('ALTER TABLE agent_task_watches ADD COLUMN last_checked REAL NOT NULL DEFAULT 0')
            if 'verified_at' not in watch_cols:
                self._db.execute('ALTER TABLE agent_task_watches ADD COLUMN verified_at REAL')
            if "last_tool_resource" not in vis_cols:
                self._db.execute("ALTER TABLE agent_visitors ADD COLUMN last_tool_resource INTEGER")
                self._db.execute("ALTER TABLE agent_visitors ADD COLUMN last_tool_name TEXT")
            if "nurture_stage" not in vis_cols:
                self._db.execute("ALTER TABLE agent_visitors ADD COLUMN nurture_stage TEXT DEFAULT 'onboarded'")
            if "last_nurture_at" not in vis_cols:
                self._db.execute("ALTER TABLE agent_visitors ADD COLUMN last_nurture_at REAL")
            self._db.execute("""CREATE TABLE IF NOT EXISTS tool_inertia (
                from_resource_id INTEGER NOT NULL,
                from_tool TEXT NOT NULL,
                to_resource_id INTEGER NOT NULL,
                to_tool TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                last_transition REAL NOT NULL,
                PRIMARY KEY (from_resource_id, from_tool, to_resource_id, to_tool)
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS tool_inertia_from ON tool_inertia (from_resource_id, from_tool, count DESC)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS agent_credits (
                account_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                held INTEGER NOT NULL DEFAULT 0,
                total_deposited INTEGER NOT NULL DEFAULT 0,
                total_spent INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS clearing_ledger (
                tx_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                resource_id INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                sla_verified INTEGER NOT NULL DEFAULT 0,
                receipt TEXT,
                created_at REAL NOT NULL,
                settled_at REAL
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS clearing_ledger_acc ON clearing_ledger (account_id, created_at)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS vec_outbox (
                resource_id INTEGER PRIMARY KEY,
                enqueued_at REAL NOT NULL,
                reason TEXT NOT NULL
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS vec_outbox_time ON vec_outbox(enqueued_at)")
            self._db.execute("""CREATE TABLE IF NOT EXISTS agent_test_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id INTEGER,
                title TEXT NOT NULL,
                slug TEXT UNIQUE,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                agent_url TEXT NOT NULL,
                category TEXT NOT NULL,
                eval_grade TEXT,
                eval_score REAL,
                status_code INTEGER,
                latency_ms REAL,
                is_success INTEGER NOT NULL DEFAULT 1,
                test_method TEXT NOT NULL,
                tool_name TEXT,
                input_wire TEXT,
                output_wire TEXT,
                summary TEXT NOT NULL,
                content_md TEXT NOT NULL,
                pros TEXT NOT NULL,
                cons TEXT NOT NULL,
                workflow_recommendation TEXT,
                tags TEXT,
                author TEXT NOT NULL DEFAULT 'AI Verification Agent',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_agent_test_reports_res ON agent_test_reports(resource_id, created_at DESC)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_agent_test_reports_kind ON agent_test_reports(kind, created_at DESC)")
            report_columns={r[1] for r in self._db.execute('PRAGMA table_info(agent_test_reports)')}
            for column,declaration in {'executed_at':'REAL','execution_finished_at':'REAL','connection_version_id':'TEXT','evidence_scope':'TEXT'}.items():
                if column not in report_columns:self._db.execute(f'ALTER TABLE agent_test_reports ADD COLUMN {column} {declaration}')
            if 'creation_subject_key' not in report_columns:
                self._db.execute('ALTER TABLE agent_test_reports ADD COLUMN creation_subject_key TEXT')
            self._db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_report_creation_subject ON agent_test_reports(creation_subject_key)')
            from ..report_creation import install_sqlite_guard
            install_sqlite_guard(self._db)
            from ..concierge.report_evidence import install_report_identity_guards
            install_report_identity_guards(self._db)
            self._db.execute("""CREATE TABLE IF NOT EXISTS agent_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                steps TEXT NOT NULL,
                tags TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_template INTEGER NOT NULL DEFAULT 0,
                author TEXT NOT NULL DEFAULT 'Admin',
                author_wallet TEXT DEFAULT '',
                parent_workflow_id INTEGER,
                forks_count INTEGER NOT NULL DEFAULT 0,
                likes_count INTEGER NOT NULL DEFAULT 0,
                runs_count INTEGER NOT NULL DEFAULT 0,
                rating_avg REAL NOT NULL DEFAULT 5.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            wf_cols = {r[1] for r in self._db.execute("PRAGMA table_info(agent_workflows)")}
            workflow_extra_cols = {
                "is_template": "INTEGER NOT NULL DEFAULT 0",
                "author": "TEXT NOT NULL DEFAULT 'Admin'",
                "author_wallet": "TEXT DEFAULT ''",
                "parent_workflow_id": "INTEGER",
                "forks_count": "INTEGER NOT NULL DEFAULT 0",
                "likes_count": "INTEGER NOT NULL DEFAULT 0",
                "runs_count": "INTEGER NOT NULL DEFAULT 0",
                "rating_avg": "REAL NOT NULL DEFAULT 5.0",
            }
            for col, decl in workflow_extra_cols.items():
                if col not in wf_cols:
                    self._db.execute(f"ALTER TABLE agent_workflows ADD COLUMN {col} {decl}")

            self._db.execute("CREATE INDEX IF NOT EXISTS idx_agent_workflows_tmpl ON agent_workflows(is_template, category, rating_avg DESC)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_agent_workflows_author ON agent_workflows(author, updated_at DESC)")

            self._db.execute("""CREATE TABLE IF NOT EXISTS platform_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_name TEXT NOT NULL UNIQUE,
                key_value TEXT NOT NULL,
                provider TEXT NOT NULL,
                description TEXT,
                updated_at REAL NOT NULL
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS workflow_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                reviewer TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at REAL NOT NULL
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_workflow_reviews_wfid ON workflow_reviews(workflow_id, created_at DESC)")

            vector_ready = ensure_vec_table(self._db)
            self.seed_default_workflows()
            self._migrate_credentials()
            self._init_observation_guards()
            if vector_ready:
                install_vector_index(self._db)
        from ..catalog_query_indexes import ensure_front_query_indexes
        ensure_front_query_indexes(self._db)
        self._vector_index = register_vector_index(self._db, self._lock) if vector_ready else None

    def _init_observation_guards(self):
        """Keep private fences outside public resource projections, including ABA changes."""
        db = self._db
        db.execute('''CREATE TABLE IF NOT EXISTS resource_observation_generations (
            resource_id INTEGER PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>0))''')
        db.execute('''CREATE TABLE IF NOT EXISTS resource_observation_owners (
            resource_id INTEGER NOT NULL, owner TEXT NOT NULL,
            issued_sequence INTEGER NOT NULL DEFAULT 0, applied_sequence INTEGER NOT NULL DEFAULT 0,
            observed_at REAL, PRIMARY KEY(resource_id,owner))''')
        db.execute('''INSERT OR IGNORE INTO resource_observation_generations
            SELECT id,1 FROM resources''')
        # These identifiers come exclusively from the local, immutable field allowlist.
        fields = tuple(dict.fromkeys(OBSERVATION_FIELDS + (
            'cap_checked_at', 'cap_error', 'auth_checked_at', 'health_status', 'trial_info', 'trial_ok')))
        columns = ','.join(fields)
        changed = ' OR '.join('OLD.' + f + ' IS NOT NEW.' + f for f in fields)
        db.execute('''CREATE TRIGGER IF NOT EXISTS resource_observation_insert
            AFTER INSERT ON resources BEGIN
            INSERT INTO resource_observation_generations VALUES(NEW.id,1)
            ON CONFLICT(resource_id) DO UPDATE SET generation=generation+1;
            DELETE FROM resource_observation_owners WHERE resource_id=NEW.id; END''')
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS resource_observation_change
            AFTER UPDATE OF {columns} ON resources WHEN {changed} BEGIN
            UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=NEW.id;
            DELETE FROM capability_eligibility WHERE resource_id=NEW.id; END''')

    def _observation_time(self, supplied=None):
        with self._lock:
            context = self._observation_context
            if context is None:
                return time.time() if supplied is None else supplied
            token, admitted_at = context
            now = time.time()
            if now < admitted_at or now < self._observation_latest_at:
                raise GuardError('stale_observation')
            if supplied is not None and (type(supplied) not in (int, float) or not math.isfinite(supplied)
                                         or not token.started_at <= supplied <= now):
                raise GuardError('stale_observation')
            self._observation_latest_at = now
            return now if supplied is None else supplied

    def _supersede_observation(self, db, rid, owner, at):
        """Supported legacy writes invalidate older tracked work without changing signatures."""
        context = self._observation_context
        if context is not None:
            token, _ = context
            if rid != token.resource_id:
                raise GuardError('invalid_token')
            if owner == token.owner:
                return
        if db.execute('SELECT 1 FROM resources WHERE id=?', (rid,)).fetchone() is None:
            return
        db.execute('''INSERT INTO resource_observation_owners
            (resource_id,owner,issued_sequence,applied_sequence,observed_at) VALUES(?,?,1,1,?)
            ON CONFLICT(resource_id,owner) DO UPDATE SET
            issued_sequence=issued_sequence+1,applied_sequence=issued_sequence+1,
            observed_at=MAX(COALESCE(observed_at,0),excluded.observed_at)''', (rid, owner, at))
        from ..agent_access.storage import enqueue
        if owner!='health':enqueue(self,db,rid,'catalog_changed',evidence=[owner,at])

    def _invalidate_survey_evaluation(self, db, rid):
        # Even a repeated failed survey is a new dependency boundary for an older evaluation.
        db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=?', (rid,))
        db.execute('UPDATE resources SET eval_at=NULL WHERE id=?', (rid,))
        db.execute('DELETE FROM capability_eligibility WHERE resource_id=?', (rid,))

    def observation_guard(self, rid, owner, *, expected_resource):
        """Reserve a single-use, process-local ticket before external work on this snapshot."""
        if type(rid) is not int or rid <= 0 or owner not in OBSERVATION_OWNERS:
            raise GuardError('invalid_token')
        expected = fingerprint(expected_resource)
        with self._lock:
            if self._observation_broken or self._observation_context is not None or self._db.in_transaction:
                raise GuardError('invalid_token')
            try:
                self._db.execute('BEGIN IMMEDIATE')
                row = self._db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone()
                if row is None or row['id'] != expected_resource['id'] or fingerprint(dict(row)) != expected:
                    raise GuardError('stale_generation')
                generation = self._db.execute('SELECT generation FROM resource_observation_generations WHERE resource_id=?', (rid,)).fetchone()[0]
                self._db.execute('''INSERT INTO resource_observation_owners(resource_id,owner,issued_sequence)
                    VALUES(?,?,1) ON CONFLICT(resource_id,owner) DO UPDATE SET issued_sequence=issued_sequence+1''', (rid, owner))
                sequence = self._db.execute('SELECT issued_sequence FROM resource_observation_owners WHERE resource_id=? AND owner=?', (rid, owner)).fetchone()[0]
                token = issue(dict(row), owner=owner, generation=generation, sequence=sequence,
                              started_at=time.time(), issuer=self._observation_issuer)
                self._db.commit()
                return token
            except BaseException:
                self._db.rollback()
                raise

    @contextmanager
    def observation_transaction(self, token):
        """Validate once under the native writer lock, then commit the complete result bundle."""
        with self._lock:
            if (type(token) is not ObservationToken or self._observation_broken
                    or self._observation_context is not None or self._db.in_transaction):
                raise GuardError('invalid_token')
            try:
                self._db.execute('BEGIN IMMEDIATE')
                row = self._db.execute('SELECT * FROM resources WHERE id=?', (token.resource_id,)).fetchone()
                generation = self._db.execute('SELECT generation FROM resource_observation_generations WHERE resource_id=?', (token.resource_id,)).fetchone()
                state = self._db.execute('SELECT * FROM resource_observation_owners WHERE resource_id=? AND owner=?', (token.resource_id, token.owner)).fetchone()
                if row is None or generation is None or state is None:
                    raise GuardError('stale_generation')
                now = time.time()
                validate(token, dict(row), generation=generation[0], sequence=state['issued_sequence'],
                         applied_sequence=state['applied_sequence'], previous_observed_at=state['observed_at'],
                         observed_at=now, issuer=self._observation_issuer)
                self._observation_context = (token, now)
                self._observation_latest_at = now
                self._observation_failed = False
                yield
                if self._observation_failed:
                    raise sqlite3.DatabaseError('Observation transaction failed.')
                finished = self._observation_time()
                self._db.execute('''UPDATE resource_observation_owners SET applied_sequence=?,observed_at=?
                    WHERE resource_id=? AND owner=?''', (token.sequence, finished, token.resource_id, token.owner))
                try:
                    self._db.commit()
                except BaseException:
                    # A commit error must never lead to automatic replay on this Store handle.
                    self._observation_broken = True
                    raise
            except BaseException:
                self._db.rollback()
                raise
            finally:
                self._observation_context = None

    @staticmethod
    def _text_constraints(kind: str, name: str, description: str, details: dict | str | None) -> tuple:
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = {}
        details = details or {}
        text = f"{name} {description}"
        if kind == "mcp":
            auth = cons.declared_auth(details.get("remotes"))
        elif kind == "x402":
            auth = False  # 결제는 필요하지만 계정·API 키는 필요 없음
        else:
            auth = None
        return cons.detect_language(text), cons.pack(cons.regions_in_text(text)), None if auth is None else int(auth)

    def _backfill_constraints_if_needed(self) -> None:
        row = self._db.execute("SELECT value FROM meta WHERE key='constraints_version'").fetchone()
        if row and json.loads(row["value"]) == CONSTRAINTS_VERSION:
            return
        rows = self._db.execute("SELECT id, kind, name, description, details FROM resources").fetchall()
        self._db.executemany(
            "UPDATE resources SET desc_lang=?, regions=?, auth_declared=? WHERE id=?",
            [(*self._text_constraints(r["kind"], r["name"], r["description"], r["details"]), r["id"]) for r in rows],
        )
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('constraints_version', ?)", (json.dumps(CONSTRAINTS_VERSION),))

    def _backfill_fts_tools_if_needed(self) -> None:
        """기존 DB에 저장된 에이전트들의 도구/스킬 목록을 FTS5 전문 검색 색인에 반영한다 (1회)."""
        row = self._db.execute("SELECT value FROM meta WHERE key='fts_tools_version'").fetchone()
        if row and json.loads(row["value"]) == FTS_TOOLS_VERSION:
            return
        rows = self._db.execute("SELECT id, name, description, usage_tools FROM resources WHERE usage_tools IS NOT NULL").fetchall()
        for r in rows:
            tool_text = extract_tool_search_text(r["usage_tools"])
            full_desc = f"{r['description']}\n{tool_text}".strip()
            self._db.execute("DELETE FROM resources_fts WHERE rowid=?", (r["id"],))
            self._db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (r["id"], r["name"], full_desc))
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('fts_tools_version', ?)", (json.dumps(FTS_TOOLS_VERSION),))

    def _backfill_trial_ok_if_needed(self) -> None:
        """기존 DB의 정상(healthy) 상태 에이전트들에 대해 trial_ok 검증 상태를 1회 마이그레이션한다."""
        row = self._db.execute("SELECT value FROM meta WHERE key='trial_ok_backfill_version'").fetchone()
        if row and json.loads(row["value"]) == 1:
            return
        self._db.execute(
            """UPDATE resources SET trial_ok = 1
               WHERE trial_ok IS NULL AND health_status = 'healthy'
               AND (last_status_code IN (200, 402) OR last_ok_at IS NOT NULL OR kind IN ('a2a', 'mcp'))"""
        )
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('trial_ok_backfill_version', '1')")

    def _sync_fts_if_needed(self) -> None:
        """resources 테이블과 resources_fts 가상 테이블 간의 정합성을 검사하고 불일치를 해소한다.
        - resources에 없는 고아 FTS 행 삭제 (과거 비정상 종료, 수동 삭제, 복구 등으로 남은 경우 방어)
        - resources에는 있으나 resources_fts에 누락된 행 자동 복구
        """
        orphans = [r[0] for r in self._db.execute(
            "SELECT rowid FROM resources_fts WHERE rowid NOT IN (SELECT id FROM resources)"
        ).fetchall()]
        if orphans:
            placeholders = ",".join("?" * len(orphans))
            self._db.execute(f"DELETE FROM resources_fts WHERE rowid IN ({placeholders})", orphans)
        missing = self._db.execute(
            "SELECT id, name, description FROM resources WHERE id NOT IN (SELECT rowid FROM resources_fts)"
        ).fetchall()
        for r in missing:
            self._db.execute(
                "INSERT OR REPLACE INTO resources_fts(rowid, name, description) VALUES (?,?,?)",
                (r["id"], r["name"], r["description"]),
            )

    def _reclassify_if_needed(self) -> None:
        """분류 기준(카테고리·키워드)이 바뀌었으면 저장된 에이전트를 다시 분류한다 (한 번만)."""
        row = self._db.execute("SELECT value FROM meta WHERE key='classifier_version'").fetchone()
        if row and json.loads(row["value"]) == CLASSIFIER_VERSION:
            return
        rows = self._db.execute("SELECT id, source, kind, name, description, category, usage_tools FROM resources").fetchall()
        updates = []
        if rows:
            log.info("Refreshing catalog categories for %d resources", len(rows))
        for position, r in enumerate(rows, 1):
            if r["source"] == "registered":  # 직접 등록한 에이전트는 자기가 밝힌 카테고리를 유지 (예전 ID만 변환)
                new = LEGACY_ALIASES.get(r["category"], r["category"])
            else:
                new = classify_listing(f"{r['name']} {r['description']}", extract_tool_search_text(r["usage_tools"]))
            if new != r["category"]:
                updates.append((new, r["id"]))
            if position % 10000 == 0:
                log.info("Catalog category refresh progress: %d/%d", position, len(rows))
        self._db.executemany("UPDATE resources SET category=? WHERE id=?", updates)
        if updates:
            now_ts = time.time()
            self._db.executemany("INSERT OR REPLACE INTO vec_outbox (resource_id, enqueued_at, reason) VALUES (?, ?, 'reclassified')",
                                 [(rid, now_ts) for _, rid in updates])
        for old, new in LEGACY_ALIASES.items():
            self._db.execute("UPDATE needs SET category=? WHERE category=?", (new, old))
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('classifier_version', ?)", (json.dumps(CLASSIFIER_VERSION),))
        if rows:
            log.info("Catalog category refresh complete: %d checked, %d changed", len(rows), len(updates))

    def _open_connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=30.0, check_same_thread=False)
        db.row_factory = sqlite3.Row
        # Existing resource triggers may access vec0 during startup migrations.
        load_sqlite_vec(db)
        if self._path != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA busy_timeout=10000")
        return db

    def _reconnect(self) -> None:
        if self._path == ":memory:":
            return
        # An uncertain vector commit requires explicit fresh inspection, not replay.
        index = getattr(self, '_vector_index', None)
        if index is not None and index.broken:
            raise sqlite3.DatabaseError('vector_commit_unknown')
        try:
            self._db.close()
        except Exception:
            pass
        self._db = self._open_connection()
        vector_ready = ensure_vec_table(self._db)
        if vector_ready:
            with self._db:
                install_vector_index(self._db)
        self._vector_index = register_vector_index(self._db, self._lock) if vector_ready else None

    @contextmanager
    def tx(self):
        from ..application_writer_fence import assert_sqlite_writer_allowed
        with self._lock:
            assert_sqlite_writer_allowed(self._db)
            if self._observation_context is not None:
                self._observation_savepoint += 1
                name = 'observation_' + str(self._observation_savepoint)
                self._db.execute('SAVEPOINT ' + name)
                try:
                    yield self._db
                    self._db.execute('RELEASE SAVEPOINT ' + name)
                except BaseException:
                    self._observation_failed = True
                    self._db.execute('ROLLBACK TO SAVEPOINT ' + name)
                    self._db.execute('RELEASE SAVEPOINT ' + name)
                    raise
                return
            try:
                with self._db:
                    yield self._db
            except sqlite3.DatabaseError as exc:
                if self._observation_context is not None:
                    self._observation_failed = True
                if self._observation_context is None and self._path != ":memory:" and "malformed" in str(exc).lower():
                    log.warning("SQLite DatabaseError in tx (%s); reconnecting %s", exc, self._path)
                    self._reconnect()
                raise

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return self._db.execute(sql, params).fetchall()
            except sqlite3.DatabaseError as exc:
                if self._observation_context is not None:
                    self._observation_failed = True
                if self._observation_context is None and self._path != ":memory:" and "malformed" in str(exc).lower():
                    log.warning("SQLite DatabaseError in query (%s); reconnecting %s", exc, self._path)
                    self._reconnect()
                    return self._db.execute(sql, params).fetchall()
                raise

    # ---------------- resources ----------------
    def upsert_resource(self, r: dict, now: float | None = None) -> int:
        """r: key, source, kind, url, name, description, category, networks(list), price_usdc, pay_to, method,
        details(dict), calls_30d, payers_30d, last_called"""
        with self.tx() as db:
            return self._upsert(db, r, now or time.time())[1]

    def upsert_page(self, records: list[dict], now: float | None = None) -> dict:
        """수집한 한 페이지를 한 트랜잭션으로 반영. {"new": n, "changed": n, "unchanged": n}"""
        now = now or time.time()
        counts = {"new": 0, "changed": 0, "unchanged": 0}
        with self.tx() as db:
            for r in records:
                counts[self._upsert(db, r, now)[0]] += 1
        return counts

    def _upsert(self, db, r: dict, now: float, *, registry_observed: bool = True) -> tuple[str, int]:
        r = dict(r)
        for field in ('name','description'):
            r[field] = r[field].replace('\0','')
        networks = "," + ",".join(sorted(set(r.get("networks") or []))) + ","
        values = (
            r["source"], r["kind"], r["url"], r["name"][:200], r["description"][:2000], r["category"], networks,
            r.get("price_usdc"), ((r.get("pay_to") or "").lower() if (r.get("pay_to") or "").lower().startswith('0x')
                                 else (r.get("pay_to") or None)), r.get("method"),
            json.dumps(r.get("details") or {}, sort_keys=True), r.get("calls_30d"), r.get("payers_30d"), r.get("last_called"),
        )
        digest = hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()
        lang, regions, auth = self._text_constraints(r["kind"], r["name"], r["description"], r.get("details"))
        row = db.execute("SELECT id, name, description, url, content_hash FROM resources WHERE key=?", (r["key"],)).fetchone()
        if row is None:
            cur = db.execute(
                """INSERT INTO resources (source, kind, url, name, description, category, networks, price_usdc, pay_to,
                   method, details, calls_30d, payers_30d, last_called, key, first_seen, last_seen, active, content_hash, host,
                   desc_lang, regions, auth_declared)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                (*values, r["key"], now, now, digest, host_of(r["url"]), lang, regions, auth),
            )
            rid = cur.lastrowid
            db.execute("INSERT OR REPLACE INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
            db.execute("INSERT OR REPLACE INTO vec_outbox(resource_id, enqueued_at, reason) VALUES (?, ?, 'new')", (rid, now))
            return "new", rid
        rid = row["id"]
        seen_at = now
        if registry_observed:
            db.execute('UPDATE resources SET registry_missing_since=NULL WHERE id=? AND registry_missing_since IS NOT NULL', (rid,))
        else:
            seen_at = db.execute('SELECT last_seen FROM resources WHERE id=?', (rid,)).fetchone()[0]
        if row["content_hash"] == digest:  # 바뀐 게 없으면 확인 시각만 갱신
            db.execute("UPDATE resources SET last_seen=? WHERE id=?", (seen_at, rid))
            return "unchanged", rid
        stored = db.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
        if (registry_observed and r["kind"] == "x402" and stored is not None and _same_details(stored["details"], values[10])
                and stored["price_usdc"] and values[7]):  # positive quote over a positive listing only
            # Same registry entry: keep the price and payee from the provider's own 402 quote. The
            # bazaar's listed amount and the live quote took turns overwriting each other, which
            # re-embedded 309 listings ~1.5 times a day and showed a different price each time (2026-11-10).
            values = values[:7] + (stored["price_usdc"], stored["pay_to"]) + values[9:]
            digest = hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()
            if row["content_hash"] == digest:
                db.execute("UPDATE resources SET last_seen=? WHERE id=?", (seen_at, rid))
                return "unchanged", rid
        if row["name"] == r["name"][:200] and row["description"] == r["description"][:2000]:
            # Same text: keep the category the collectors set from richer evidence (agent card,
            # tools). The A2A registry changes updated_at about every 30 minutes, and rewriting
            # its own label each time flipped 629 listings back and forth and re-embedded them
            # (2026-11-09, 49k embeddings a day).
            if stored is not None and stored["category"] in CATEGORIES and stored["category"] != OTHER_CATEGORY:
                values = values[:5] + (stored["category"],) + values[6:]
        db.execute(
            """UPDATE resources SET source=?, kind=?, url=?, name=?, description=?, category=?, networks=?,
               price_usdc=?, pay_to=?, method=?, details=?, calls_30d=?, payers_30d=?, last_called=?,
               last_seen=?, content_hash=?, host=?, desc_lang=?, regions=?, auth_declared=? WHERE id=?""",
            (*values, seen_at, digest, host_of(r["url"]), lang, regions, auth, rid),
        )
        # Only the registry's activity figures (updated_at, call counts) changed: the listing is the
        # same, so its capability check and evaluation stay (A2A registry: every ~30 minutes).
        if r["kind"] in ("mcp", "a2a") and not _activity_only(stored, values):  # 레지스트리 항목(버전·저장소 등)이 바뀌면 기능 조사·품질 평가를 다시
            db.execute("UPDATE resources SET cap_checked_at=NULL, eval_at=NULL WHERE id=?", (rid,))
        if row["url"] != r["url"]:  # 주소가 바뀌면 헬스 상태를 새로 시작 (제외됐던 에이전트도 다시 점검)
            db.execute(
                """UPDATE resources SET health_status='unknown', consecutive_failures=0, failing_since=NULL,
                   next_check_at=NULL, health_ok_24h=0, health_n_24h=0 WHERE id=?""", (rid,))
        # Metadata updates cannot clear locally established health/retirement.
        if row["name"] != r["name"][:200] or row["description"] != r["description"][:2000]:
            db.execute("DELETE FROM resources_fts WHERE rowid=?", (rid,))
            db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
            db.execute("INSERT OR REPLACE INTO vec_outbox(resource_id, enqueued_at, reason) VALUES (?, ?, 'changed')", (rid, now))
        return "changed", rid

    def deactivate_unseen(self, source: str, before: float) -> int:
        """Compatibility entry: discovery absence never deactivates local agents."""
        self.mark_registry_unseen(source, before)
        return 0

    def mark_registry_unseen(self, source: str, before: float) -> int:
        from ..managed_catalog import mark_missing
        with self.tx() as db:
            return mark_missing(db, source, before)

    def resource(self, rid: int) -> dict | None:
        rows = self.query("SELECT * FROM resources WHERE id=?", (rid,))
        return dict(rows[0]) if rows else None

    def record_probe(self, rid: int, ok: bool, latency_ms: int | None) -> None:
        col = "probe_ok" if ok else "probe_fail"
        with self.tx() as db:
            db.execute(f"UPDATE resources SET {col}={col}+1, probe_latency_ms=?, probed_at=? WHERE id=?", (latency_ms, time.time(), rid))

    def search(self, text: str, category: str, max_price: int | None, networks: list[str], kinds: list[str], limit: int = 200,
               region: str | None = None, auth_free: bool = False, agent_usable: bool = False,
               min_grade: str | None = None, rag_engine=None) -> list[dict]:
        """FTS로 관련 후보를 뽑고, 부족하면 같은 카테고리 인기순으로 채운다.
        rag_engine이 주어지면 sqlite-vec 밀집 벡터 하이브리드 검색 결과도 후보군에 병합한다.

        region: 다른 나라·지역 전용 데이터를 다루는 에이전트는 뺀다 (지역 표시가 없는 전 세계 공통 에이전트는 남김).
        auth_free: 계정·API 키가 필요한 것으로 확인된 에이전트는 뺀다 (모르는 것은 남김).
        agent_usable: 사람 없이 에이전트 혼자 쓸 수 있는 것만 (인증 불필요 또는 OAuth client_credentials + 자동 등록).
        min_grade: 품질 평가 등급이 이 이상인 것만 (평가가 없는 x402 등은 남김). 보안 격리된 서버는 항상 뺀다.
        """
        terms = query_terms(text)
        conds = ["r.active=1", "r.health_status NOT IN ('down','retired')", f"r.kind IN ({','.join('?' * len(kinds))})",
                 "COALESCE(r.eval_security, '') != 'quarantine'"]
        params: list = list(kinds)
        if min_grade and min_grade.upper() in "ABCDF":
            allowed = "ABCDF"[:"ABCDF".index(min_grade.upper()) + 1]
            conds.append(f"(r.eval_grade IS NULL OR r.eval_grade IN ({','.join('?' * len(allowed))}))")
            params += list(allowed)
        if region:
            conds.append("((r.regions IS NULL AND r.cap_regions IS NULL) OR r.regions LIKE ? OR r.cap_regions LIKE ?)")
            params += [f"%,{region},%"] * 2
        if auth_free:
            conds.append("COALESCE(r.auth_observed, r.auth_declared, 0) = 0")
        if agent_usable:
            conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0) = 0 OR r.auth_autonomy = 'agent_autonomous')")
        if max_price is not None:
            conds.append("(r.price_usdc IS NOT NULL AND r.price_usdc <= ?)")
            params.append(max_price)
        if networks:
            conds.append("(r.kind != 'x402' OR " + " OR ".join("r.networks LIKE ?" for _ in networks) + ")")
            params += [f"%,{n},%" for n in networks]
        where = " AND ".join(conds)
        found: dict[int, dict] = {}
        if terms:
            match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
            for row in self.query(
                f"""SELECT r.* FROM resources_fts f JOIN resources r ON r.id=f.rowid
                    WHERE resources_fts MATCH ? AND {where} ORDER BY bm25(resources_fts) LIMIT ?""",
                (match, *params, limit),
            ):
                found[row["id"]] = dict(row)
        if rag_engine is not None and text:
            try:
                def load_rows(db, ranked_items):
                    # Runs inside the engine's read snapshot, after embedding.
                    ids = [item['id'] for item in ranked_items if item['id'] not in found]
                    if not ids:
                        return []
                    return [dict(row) for row in db.execute(
                        f"SELECT r.* FROM resources r WHERE r.id IN ({','.join('?' * len(ids))}) AND {where}",
                        (*ids, *params),
                    ).fetchall()]

                h_items = rag_engine.hybrid_search(
                    self._db, text, limit=min(limit, 50),
                    kind=kinds[0] if len(kinds) == 1 else None, _store_filter=load_rows,
                )
                for row in h_items:
                    found.setdefault(row['id'], row)
            except Exception as exc:
                log.warning("hybrid search in store.search failed: %r", exc)
        if len(found) < limit:
            for row in self.query(
                f"SELECT r.* FROM resources r WHERE r.category=? AND {where} ORDER BY COALESCE(r.payers_30d,0) DESC LIMIT ?",
                (category, *params, limit - len(found)),
            ):
                found.setdefault(row["id"], dict(row))
        return list(found.values())

    def idf(self, terms: list[str]) -> dict[str, float]:
        if not terms:
            return {}
        n = self.query("SELECT COUNT(*) AS n FROM resources_fts")[0]["n"] or 1
        rows = self.query(f"SELECT term, doc FROM resources_vocab WHERE term IN ({','.join('?' * len(terms))})", terms)
        docs = {r["term"]: r["doc"] for r in rows}
        return {t: math.log((n + 1) / (docs.get(t, 0) + 1)) + 1 for t in terms}

    def feedback_stats(self, rid: int) -> tuple[int, int, float | None]:
        row = self.query("SELECT COUNT(*) AS n, COALESCE(SUM(success),0) AS s, AVG(rating) AS r FROM feedback WHERE resource_id=?", (rid,))[0]
        return row["n"], row["s"], row["r"]

    def feedback_stats_many(self, rids: list[int]) -> dict[int, tuple[int, int, float | None]]:
        """여러 후보의 고객 평가를 한 번에 (후보마다 쿼리하지 않게). 평가가 없는 후보는 결과에 없다."""
        if not rids:
            return {}
        rows = self.query(f"""SELECT resource_id, COUNT(*) AS n, COALESCE(SUM(success),0) AS s, AVG(rating) AS r FROM feedback
                              WHERE resource_id IN ({','.join('?' * len(rids))}) GROUP BY resource_id""", list(rids))
        return {r["resource_id"]: (r["n"], r["s"], r["r"]) for r in rows}

    def record_tool_transition(self, from_rid: int, from_tool: str, to_rid: int, to_tool: str) -> None:
        """도구 호출 전이(Transition) 기록. AutoTool 관성 그래프 학습."""
        if from_rid == to_rid and from_tool == to_tool:
            return  # 동일 도구 연속 재시도는 전이로 기록하지 않음
        now = time.time()
        with self.tx() as db:
            db.execute("""INSERT INTO tool_inertia (from_resource_id, from_tool, to_resource_id, to_tool, count, last_transition)
                          VALUES (?, ?, ?, ?, 1, ?)
                          ON CONFLICT(from_resource_id, from_tool, to_resource_id, to_tool)
                          DO UPDATE SET count=count+1, last_transition=excluded.last_transition""",
                       (from_rid, from_tool, to_rid, to_tool, now))

    def get_tool_transitions(self, from_rid: int, from_tool: str, limit: int = 3) -> list[dict]:
        """도구 호출 후 다음으로 많이 호출된 도구 목록과 전이 확률 계산."""
        rows = self.query("""SELECT to_resource_id, to_tool, count FROM tool_inertia
                             WHERE from_resource_id=? AND from_tool=? ORDER BY count DESC LIMIT ?""",
                          (from_rid, from_tool, limit))
        if not rows:
            return []
        total = sum(r["count"] for r in rows) or 1
        return [{"to_resource_id": r["to_resource_id"], "to_tool": r["to_tool"],
                 "count": r["count"], "probability": round(r["count"] / total, 3)} for r in rows]

    def resource_counts(self) -> dict:
        rows = self.query("SELECT kind, category, COUNT(*) AS n FROM resources WHERE active=1 GROUP BY kind, category")
        out: dict = {}
        for r in rows:
            out.setdefault(r["kind"], {})[r["category"]] = r["n"]
        return out

    # ---------------- A402 가상 에스크로 & 정산소 (Clearinghouse) ----------------
    def deposit_credit(self, account_id: str, amount: int) -> dict:
        """가상 크레딧 계정에 잔액을 충전한다 (amount: micro-USDC 단위)."""
        if type(amount) is not int or not 1 <= amount <= 10**12:
            raise ValueError("Deposit amount must be positive.")
        now = time.time()
        with self.tx() as db:
            current = db.execute("SELECT balance,total_deposited FROM agent_credits WHERE account_id=?", (account_id,)).fetchone()
            if current and (current["balance"] + amount > 2**63-1 or current["total_deposited"] + amount > 2**63-1):
                raise ValueError("Credit account exceeds integer storage limit.")
            db.execute("""INSERT INTO agent_credits (account_id, balance, held, total_deposited, total_spent, updated_at)
                          VALUES (?, ?, 0, ?, 0, ?)
                          ON CONFLICT(account_id)
                          DO UPDATE SET balance=balance+excluded.balance,
                                        total_deposited=total_deposited+excluded.total_deposited,
                                        updated_at=excluded.updated_at""",
                       (account_id, amount, amount, now))
        return self.get_credit(account_id)

    def get_credit(self, account_id: str) -> dict:
        """가상 크레딧 계정 잔액 및 에스크로 예약 상태 조회."""
        rows = self.query("SELECT * FROM agent_credits WHERE account_id=?", (account_id,))
        if not rows:
            return {"account_id": account_id, "balance": 0, "held": 0, "available": 0, "total_deposited": 0, "total_spent": 0}
        r = rows[0]
        balance, held = r["balance"], r["held"]
        return {
            "account_id": account_id,
            "balance": balance,
            "held": held,
            "available": max(0, balance - held),
            "total_deposited": r["total_deposited"],
            "total_spent": r["total_spent"],
        }

    def hold_credit(self, account_id: str, amount: int, resource_id: int, tool_name: str) -> str:
        """에스크로 가승인(Hold). 결제 잔액을 예약하고 대기 트랜잭션 ID를 반환."""
        if type(amount) is not int or not 1 <= amount <= 10**12:
            raise ValueError("Hold amount must be positive.")
        tx_id = f"clr_{uuid.uuid4().hex}"
        now = time.time()
        with self.tx() as db:
            row = db.execute("SELECT balance, held FROM agent_credits WHERE account_id=?", (account_id,)).fetchone()
            if not row or (row["balance"] - row["held"]) < amount:
                avail = (row["balance"] - row["held"]) if row else 0
                raise ValueError(f"Insufficient available credits: needed {amount}, available {avail}")
            db.execute("UPDATE agent_credits SET held=held+?, updated_at=? WHERE account_id=?", (amount, now, account_id))
            db.execute("""INSERT INTO clearing_ledger (tx_id, account_id, resource_id, tool_name, amount, status, sla_verified, created_at)
                          VALUES (?, ?, ?, ?, ?, 'held', 0, ?)""",
                       (tx_id, account_id, resource_id, tool_name, amount, now))
        return tx_id

    def settle_credit(self, tx_id: str, receipt: dict | None = None) -> dict:
        """SLA 검증 통과 후 에스크로 최종 정산(Settle). 잔액 차감 및 영수증 저장."""
        now = time.time()
        receipt_json = json.dumps(receipt or {})
        with self.tx() as db:
            tx = db.execute("SELECT * FROM clearing_ledger WHERE tx_id=?", (tx_id,)).fetchone()
            if not tx:
                raise ValueError(f"Clearing transaction {tx_id} not found.")
            if tx["status"] != "held":
                raise ValueError(f"Transaction {tx_id} already finalized (status: {tx['status']}).")
            amount = tx["amount"]
            account_id = tx["account_id"]
            db.execute("""UPDATE agent_credits SET held=held-?, balance=balance-?, total_spent=total_spent+?, updated_at=?
                          WHERE account_id=?""", (amount, amount, amount, now, account_id))
            db.execute("""UPDATE clearing_ledger SET status='settled', sla_verified=1, receipt=?, settled_at=?
                          WHERE tx_id=?""", (receipt_json, now, tx_id))
        return {"tx_id": tx_id, "account_id": account_id, "amount": amount, "status": "settled", "receipt": receipt}

    def refund_credit(self, tx_id: str, reason: str = "") -> dict:
        """SLA 미충족 또는 호출 실패 시 에스크로 전액 환불(Refund). 예약 해제."""
        now = time.time()
        receipt_json = json.dumps({"refund_reason": reason})
        with self.tx() as db:
            tx = db.execute("SELECT * FROM clearing_ledger WHERE tx_id=?", (tx_id,)).fetchone()
            if not tx:
                raise ValueError(f"Clearing transaction {tx_id} not found.")
            if tx["status"] != "held":
                raise ValueError(f"Transaction {tx_id} already finalized (status: {tx['status']}).")
            amount = tx["amount"]
            account_id = tx["account_id"]
            db.execute("UPDATE agent_credits SET held=held-?, updated_at=? WHERE account_id=?", (amount, now, account_id))
            db.execute("""UPDATE clearing_ledger SET status='refunded', receipt=?, settled_at=?
                          WHERE tx_id=?""", (receipt_json, now, tx_id))
        return {"tx_id": tx_id, "account_id": account_id, "amount": amount, "status": "refunded", "reason": reason}

    def get_clearing_tx(self, tx_id: str) -> dict | None:
        rows = self.query("SELECT * FROM clearing_ledger WHERE tx_id=?", (tx_id,))
        return dict(rows[0]) if rows else None

    def withdraw_credit(self, account_id: str, amount: int, to_address: str) -> dict:
        """가상 크레딧 계정에서 잔액을 인출한다 (amount: micro-USDC 단위)."""
        if type(amount) is not int or not 1 <= amount <= 10**12:
            raise ValueError("Withdrawal amount must be positive.")
        if not isinstance(to_address, str) or len(to_address) != 42 or not to_address.startswith("0x") or any(c not in "0123456789abcdefABCDEF" for c in to_address[2:]) or int(to_address[2:], 16) == 0:
            raise ValueError("Invalid withdrawal destination.")
        now = time.time()
        tx_id = f"wdr_{uuid.uuid4().hex}"
        receipt = {"to_address": to_address, "network": "base", "withdrawn_at": now}
        receipt_json = json.dumps(receipt)
        with self.tx() as db:
            row = db.execute("SELECT balance, held FROM agent_credits WHERE account_id=?", (account_id,)).fetchone()
            if not row or (row["balance"] - row["held"]) < amount:
                avail = (row["balance"] - row["held"]) if row else 0
                raise ValueError(f"Insufficient available credits to withdraw: needed {amount}, available {avail}")
            db.execute("UPDATE agent_credits SET balance=balance-?, total_spent=total_spent+?, updated_at=? WHERE account_id=?",
                       (amount, amount, now, account_id))
            db.execute("""INSERT INTO clearing_ledger (tx_id, account_id, resource_id, tool_name, amount, status, sla_verified, receipt, created_at, settled_at)
                          VALUES (?, ?, 0, 'withdraw', ?, 'withdrawn', 1, ?, ?, ?)""",
                       (tx_id, account_id, amount, receipt_json, now, now))
        return {"tx_id": tx_id, "account_id": account_id, "amount": amount, "to_address": to_address, "status": "withdrawn", "receipt": receipt}

    def sweep_orphaned_holds(self, ttl_seconds: float = 900) -> list[str]:
        """일정 시간(기본 15분) 이상 정산/환불되지 않은 보류(held) 건을 자동 환불 처리."""
        cutoff = time.time() - ttl_seconds
        rows = self.query("SELECT tx_id FROM clearing_ledger WHERE status='held' AND created_at < ?", (cutoff,))
        refunded = []
        for r in rows:
            try:
                self.refund_credit(r["tx_id"], reason=f"Hold TTL expired ({int(ttl_seconds)}s) - auto refunded")
                refunded.append(r["tx_id"])
            except Exception as e:
                log.warning("Failed to auto-refund orphan hold %s: %s", r["tx_id"], e)
        return refunded

    def list_clearing_transactions(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        account_id: str | None = None,
    ) -> tuple[list[dict], int]:
        query = "SELECT * FROM clearing_ledger WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM clearing_ledger WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            count_query += " AND status = ?"
            params.append(status)
        if account_id:
            query += " AND account_id LIKE ?"
            count_query += " AND account_id LIKE ?"
            params.append(f"%{account_id}%")

        total = self.query(count_query, params)[0]["COUNT(*)"]
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        rows = self.query(query, params + [limit, offset])
        return [dict(r) for r in rows], total

    def list_agent_credits(
        self,
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
    ) -> tuple[list[dict], int]:
        query = "SELECT * FROM agent_credits WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM agent_credits WHERE 1=1"
        params: list = []
        if q:
            query += " AND account_id LIKE ?"
            count_query += " AND account_id LIKE ?"
            params.append(f"%{q}%")

        total = self.query(count_query, params)[0]["COUNT(*)"]
        query += " ORDER BY balance DESC, updated_at DESC LIMIT ? OFFSET ?"
        rows = self.query(query, params + [limit, offset])
        items = []
        for r in rows:
            d = dict(r)
            d["available"] = max(0, d["balance"] - d["held"])
            d["agent_id"] = d.get("account_id")
            d["balance_credits"] = d.get("balance", 0)
            d["held_credits"] = d.get("held", 0)
            d["total_credits"] = d.get("balance", 0) + d.get("held", 0)
            d["total_usd"] = round(d["total_credits"] * 0.001, 3)
            items.append(d)
        return items, total

    def get_clearing_overview(self) -> dict:
        acc_rows = self.query("""
            SELECT COUNT(*) AS total_accounts,
                   COALESCE(SUM(balance), 0) AS total_balance,
                   COALESCE(SUM(held), 0) AS total_held,
                   COALESCE(SUM(total_deposited), 0) AS total_deposited,
                   COALESCE(SUM(total_spent), 0) AS total_spent
            FROM agent_credits
        """)
        acc = dict(acc_rows[0]) if acc_rows else {}
        acc["total_settled"] = acc.get("total_spent", 0)
        acc["available_balance"] = max(0, acc.get("total_balance", 0) - acc.get("total_held", 0))

        tx_rows = self.query("""
            SELECT status, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total_amount
            FROM clearing_ledger GROUP BY status
        """)
        by_status = {r["status"]: {"count": r["count"], "total_amount": r["total_amount"]} for r in tx_rows}

        sla_rows = self.query("""
            SELECT COUNT(*) AS count,
                   COALESCE(AVG(json_extract(receipt, '$.latency_ms')), 0) AS avg_latency
            FROM clearing_ledger WHERE status='settled' AND sla_verified=1
        """)
        sla_info = dict(sla_rows[0]) if sla_rows else {}

        settled_count = by_status.get("settled", {}).get("count", 0)
        refunded_count = by_status.get("refunded", {}).get("count", 0)
        total_eval = settled_count + refunded_count
        sla_success_rate = round((settled_count / total_eval * 100), 1) if total_eval > 0 else 100.0

        return {
            "accounts": acc,
            "by_status": by_status,
            "ledger_by_status": by_status,
            "sla": {
                "settled_count": settled_count,
                "refunded_count": refunded_count,
                "success_rate": sla_success_rate,
                "avg_latency_ms": round(sla_info.get("avg_latency", 0), 1),
            },
        }

    # ---------------- 헬스체크 ----------------
    def due_for_check(self, now: float, limit: int, per_host: int | None = None,
                      kind: str | list[str] | tuple[str, ...] | None = None) -> list[dict]:
        """점검 시각이 된 에이전트. 한 번도 점검하지 않은 것(새로 수집된 것)이 먼저, 그다음 오래 기다린 순.
        per_host를 주면 호스트마다 그 개수까지만 뽑는다 (엔드포인트가 수천 개인 호스트가 앞을 다 차지하지 않게).
        kind를 지정하면 특정 에이전트 종류(a2a, mcp, x402 등)만 분산하여 점검한다."""
        order = "next_check_at IS NOT NULL, next_check_at"
        conds = ["active=1", "health_status != 'retired'"]
        params = []
        if isinstance(kind, (list, tuple)):
            if len(kind) == 1:
                conds.append("kind = ?")
                params.append(kind[0])
            elif len(kind) > 1:
                placeholders = ",".join("?" for _ in kind)
                conds.append(f"kind IN ({placeholders})")
                params.extend(kind)
        elif isinstance(kind, str) and kind:
            if kind == "x402":
                conds.append("(kind = 'x402' OR kind NOT IN ('a2a', 'mcp') OR kind IS NULL)")
            else:
                conds.append("kind = ?")
                params.append(kind)
        conds.append("(next_check_at IS NULL OR next_check_at <= ?)")
        params.append(now)
        where_clause = " AND ".join(conds)

        if per_host is None:
            rows = self.query(
                f"""SELECT * FROM resources WHERE {where_clause} ORDER BY {order}, random() LIMIT ?""",
                (*params, limit))
        else:
            rows = self.query(
                f"""SELECT * FROM (
                      SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY {order}) AS rn FROM resources
                      WHERE {where_clause})
                    WHERE rn <= ? ORDER BY {order}, random() LIMIT ?""",
                (*params, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def due_for_scavenge(self, now: float, limit: int = 50, per_host: int = 1) -> list[dict]:
        """7일 이상 연속 실패로 retired 된 에이전트 중 재활성화 점검 시각(Phase 2: 7일, Phase 3: 30일)이 된 대상.
        호스트당 per_host개로 제한하여 트래픽 집중을 방지한다."""
        order = "next_check_at IS NOT NULL, next_check_at"
        rows = self.query(
            f"""SELECT * FROM (
                  SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY {order}) AS rn FROM resources
                  WHERE active=1 AND health_status = 'retired' AND next_check_at IS NOT NULL AND next_check_at <= ?)
                WHERE rn <= ? ORDER BY {order} LIMIT ?""",
            (now, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def record_scavenge_failure(self, rid: int, now: float, error: str | None = None) -> None:
        """스캐빈저 재점검 실패 시 (여전히 죽어있는 경우): 다음 재점검 시각을 계층형 지수 백오프로 연장."""
        with self._lock:
            now = self._observation_time() if self._observation_context is not None else now
        with self.tx() as db:
            self._supersede_observation(db, rid, 'health', self._observation_time())
            row = db.execute("SELECT failing_since, consecutive_failures FROM resources WHERE id=?", (rid,)).fetchone()
            if not row:
                return
            failing_since = row["failing_since"] or now
            dead_duration = now - failing_since
            if dead_duration < 30 * 86400:
                next_check = now + 7 * 86400 * random.uniform(0.9, 1.1)
            elif dead_duration < 90 * 86400:
                next_check = now + 30 * 86400 * random.uniform(0.9, 1.1)
            else:
                next_check = None  # 90일 초과 시 영구 휴면
            db.execute(
                """UPDATE resources SET last_check_at=?, next_check_at=?, last_error=?,
                   consecutive_failures=consecutive_failures+1 WHERE id=?""",
                (now, next_check, (error or "")[:300] or None, rid),
            )

    def scavenger_stats(self, *, read_db=None) -> dict:
        """retired 상태 에이전트들의 페이즈별 수와 점검 대기 현황."""
        now = time.time()
        q = self.query if read_db is None else lambda sql, params=(): [dict(r) for r in read_db.execute(sql, params)]
        p2 = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status='retired' AND (? - failing_since) < 30 * 86400", (now,))[0]["n"]
        p3 = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status='retired' AND (? - failing_since) BETWEEN 30 * 86400 AND 90 * 86400", (now,))[0]["n"]
        p4 = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status='retired' AND (? - failing_since) >= 90 * 86400", (now,))[0]["n"]
        due = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status='retired' AND next_check_at <= ?", (now,))[0]["n"]
        total = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status='retired'")[0]["n"]
        return {"total_retired": total, "phase2_weekly": p2, "phase3_monthly": p3, "phase4_tombstone": p4, "due_for_scavenge": due}

    def vec_stats(self, descriptor=None, *, read_db=None) -> dict:
        """벡터 인덱스 및 아웃박스 대기열 통계."""
        with self._lock if read_db is None else nullcontext():
            db = self._db if read_db is None else read_db
            try:
                raw_count = db.execute("SELECT COUNT(*) FROM vec_resources").fetchone()[0]
                descriptor_hash = descriptor.digest if descriptor is not None else db.execute(
                    'SELECT descriptor_hash FROM legacy_vector_control WHERE id=1').fetchone()[0]
                vec_count = db.execute('''SELECT COUNT(*) FROM legacy_vector_provenance p
                    JOIN legacy_vector_generations g USING(resource_id)
                    JOIN legacy_vector_heads h USING(resource_id)
                    JOIN legacy_vector_jobs j ON j.job_id=p.job_id
                    JOIN resources r ON r.id=p.resource_id
                    WHERE p.resource_id IN (SELECT rowid FROM vec_resources)
                    AND p.generation=g.generation AND p.job_id=h.job_id AND j.status='indexed'
                    AND p.descriptor_hash=? AND r.active=1 AND r.health_status!='retired'
                    AND COALESCE(r.eval_security,'')!='quarantine' ''', (descriptor_hash,)).fetchone()[0]
                if getattr(self, '_vector_index', None) is None or self._vector_index.broken:
                    vec_count = 0
            except (sqlite3.Error, TypeError):
                raw_count, vec_count = 0, 0
            try:
                outbox_count = db.execute("SELECT COUNT(*) FROM vec_outbox").fetchone()[0]
            except Exception:
                outbox_count = 0
            active_count = db.execute("SELECT COUNT(*) FROM resources WHERE active=1").fetchone()[0]
            return {
                "vector_count": vec_count,
                "raw_vector_count": raw_count,
                "outbox_count": outbox_count,
                "active_count": active_count,
                "pct": round(vec_count / active_count * 100, 1) if active_count else 0.0,
            }

    def in_use_ids(self) -> set[int]:
        """게이트웨이 고객에게 현재 소개됐거나 제안 중인 에이전트 (더 자주 점검)."""
        rows = self.query(
            """SELECT current_resource AS id FROM needs WHERE status IN ('watching','active') AND current_resource IS NOT NULL
               UNION SELECT resource_id FROM offers WHERE status='pending'"""
        )
        return {r["id"] for r in rows}

    def record_health(self, rid: int, outcome: str, status_code: int | None, latency_ms: int | None,
                      error: str | None, next_check_at: float, down_after: int = 3, retire_after: float = 7 * 86400,
                      observed_price: int | None = None, observed_pay_to: str | None = None,
                      auth_observed: bool | None = None) -> dict:
        """점검 결과 저장. outcome: healthy | reachable | fail. 갱신된 상태를 돌려준다.

        down_after번 연속 실패하면 down, 실패가 retire_after(기본 7일) 넘게 이어지면 retired(점검·추천에서 제외).
        """
        now = self._observation_time()
        with self.tx() as db:
            self._supersede_observation(db, rid, 'health', self._observation_time())
            row = db.execute("SELECT consecutive_failures, failing_since, health_status, price_usdc, auth_scope FROM resources WHERE id=?",
                             (rid,)).fetchone()
            if row is None:
                return {}
            db.execute('UPDATE resources SET managed_at=COALESCE(managed_at,?) WHERE id=?', (now, rid))
            if outcome in HEALTH_UP:
                failures, status, last_ok, failing_since = 0, outcome, now, None
                next_check = next_check_at
            else:
                failures = row["consecutive_failures"] + 1
                failing_since = row["failing_since"] or now
                last_ok = None
                if failures >= down_after and now - failing_since >= retire_after:
                    status = "retired"
                    dead_duration = now - failing_since
                    if dead_duration < 30 * 86400:
                        next_check = now + 7 * 86400 * random.uniform(0.9, 1.1)  # Phase 2 (8~30일): 주 1회 재점검
                    elif dead_duration < 90 * 86400:
                        next_check = now + 30 * 86400 * random.uniform(0.9, 1.1)  # Phase 3 (31~90일): 월 1회 재점검
                    else:
                        next_check = None  # Phase 4 (90일 초과): 영구 휴면
                else:
                    status = "down" if failures >= down_after else "failing"
                    next_check = next_check_at
            db.execute(
                "INSERT INTO health_checks VALUES (?,?,?,?,?,?,?)",
                (rid, now, outcome, status_code, latency_ms, (error or "")[:300] or None, observed_price),
            )
            agg = db.execute(
                "SELECT COUNT(*) AS n, SUM(outcome IN ('healthy','reachable')) AS ok FROM health_checks WHERE resource_id=? AND at>?",
                (rid, now - 86400),
            ).fetchone()
            db.execute(
                """UPDATE resources SET health_status=?, consecutive_failures=?, failing_since=?, last_check_at=?,
                   last_ok_at=COALESCE(?, last_ok_at), next_check_at=?, last_status_code=?, last_error=?,
                   health_ok_24h=?, health_n_24h=?, probe_latency_ms=COALESCE(?, probe_latency_ms), probed_at=?
                   WHERE id=?""",
                (status, failures, failing_since, now, last_ok, next_check, status_code, (error or "")[:300] or None,
                 agg["ok"] or 0, agg["n"], latency_ms, now, rid),
            )
            if status!=row['health_status']:
                from ..agent_access.storage import enqueue
                enqueue(self,db,rid,'catalog_changed',evidence=['health',now],
                        observation={'scope':'health','status':status,'finished':now})
            if auth_observed is not None and (bool(auth_observed) or row['auth_scope'] != 'tool'):
                self._supersede_observation(db, rid, 'auth', now)
                db.execute("UPDATE resources SET auth_observed=? WHERE id=?", (int(auth_observed), rid))
            # A 402 challenge asking for 0 means payment is required but the amount is not known
            # (dynamic-price APIs answer an empty probe with 0: x402 32172, 109666, 9573 on
            # 2026-11-10). It keeps a stored price, and is stored as unknown (NULL), never as free.
            if observed_price == 0:
                observed_price = None if row["price_usdc"] == 0 else row["price_usdc"]
                price_changed = row["price_usdc"] == 0
            else:
                price_changed = observed_price is not None and observed_price != row["price_usdc"]
            if price_changed:
                self.record_observed_quote(rid, observed_price, observed_pay_to)
        return {"status": status, "previous": row["health_status"], "consecutive_failures": failures, "failing_since": failing_since,
                "price_changed": price_changed, "health_ok_24h": agg["ok"] or 0, "health_n_24h": agg["n"]}

    def record_observed_quote(self, rid, amount, pay_to=None):
        """Apply a provider quote through registry hashing, separately from reachability state."""
        if amount is not None and (type(amount) is not int or not 0 <= amount < 2**63):
            raise ValueError('Invalid observed quote.')
        with self.tx() as db:
            row = db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone()
            if row is None:
                return
            if self._observation_context is not None and self._observation_context[0].resource_id != rid:
                raise GuardError('invalid_token')
            resource = dict(row)
            resource.update(networks=[v for v in resource['networks'].split(',') if v],
                            details=json.loads(resource['details']), price_usdc=amount,
                            pay_to=pay_to or resource['pay_to'])
            self._upsert(db, resource, self._observation_time(), registry_observed=False)
            db.execute('UPDATE resources SET eval_at=NULL WHERE id=?', (rid,))

    # ---------------- 기능 조사 (tools/list) ----------------
    def due_for_capability(self, now: float, max_age: float, limit: int, per_host: int = 2, kind: str = "mcp") -> list[dict]:
        """기능을 조사할 에이전트: MCP는 인증 없이 응답하는(healthy) 서버, A2A는 agent card가 열리는(healthy) 에이전트 중
        조사한 지 max_age가 지난 것. 호스트당 per_host개."""
        # Rank only narrow columns, then read the chosen rows. Sorting whole rows (106k A2A
        # listings, ~2.7 KB each) spilled ~180 MB to disk and passed the 5 s statement timeout
        # under load (11-10 13:28); the narrow ranking stays in memory (601 -> 310 ms).
        chosen = self.query(
            """SELECT id FROM (
                 SELECT id, cap_checked_at, ROW_NUMBER() OVER (PARTITION BY host ORDER BY cap_checked_at IS NOT NULL, cap_checked_at) AS rn
                 FROM resources WHERE active=1 AND kind=? AND health_status='healthy'
                 AND (cap_checked_at IS NULL OR cap_checked_at < ?))
               WHERE rn <= ? ORDER BY cap_checked_at IS NOT NULL, cap_checked_at, random() LIMIT ?""",
            (kind, now - max_age, per_host, limit))
        rows = []
        for row in chosen:
            found = self.query("SELECT * FROM resources WHERE id=?", (row["id"],))
            if found:
                rows.append(dict(found[0]))
        return rows

    def record_capability(self, rid: int, caps: dict | None, error: str | None = None) -> None:
        with self.tx() as db:
            self._supersede_observation(db, rid, 'survey', self._observation_time())
            self._invalidate_survey_evaluation(db, rid)
            if caps is None:
                db.execute("UPDATE resources SET cap_checked_at=?, cap_error=? WHERE id=?", (self._observation_time(), (error or "")[:300], rid))
                return
            db.execute(
                """UPDATE resources SET cap_languages=?, cap_regions=?, cap_currencies=?, cap_tool_count=?, cap_tool_names=?,
                   cap_checked_at=?, cap_error=NULL WHERE id=?""",
                (cons.pack(caps["languages"]), cons.pack(caps["regions"]), cons.pack(caps["currencies"]), caps["tool_count"],
                 json.dumps(caps["tool_names"]), self._observation_time(), rid))

    # ---------------- 인증 방법 조사 ----------------
    def due_for_auth(self, now: float, max_age: float, limit: int, per_host: int = 1) -> list[dict]:
        """인증이 필요한 것으로 보이는 MCP 중 인증 방법을 조사한 지 max_age가 지난 것. 호스트당 per_host개."""
        rows = self.query(
            """SELECT * FROM (
                 SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY auth_checked_at IS NOT NULL, auth_checked_at) AS rn
                 FROM resources WHERE active=1 AND kind='mcp' AND health_status NOT IN ('down','retired')
                 AND COALESCE(auth_observed, auth_declared) = 1
                 AND (auth_checked_at IS NULL OR auth_checked_at < ?))
               WHERE rn <= ? ORDER BY auth_checked_at IS NOT NULL, auth_checked_at, random() LIMIT ?""",
            (now - max_age, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def record_auth(self, rid: int, found: dict | None, error: str | None = None) -> None:
        with self.tx() as db:
            self._supersede_observation(db, rid, 'auth', self._observation_time())
            if found is None:
                db.execute("UPDATE resources SET auth_checked_at=?, auth_error=? WHERE id=?", (self._observation_time(), (error or "")[:300], rid))
                return
            db.execute(
                "UPDATE resources SET auth_method=?, auth_autonomy=?, auth_info=?, auth_checked_at=?, auth_error=NULL WHERE id=?",
                (found["method"], found["autonomy"], json.dumps(found["info"]), self._observation_time(), rid))  # 자르지 않음 (조사 단계에서 줄임)
            if found["method"] == "none":  # 실제로는 인증 없이 동작 (도구 단계 인증이 확인된 경우는 제외)
                db.execute("UPDATE resources SET auth_observed=0 WHERE id=? AND COALESCE(auth_scope,'') != 'tool'", (rid,))

    def set_category(self, rid: int, category: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE resources SET category=? WHERE id=?", (category, rid))

    def set_auth_observed(self, rid: int, required: bool) -> None:
        with self.tx() as db:
            self._supersede_observation(db, rid, 'auth', self._observation_time())
            db.execute("UPDATE resources SET auth_observed=?, auth_scope='connection' WHERE id=?", (int(required), rid))

    def mark_tool_level_auth(self, rid: int) -> None:
        """연결은 인증 없이 되지만 도구 호출에서 인증을 요구함 → 인증 필요로 표시하고 인증 방법을 다시 조사."""
        with self.tx() as db:
            self._supersede_observation(db, rid, 'auth', self._observation_time())
            db.execute("UPDATE resources SET auth_observed=1, auth_scope='tool', auth_checked_at=NULL WHERE id=?", (rid,))

    # ---------------- 사용 안내 ----------------
    def record_usage(self, rid: int, tools: list[dict], digest: str, guide: dict, changes: dict | None,
                     trial: dict | None, *, full_tools: list[dict] | None = None) -> bool:
        """사용 안내 저장. 도구 목록이 바뀌었으면 usage_updated_at을 갱신하고 True를 돌려준다."""
        now = self._observation_time()
        from ..capability_registry import full_tools as normalize_full, digest as schema_digest
        if full_tools is None:
            candidate = guide.get('tools') or tools
            if candidate and all(isinstance(t, dict) and 'inputSchema' in t for t in candidate):
                full_tools = candidate
        full = None
        if full_tools is not None:
            try:
                full = normalize_full(full_tools)
            except (ValueError, TypeError) as exc:
                log.debug("resource %s full_tools normalization skipped: %s", rid, exc)
                full = None
        with self.tx() as db:
            self._supersede_observation(db, rid, 'survey', self._observation_time())
            row = db.execute("SELECT usage_tools_hash, name, description FROM resources WHERE id=?", (rid,)).fetchone()
            changed = row is not None and row["usage_tools_hash"] != digest
            db.execute(
                """UPDATE resources SET usage_tools=?, usage_tools_hash=?, usage_guide=?,
                   usage_updated_at=CASE WHEN ? THEN ? ELSE usage_updated_at END,
                   usage_changes=CASE WHEN ? THEN ? ELSE usage_changes END WHERE id=?""",
                (json.dumps(tools), digest, json.dumps(guide), changed, now, changed and changes is not None,
                 json.dumps(changes) if changes else None, rid))
            if full is not None:
                db.execute('UPDATE resources SET usage_full_tools=?,usage_full_hash=? WHERE id=?',(json.dumps(full),schema_digest(full),rid))
            elif changed or self._observation_context is not None:
                db.execute('UPDATE resources SET usage_full_tools=NULL,usage_full_hash=NULL WHERE id=?',(rid,))
            self._invalidate_survey_evaluation(db, rid)
            if trial is not None:
                trial = {**trial, "at": self._observation_time(trial.get("at"))}
                db.execute("UPDATE resources SET trial_info=?, trial_ok=? WHERE id=?", (json.dumps(trial), int(bool(trial.get("ok"))), rid))
            if row is not None:
                tool_text = extract_tool_search_text(json.dumps(tools))
                full_desc = f"{row['description']}\n{tool_text}".strip()
                db.execute("DELETE FROM resources_fts WHERE rowid=?", (rid,))
                db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, row["name"], full_desc))
                db.execute("INSERT OR REPLACE INTO vec_outbox(resource_id, enqueued_at, reason) VALUES (?, ?, 'usage')", (rid, now))
                cat_row = db.execute("SELECT category, source FROM resources WHERE id=?", (rid,)).fetchone()
                if cat_row and cat_row["source"] != "registered" and cat_row["category"] == "other":
                    new_cat = classify_listing(f"{row['name']} {row['description']}", tool_text)
                    if new_cat != "other":
                        db.execute("UPDATE resources SET category=? WHERE id=?", (new_cat, rid))
        return changed

    # ---------------- 품질 평가 ----------------
    def record_evaluation_unavailable(self, rid: int) -> None:
        """Retain assessment history while requiring review of an unevaluated new survey."""
        with self.tx() as db:
            self._supersede_observation(db, rid, 'evaluation', self._observation_time())
            db.execute("""UPDATE resources SET eval_at=NULL,
                eval_security=CASE WHEN eval_security='quarantine' THEN 'quarantine' ELSE 'review' END
                WHERE id=?""", (rid,))
            db.execute('DELETE FROM capability_eligibility WHERE resource_id=?', (rid,))

    def record_evaluation(self, rid: int, ev: dict) -> None:
        trial_ok = ev.get("trial_ok")
        with self.tx() as db:
            self._supersede_observation(db, rid, 'evaluation', self._observation_time())
            if trial_ok is not None:
                db.execute("""UPDATE resources SET eval_score=?, eval_grade=?, eval_security=?, eval_coverage=?, eval_info=?, eval_at=?, trial_ok=?
                              WHERE id=?""",
                           (ev.get("score"), ev.get("grade"), ev.get("security"), ev.get("coverage"),
                            json.dumps(ev, ensure_ascii=False), self._observation_time(ev.get("at")), trial_ok, rid))
            else:
                db.execute("""UPDATE resources SET eval_score=?, eval_grade=?, eval_security=?, eval_coverage=?, eval_info=?, eval_at=?
                              WHERE id=?""",
                           (ev.get("score"), ev.get("grade"), ev.get("security"), ev.get("coverage"),
                            json.dumps(ev, ensure_ascii=False), self._observation_time(ev.get("at")), rid))

    def evaluate_x402_batch(self, limit: int = 5000) -> int:
        from ..collector.evaluation import POLICY_WINDOW_DAYS, apply_quality_policy, evaluate_x402
        rows = self.query(
            """SELECT * FROM resources WHERE active=1 AND kind='x402' AND health_status != 'retired'
               AND (eval_at IS NULL OR eval_at < strftime('%s','now') - 86400)
               ORDER BY eval_at IS NOT NULL, eval_at LIMIT ?""", (limit,))
        if not rows:
            return 0
        accepted = 0
        counts = self.health_counts([row['id'] for row in rows], time.time() - POLICY_WINDOW_DAYS * 86400)
        for row in rows:
            resource = dict(row)
            try:
                token = self.observation_guard(resource['id'], 'evaluation', expected_resource=resource)
                ev = apply_quality_policy(resource, evaluate_x402(resource, now=time.time()), counts.get(resource['id']))
                with self.observation_transaction(token):
                    self.record_evaluation(resource['id'], ev)
                accepted += 1
            except GuardError:
                continue
        return accepted

    def health_counts(self, ids: list[int], since: float) -> dict[int, tuple[int, int]]:
        """resource_id → (점검 수, 성공 수), SINCE 이후 헬스체크 기록. 품질 정책의 가용성 근거."""
        counts = {}
        for start in range(0, len(ids), 200):  # PostgreSQL 저장소는 문장당 값 256개까지 받는다
            chunk = ids[start:start + 200]
            rows = self.query(f"""SELECT resource_id, COUNT(*) AS n,
                SUM(CASE WHEN outcome IN ('healthy','reachable') THEN 1 ELSE 0 END) AS ok
                FROM health_checks WHERE at > ? AND resource_id IN ({','.join('?' * len(chunk))}) GROUP BY resource_id""",
                              (since, *chunk))
            counts.update({r["resource_id"]: (r["n"], r["ok"] or 0) for r in rows})
        return counts

    def quality_policy_batch(self, limit: int = 500) -> int:
        """기존 평가에 품질 정책(evaluation.apply_quality_policy)을 입힌다. 네트워크 요청 없음.
        id 순서로 한 바퀴 돌고, 다 돌면 그 정책 버전은 끝난 것으로 기록한다 (새 평가는 기록할 때 정책이 붙는다)."""
        from ..collector.evaluation import POLICY_VERSION, POLICY_WINDOW_DAYS, apply_quality_policy
        if self.get_meta("quality_policy_done") == POLICY_VERSION:
            return 0
        cursor = self.get_meta("quality_policy_cursor") or {}
        after = cursor.get("id", 0) if cursor.get("version") == POLICY_VERSION else 0
        rows = [dict(r) for r in self.query(
            """SELECT * FROM resources WHERE id > ? AND active=1 AND kind IN ('mcp','a2a','x402')
               AND eval_score IS NOT NULL ORDER BY id LIMIT ?""", (after, limit))]
        if not rows:
            self.set_meta("quality_policy_done", POLICY_VERSION)
            return 0
        counts = self.health_counts([r["id"] for r in rows], time.time() - POLICY_WINDOW_DAYS * 86400)
        changed = 0
        for resource in rows:
            try:
                ev = json.loads(resource.get("eval_info") or "null")
            except ValueError:
                continue
            new = apply_quality_policy(resource, ev, counts.get(resource["id"]))
            if new is ev:
                continue
            try:
                token = self.observation_guard(resource["id"], "evaluation", expected_resource=resource)
                with self.observation_transaction(token):
                    self.record_evaluation(resource["id"], {**new, "at": time.time()})
                changed += 1
            except GuardError:
                continue
        self.set_meta("quality_policy_cursor", {"version": POLICY_VERSION, "id": rows[-1]["id"], "changed": changed})
        return len(rows)

    def score_percentile(self, score: float, kind: str = "mcp") -> float | None:
        """같은 종류에서 평가 점수가 이보다 낮은 비율 (0~1). 등급이 A에 몰려도 상대 위치를 알 수 있게."""
        row = self.query("""SELECT COUNT(*) AS n, SUM(eval_score < ?) AS lower FROM resources
                            WHERE active=1 AND kind=? AND eval_score IS NOT NULL""", (score, kind))[0]
        return round((row["lower"] or 0) / row["n"], 3) if row["n"] >= 20 else None

    def due_for_static_evaluation(self, now: float, max_age: float, limit: int) -> list[dict]:
        """연결부터 인증이 필요해 도구를 볼 수 없는 MCP: 출처 정적 평가만 (네트워크 요청 없음)."""
        return [dict(r) for r in self.query(
            """SELECT * FROM resources WHERE active=1 AND kind='mcp' AND health_status NOT IN ('down','retired')
               AND COALESCE(auth_observed, auth_declared, 0) = 1 AND COALESCE(auth_scope, 'connection') != 'tool'
               AND (eval_at IS NULL OR eval_at < ?) ORDER BY eval_at IS NOT NULL, eval_at LIMIT ?""",
            (now - max_age, limit))]

    def postpone(self, ids: list[int], at: float) -> None:
        """점검 결과를 기록하지 않고 나중에 다시 점검하도록 미룬다 (우리 쪽 네트워크 문제일 때)."""
        with self.tx() as db:
            db.executemany("UPDATE resources SET next_check_at=? WHERE id=?", [(at, i) for i in ids])

    def health_history(self, rid: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.query(
            "SELECT at, outcome, status_code, latency_ms, error, observed_price FROM health_checks WHERE resource_id=? ORDER BY at DESC LIMIT ?",
            (rid, limit))]

    def prune_health(self, before: float) -> int:
        with self.tx() as db:
            return db.execute("DELETE FROM health_checks WHERE at<?", (before,)).rowcount

    def record_crawl_run(self, source: str, report: dict) -> None:
        with self.tx() as db:
            db.execute(
                """INSERT INTO crawl_runs (at, source, ok, seen, new, deactivated, seconds, error, mode, changed, unchanged, pages, registry_missing)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), source, int(report.get("ok", False)), report.get("seen"), report.get("new"),
                 report.get("deactivated"), report.get("seconds"), report.get("error"), report.get("mode"),
                 report.get("changed"), report.get("unchanged"), report.get("pages"), report.get('registry_missing', 0)),
            )

    def collector_stats(self) -> dict:
        q = self.query
        status = {r["health_status"]: r["n"] for r in q(
            "SELECT health_status, COUNT(*) AS n FROM resources WHERE active=1 GROUP BY health_status")}
        checked_1h = q("SELECT COUNT(*) AS n, SUM(outcome IN ('healthy','reachable')) AS ok FROM health_checks WHERE at>?",
                       (time.time() - 3600,))[0]
        overdue = q("""SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status != 'retired'
                       AND (next_check_at IS NULL OR next_check_at < ?)""",
                    (time.time() - 3600,))[0]["n"]
        runs = [dict(r) for r in q("SELECT * FROM crawl_runs ORDER BY at DESC LIMIT 10")]
        c = q("""SELECT
                   SUM(COALESCE(auth_observed, auth_declared) = 1) AS auth_required,
                   SUM(COALESCE(auth_observed, auth_declared) = 0) AS auth_free,
                   SUM(COALESCE(auth_observed, auth_declared) IS NULL) AS auth_unknown,
                   SUM(regions IS NOT NULL OR cap_regions IS NOT NULL) AS region_specific,
                   SUM(cap_checked_at IS NOT NULL AND cap_error IS NULL) AS capabilities_checked,
                   SUM(cap_languages IS NOT NULL) AS with_language_options,
                   SUM(auth_method IS NOT NULL) AS auth_method_known,
                   SUM(auth_autonomy = 'agent_autonomous') AS auth_agent_autonomous,
                   SUM(usage_guide IS NOT NULL) AS usage_guides,
                   SUM(trial_ok = 1) AS verified_working,
                   SUM(trial_ok = 0) AS trial_failed,
                   SUM(usage_changes IS NOT NULL AND usage_updated_at > strftime('%s','now') - 86400) AS usage_changed_24h
                 FROM resources WHERE active=1 AND health_status != 'retired'""")[0]
        langs = {r["desc_lang"]: r["n"] for r in q(
            "SELECT desc_lang, COUNT(*) AS n FROM resources WHERE active=1 AND desc_lang IS NOT NULL GROUP BY desc_lang ORDER BY n DESC LIMIT 10")}
        return {
            "active_agents": sum(status.values()),
            "by_health": status,
            "by_kind_category": self.resource_counts(),
            "checks_last_hour": {"total": checked_1h["n"], "ok": checked_1h["ok"] or 0},
            "overdue_over_1h": overdue,
            "recent_crawls": runs,
            "constraints": {**{k: c[k] or 0 for k in c.keys()}, "description_languages": langs,
                            "auth_methods": {r["auth_method"]: r["n"] for r in q(
                                "SELECT auth_method, COUNT(*) AS n FROM resources WHERE active=1 AND auth_method IS NOT NULL GROUP BY auth_method")}},
            "evaluation": self.evaluation_stats(),
            "evaluation_by_kind": {k: self.evaluation_stats(k) for k in ("mcp", "a2a", "x402")},
            "agent_sources": self.agent_source_stats(),
        }

    def evaluation_stats(self, kind: str | None = None) -> dict:
        q = self.query
        base = "FROM resources WHERE active=1 AND health_status != 'retired' AND eval_at IS NOT NULL" + \
            (f" AND kind='{kind}'" if kind in ("mcp", "a2a", "x402") else "")
        avg = q(f"SELECT COUNT(*) AS n, AVG(eval_score) AS avg, SUM(eval_at > strftime('%s','now') - 86400) AS last_24h {base}")[0]
        return {
            "evaluated": avg["n"],
            "evaluated_24h": avg["last_24h"] or 0,
            "average_score": round(avg["avg"], 1) if avg["avg"] is not None else None,
            "by_grade": {r["g"]: r["n"] for r in q(f"SELECT COALESCE(eval_grade, 'static') AS g, COUNT(*) AS n {base} GROUP BY g ORDER BY g")},
            "by_security": {r["eval_security"]: r["n"] for r in q(f"SELECT eval_security, COUNT(*) AS n {base} GROUP BY eval_security")},
            "by_coverage": {r["eval_coverage"]: r["n"] for r in q(f"SELECT eval_coverage, COUNT(*) AS n {base} GROUP BY eval_coverage")},
        }

    def agent_source_stats(self) -> dict:
        """A2A 에이전트 수집 현황: 출처별 수, ERC-8004 체인별 조사 진행."""
        q = self.query
        return {
            "a2a_by_source": {r["source"]: r["n"] for r in q(
                "SELECT source, COUNT(*) AS n FROM resources WHERE active=1 AND kind='a2a' GROUP BY source")},
            "erc8004": {f"{r['chain']}:{r['status']}": r["n"] for r in q(
                "SELECT chain, status, COUNT(*) AS n FROM erc8004_tokens GROUP BY chain, status")},
            "wellknown_hosts_checked": q("SELECT COUNT(*) AS n FROM wellknown_hosts")[0]["n"],
            "wellknown_hosts_found": q("SELECT COUNT(*) AS n FROM wellknown_hosts WHERE found IS NOT NULL")[0]["n"],
        }

    # ---------------- meta ----------------
    def get_meta(self, key: str, default=None):
        rows = self.query("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    # ---------------- Agent Test Reports & Workflows ----------------
    def find_existing_test_report(self, resource_id=None, kind=None, agent_url=None):
        from ..report_creation import find_existing, subject
        return find_existing(self, subject(self, resource_id, kind, agent_url))

    def create_test_report(self, data: dict) -> int:
        from ..concierge.report_evidence import report_subject_matches, measured_report, canonical_endpoint
        from ..report_creation import (ReportAlreadyExists, ReportSlugConflict,
                                      find_existing, subject as report_subject, reserve, finish)
        data = dict(data)
        now = time.time()
        from ..report_time import report_timestamp
        for field in ('created_at','updated_at'):
            if data.get(field) is not None:
                data[field] = report_timestamp(data[field], legacy_utc=True)
        executed=data.get('executed_at');finished=data.get('execution_finished_at')
        if executed is not None or finished is not None:
            import math
            if any(type(t) not in (int,float) or not math.isfinite(t) for t in (executed,finished)) or not 0<executed<=finished<=now+5:
                raise ValueError('Reports require valid actual execution timestamps.')
        rid = data.get('resource_id')
        if rid is not None and (type(rid) is not int or rid <= 0):
            raise ValueError('A report resource ID must be a positive integer.')
        subject = self.resource(rid) if rid is not None else None
        if rid is not None and subject is None:
            raise ValueError('Choose an existing registered agent.')
        if subject:
            data.setdefault('kind', subject['kind'])
            if not data.get('agent_name'):data['agent_name'] = subject['name']
            if not data.get('agent_url'):data['agent_url'] = subject['url']
            if not report_subject_matches(data, subject):
                raise ValueError('The report subject does not match this catalog resource.')
            data['agent_name'] = subject['name']
            if canonical_endpoint(data['agent_url']) == canonical_endpoint(subject['url']):
                data['agent_url'] = subject['url']
        scope = data.get('evidence_scope')
        if scope in ('execution', 'contract'):
            if not subject or not measured_report(data, subject, self, now, require_latest=False):
                raise ValueError('Execution reports require matching recorded evidence for the current connection version.')
        title = str(data["title"]).strip()
        if not title:
            raise ValueError('Provide a report title.')
        resolved = report_subject(self, rid, data.get('kind'), data.get('agent_url'))
        slug = str(data.get("slug") or "").strip()
        if not slug:
            slug = f"report-{resolved[1]}-{uuid.uuid4().hex}"
        with self.tx() as db:
            reserve(db, resolved[0])
            if subject:
                current = self.resource(rid)
                if (not current or not report_subject_matches(data, current)
                        or report_subject(self, rid, data.get('kind'), data.get('agent_url')) != resolved):
                    raise ValueError('The report subject changed while saving.')
                if scope in ('execution','contract') and not measured_report(data, current, self, now, require_latest=False):
                    raise ValueError('The connection evidence changed while saving.')
            existing = find_existing(self, resolved)
            if existing is not None:
                raise ReportAlreadyExists(existing)
            if db.execute('SELECT id FROM agent_test_reports WHERE slug=?', (slug,)).fetchone():
                raise ReportSlugConflict()
            cur = db.execute(
                """INSERT INTO agent_test_reports (
                    resource_id, title, slug, kind, source, agent_name, agent_url, category,
                    eval_grade, eval_score, status_code, latency_ms, is_success, test_method,
                    tool_name, input_wire, output_wire, summary, content_md, pros, cons,
                    workflow_recommendation, tags, author, created_at, updated_at,
                    executed_at, execution_finished_at, connection_version_id, evidence_scope,creation_subject_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("resource_id"),
                    title,
                    slug,
                    data.get("kind", "mcp"),
                    data.get("source", "unknown"),
                    data.get("agent_name", ""),
                    data.get("agent_url", ""),
                    data.get("category", "other"),
                    data.get("eval_grade"),
                    data.get("eval_score"),
                    data.get("status_code", 200),
                    data.get("latency_ms", 0.0),
                    int(data.get("is_success", 0)),
                    data.get("test_method", ""),
                    data.get("tool_name"),
                    json.dumps(data.get("input_wire") or {}),
                    json.dumps(data.get("output_wire") or {}),
                    data.get("summary", ""),
                    data.get("content_md", ""),
                    json.dumps(data.get("pros") if isinstance(data.get("pros"), list) else [str(data.get("pros") or "")]),
                    json.dumps(data.get("cons") if isinstance(data.get("cons"), list) else [str(data.get("cons") or "")]),
                    data.get("workflow_recommendation", ""),
                    data.get("tags", ""),
                    data.get("author", "AI Verification Agent"),
                    data.get("created_at") or now,
                    data.get("updated_at") or now,
                    executed, finished, data.get('connection_version_id'),
                    scope if scope in ('transport','execution','contract') else 'legacy',
                    resolved[0],
                )
            )
            report_id=cur.lastrowid
            # Recheck after acquiring the writer lock: an external catalog
            # writer may have changed the binding during initial validation.
            if subject:
                current = self.resource(rid)
                if not current or not report_subject_matches(data, current):
                    raise ValueError('The report subject changed while saving.')
                if scope in ('execution','contract') and not measured_report(data, current, self, now, require_latest=False):
                    raise ValueError('The connection evidence changed while saving.')
            finish(db, resolved[0], report_id)
            return report_id

    def list_test_reports(self, limit: int = 50, offset: int = 0, kind: str | None = None,
                          category: str | None = None, grade: str | None = None,
                          q: str | None = None, is_success: int | None = None,
                          tag: str | None = None) -> tuple[list[dict], int]:
        conds, params = [], []
        if kind:
            conds.append("kind = ?")
            params.append(kind)
        if category:
            conds.append("category = ?")
            params.append(category)
        if grade:
            conds.append("eval_grade = ?")
            params.append(grade)
        if is_success is not None:
            conds.append("is_success = ?")
            params.append(int(is_success))
        if tag:
            conds.append("tags LIKE ?")
            params.append(f"%{tag}%")
        if q:
            term = f"%{q.strip()}%"
            conds.append("(title LIKE ? OR agent_name LIKE ? OR summary LIKE ? OR tags LIKE ?)")
            params.extend([term, term, term, term])

        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        total = self.query(f"SELECT COUNT(*) AS c FROM agent_test_reports {where}", params)[0]["c"]
        rows = self.query(
            f"""SELECT id, resource_id, title, slug, kind, source, agent_name, agent_url, category,
                       eval_grade, eval_score, status_code, latency_ms, is_success, test_method,
                       tool_name, summary, pros, cons, workflow_recommendation, tags, author, created_at, updated_at,
                       executed_at,execution_finished_at,connection_version_id,evidence_scope
                FROM agent_test_reports {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset)
        )
        res = [dict(r) for r in rows]
        for r in res:
            from ..concierge.report_evidence import measured_report
            resource = self.resource(r['resource_id']) if r.get('resource_id') is not None else None
            r['execution_measured'] = bool(resource and measured_report(r,resource,self,time.time()))
            for k in ("pros", "cons"):
                if r.get(k):
                    try:
                        r[k] = json.loads(r[k])
                    except Exception:
                        pass
        return res, total

    def get_test_report(self, report_id: int) -> dict | None:
        rows = self.query("SELECT * FROM agent_test_reports WHERE id = ?", (report_id,))
        if not rows:
            return None
        r = dict(rows[0])
        from ..concierge.report_evidence import measured_report
        resource = self.resource(r['resource_id']) if r.get('resource_id') is not None else None
        r['execution_measured'] = bool(resource and measured_report(r,resource,self,time.time()))
        for k in ("input_wire", "output_wire", "pros", "cons"):
            if r.get(k):
                try:
                    r[k] = json.loads(r[k])
                except Exception:
                    pass
        return r

    def get_test_report_by_slug(self, slug: str) -> dict | None:
        rows = self.query("SELECT * FROM agent_test_reports WHERE slug = ?", (slug,))
        if not rows:
            return None
        r = dict(rows[0])
        from ..concierge.report_evidence import measured_report
        resource = self.resource(r['resource_id']) if r.get('resource_id') is not None else None
        r['execution_measured'] = bool(resource and measured_report(r,resource,self,time.time()))
        for k in ("input_wire", "output_wire", "pros", "cons"):
            if r.get(k):
                try:
                    r[k] = json.loads(r[k])
                except Exception:
                    pass
        return r

    def create_workflow(self, data: dict) -> int:
        now = time.time()
        steps_val = data.get("steps")
        nodes_val = data.get("nodes")
        edges_val = data.get("edges")
        graph_data = data.get("graph_data")

        if graph_data and isinstance(graph_data, dict):
            nodes_val = graph_data.get("nodes", nodes_val)
            edges_val = graph_data.get("edges", edges_val)

        if nodes_val is not None:
            if not isinstance(nodes_val, list):
                nodes_val = []
            if not isinstance(edges_val, list):
                edges_val = []
            derived_steps = _graph_to_steps(nodes_val, edges_val)
            packaged = {
                "nodes": nodes_val,
                "edges": edges_val,
                "steps": derived_steps
            }
            steps_str = json.dumps(packaged)
        elif isinstance(steps_val, list):
            nodes, edges = _steps_to_graph(steps_val, data.get("trigger_type", "manual"))
            packaged = {
                "nodes": nodes,
                "edges": edges,
                "steps": steps_val
            }
            steps_str = json.dumps(packaged)
        elif isinstance(steps_val, dict) and "nodes" in steps_val:
            steps_str = json.dumps(steps_val)
        elif isinstance(steps_val, str):
            steps_str = steps_val
        else:
            steps_str = json.dumps([])

        with self.tx() as db:
            cur = db.execute(
                """INSERT INTO agent_workflows (
                    name, description, category, trigger_type, steps, tags, is_active,
                    is_template, author, author_wallet, parent_workflow_id,
                    forks_count, likes_count, runs_count, rating_avg,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("name", "New Workflow"),
                    data.get("description", ""),
                    data.get("category", "automation"),
                    data.get("trigger_type", "manual"),
                    steps_str,
                    data.get("tags", ""),
                    int(data.get("is_active", 1)),
                    int(data.get("is_template", 0)),
                    data.get("author", "Admin"),
                    data.get("author_wallet", ""),
                    data.get("parent_workflow_id"),
                    int(data.get("forks_count", 0)),
                    int(data.get("likes_count", 0)),
                    int(data.get("runs_count", 0)),
                    float(data.get("rating_avg", 5.0)),
                    now,
                    now
                )
            )
            return cur.lastrowid

    def list_workflows(
        self,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = False,
        is_template: int | None = None,
        author: str | None = None,
        category: str | None = None,
        q: str | None = None,
        sort_by: str = "updated_at",
    ) -> tuple[list[dict], int]:
        wheres = []
        params = []
        if active_only:
            wheres.append("is_active = 1")
        if is_template is not None:
            wheres.append("is_template = ?")
            params.append(int(is_template))
        if author:
            wheres.append("author = ?")
            params.append(author)
        if category and category != "all":
            wheres.append("category = ?")
            params.append(category)
        if q:
            wheres.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])

        where_clause = f"WHERE {' AND '.join(wheres)}" if wheres else ""

        if sort_by == "popular":
            order_clause = "ORDER BY forks_count DESC, likes_count DESC, id DESC"
        elif sort_by == "rating":
            order_clause = "ORDER BY rating_avg DESC, forks_count DESC, id DESC"
        elif sort_by == "runs":
            order_clause = "ORDER BY runs_count DESC, id DESC"
        elif sort_by == "created":
            order_clause = "ORDER BY created_at DESC, id DESC"
        else:
            order_clause = "ORDER BY updated_at DESC, id DESC"

        total = self.query(f"SELECT COUNT(*) AS c FROM agent_workflows {where_clause}", tuple(params))[0]["c"]
        rows = self.query(
            f"SELECT * FROM agent_workflows {where_clause} {order_clause} LIMIT ? OFFSET ?",
            tuple(params + [limit, offset])
        )
        res = [dict(r) for r in rows]
        for r in res:
            if r.get("steps"):
                try:
                    parsed = json.loads(r["steps"])
                    if isinstance(parsed, dict) and "nodes" in parsed:
                        r["nodes"] = parsed.get("nodes", [])
                        r["edges"] = parsed.get("edges", [])
                        r["graph_data"] = {"nodes": r["nodes"], "edges": r["edges"]}
                        r["steps"] = parsed.get("steps") or _graph_to_steps(r["nodes"], r["edges"])
                    elif isinstance(parsed, list):
                        nodes, edges = _steps_to_graph(parsed, r.get("trigger_type", "manual"))
                        r["nodes"] = nodes
                        r["edges"] = edges
                        r["graph_data"] = {"nodes": nodes, "edges": edges}
                        r["steps"] = parsed
                    else:
                        r["steps"] = []
                        r["nodes"] = []
                        r["edges"] = []
                        r["graph_data"] = {"nodes": [], "edges": []}
                except Exception:
                    r["steps"] = []
                    r["nodes"] = []
                    r["edges"] = []
                    r["graph_data"] = {"nodes": [], "edges": []}
            else:
                r["steps"] = []
                r["nodes"] = []
                r["edges"] = []
                r["graph_data"] = {"nodes": [], "edges": []}
        from ..workflow_templates import bind_resources
        return [bind_resources(self,r) for r in res], total

    def get_workflow(self, workflow_id: int) -> dict | None:
        rows = self.query("SELECT * FROM agent_workflows WHERE id = ?", (workflow_id,))
        if not rows:
            return None
        r = dict(rows[0])
        if r.get("steps"):
            try:
                parsed = json.loads(r["steps"])
                if isinstance(parsed, dict) and "nodes" in parsed:
                    r["nodes"] = parsed.get("nodes", [])
                    r["edges"] = parsed.get("edges", [])
                    r["graph_data"] = {"nodes": r["nodes"], "edges": r["edges"]}
                    r["steps"] = parsed.get("steps") or _graph_to_steps(r["nodes"], r["edges"])
                elif isinstance(parsed, list):
                    nodes, edges = _steps_to_graph(parsed, r.get("trigger_type", "manual"))
                    r["nodes"] = nodes
                    r["edges"] = edges
                    r["graph_data"] = {"nodes": nodes, "edges": edges}
                    r["steps"] = parsed
                else:
                    r["steps"] = []
                    r["nodes"] = []
                    r["edges"] = []
                    r["graph_data"] = {"nodes": [], "edges": []}
            except Exception:
                r["steps"] = []
                r["nodes"] = []
                r["edges"] = []
                r["graph_data"] = {"nodes": [], "edges": []}
        else:
            r["steps"] = []
            r["nodes"] = []
            r["edges"] = []
            r["graph_data"] = {"nodes": [], "edges": []}
        from ..workflow_templates import bind_resources
        return bind_resources(self,r)

    def update_workflow(self, workflow_id: int, data: dict) -> bool:
        fields = []
        params = []
        for col in (
            "name", "description", "category", "trigger_type", "tags", "is_active",
            "is_template", "author", "author_wallet", "parent_workflow_id",
            "forks_count", "likes_count", "runs_count", "rating_avg"
        ):
            if col in data:
                fields.append(f"{col} = ?")
                params.append(data[col])
        if "steps" in data or "nodes" in data or "graph_data" in data:
            nodes_val = data.get("nodes")
            edges_val = data.get("edges")
            graph_data = data.get("graph_data")
            if graph_data and isinstance(graph_data, dict):
                nodes_val = graph_data.get("nodes", nodes_val)
                edges_val = graph_data.get("edges", edges_val)

            if nodes_val is not None:
                if not isinstance(nodes_val, list):
                    nodes_val = []
                if not isinstance(edges_val, list):
                    edges_val = []
                derived_steps = _graph_to_steps(nodes_val, edges_val)
                packaged = {
                    "nodes": nodes_val,
                    "edges": edges_val,
                    "steps": derived_steps
                }
                steps_val = json.dumps(packaged)
            else:
                steps_raw = data.get("steps")
                if isinstance(steps_raw, list):
                    nodes, edges = _steps_to_graph(steps_raw, data.get("trigger_type", "manual"))
                    packaged = {
                        "nodes": nodes,
                        "edges": edges,
                        "steps": steps_raw
                    }
                    steps_val = json.dumps(packaged)
                elif isinstance(steps_raw, dict):
                    steps_val = json.dumps(steps_raw)
                elif isinstance(steps_raw, str):
                    steps_val = steps_raw
                else:
                    steps_val = json.dumps([])
            fields.append("steps = ?")
            params.append(steps_val)
        if not fields:
            return False
        fields.append("updated_at = ?")
        params.append(time.time())
        params.append(workflow_id)
        with self.tx() as db:
            cur = db.execute(f"UPDATE agent_workflows SET {', '.join(fields)} WHERE id = ?", params)
            return cur.rowcount > 0

    def delete_workflow(self, workflow_id: int) -> bool:
        """워크플로우 및 관련 리뷰 데이터를 영구 삭제한다."""
        with self.tx() as db:
            db.execute("DELETE FROM workflow_reviews WHERE workflow_id = ?", (workflow_id,))
            cur = db.execute("DELETE FROM agent_workflows WHERE id = ?", (workflow_id,))
            return cur.rowcount > 0

    def fork_workflow(self, workflow_id: int, author: str = "Me", custom_name: str | None = None) -> dict | None:
        orig = self.get_workflow(workflow_id)
        if not orig:
            return None
        with self.tx() as db:
            db.execute("UPDATE agent_workflows SET forks_count = forks_count + 1 WHERE id = ?", (workflow_id,))

        name = custom_name or f"{orig.get('name', 'Workflow')} (Remix)"
        forked_id = self.create_workflow({
            "name": name,
            "description": f"Remixed from {orig.get('author', 'original')}. {orig.get('description', '')}".strip(),
            "category": orig.get("category", "automation"),
            "trigger_type": orig.get("trigger_type", "manual"),
            "steps": orig.get("steps", []),
            "nodes": orig.get("nodes", []),
            "edges": orig.get("edges", []),
            "tags": orig.get("tags", ""),
            "is_active": 1,
            "is_template": 0,
            "author": author,
            "parent_workflow_id": workflow_id,
        })
        return self.get_workflow(forked_id)

    def _vault(self):
        with self._lock:
            if not hasattr(self,'_credential_vault'):
                from ..credential_vault import CredentialVault
                self._credential_vault=CredentialVault(self.query('PRAGMA database_list')[0]['file'])
            return self._credential_vault

    def _migrate_credentials(self):
        from ..credential_vault import PREFIX
        rows=self.query('SELECT key_name,key_value FROM platform_credentials')
        if not rows:return
        vault=self._vault()
        # Validate all existing ciphertext before writing any legacy values.
        pending=[]
        for row in rows:
            if row['key_value'].startswith(PREFIX):vault.open(row['key_name'],row['key_value'])
            else:pending.append((vault.seal(row['key_name'],row['key_value']),row['key_name'],row['key_value']))
        for sealed,name,old in pending:
            self._db.execute('UPDATE platform_credentials SET key_value=? WHERE key_name=? AND key_value=?',(sealed,name,old))

    def list_credentials(self) -> list[dict]:
        rows = self.query("SELECT id, key_name, key_value, provider, description, updated_at FROM platform_credentials ORDER BY updated_at DESC")
        res = []
        for r in rows:
            val = self._vault().open(r["key_name"],r["key_value"]) if r["key_value"] else ""
            masked = f"{val[:3]}...{val[-4:]}" if len(val) > 7 else ("*" * len(val) if val else "")
            res.append({
                "id": r["id"],
                "key_name": r["key_name"],
                "masked_value": masked,
                "has_value": bool(val),
                "provider": r["provider"],
                "description": r["description"] or "",
                "updated_at": r["updated_at"]
            })
        return res

    def get_credential(self, key_name: str) -> str | None:
        rows = self.query("SELECT key_value FROM platform_credentials WHERE key_name = ?", (key_name,))
        if rows:
            return self._vault().open(key_name,rows[0]["key_value"])
        return None

    def set_credential(self, key_name: str, key_value: str, provider: str, description: str = "") -> None:
        key_value=self._vault().seal(key_name,key_value)
        now = time.time()
        with self.tx() as db:
            db.execute(
                """INSERT INTO platform_credentials (key_name, key_value, provider, description, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key_name) DO UPDATE SET
                    key_value = excluded.key_value,
                    provider = excluded.provider,
                    description = excluded.description,
                    updated_at = excluded.updated_at""",
                (key_name, key_value, provider, description, now)
            )

    def delete_credential(self, key_name: str) -> bool:
        with self.tx() as db:
            cur = db.execute("DELETE FROM platform_credentials WHERE key_name = ?", (key_name,))
            return cur.rowcount > 0

    def add_workflow_review(self, workflow_id: int, reviewer: str, rating: int, comment: str = "") -> int:
        now = time.time()
        rating = max(1, min(5, int(rating)))
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO workflow_reviews (workflow_id, reviewer, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
                (workflow_id, reviewer, rating, comment, now)
            )
            avg_row = db.execute("SELECT AVG(rating) as avg_r FROM workflow_reviews WHERE workflow_id = ?", (workflow_id,)).fetchone()
            if avg_row and avg_row["avg_r"] is not None:
                new_avg = round(float(avg_row["avg_r"]), 2)
                db.execute("UPDATE agent_workflows SET rating_avg = ? WHERE id = ?", (new_avg, workflow_id))
            return cur.lastrowid

    def list_workflow_reviews(self, workflow_id: int) -> list[dict]:
        rows = self.query(
            "SELECT id, workflow_id, reviewer, rating, comment, created_at FROM workflow_reviews WHERE workflow_id = ? ORDER BY created_at DESC",
            (workflow_id,)
        )
        return [dict(r) for r in rows]

    def seed_default_workflows(self) -> None:
        from ..workflow_templates import seed
        seed(self)


    # ---------------- Customer Requests Hub (Needs, Inquiries, Cancellations, Privacy) ----------------
    def record_customer_inquiry(self, category: str, name: str, email: str, subject: str, message: str,
                                visitor_token: str | None = None, ip: str | None = None, user_agent: str | None = None) -> str:
        from ..concierge.token_hygiene import token_reference
        visitor_token = token_reference(visitor_token)
        inquiry_id = new_id("inq")
        now = time.time()
        c_name = sanitize_text(name, max_length=100)
        c_email = sanitize_email(email) or sanitize_text(email, max_length=150)
        c_subject = sanitize_text(subject, max_length=200)
        c_message = sanitize_text(message, max_length=4000)
        with self.tx() as db:
            db.execute(
                """INSERT INTO customer_inquiries (
                    inquiry_id, created_at, updated_at, category, name, email, subject, message,
                    visitor_token, ip, user_agent, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (inquiry_id, now, now, category or "general", c_name, c_email, c_subject, c_message,
                 visitor_token, ip, user_agent)
            )
        return inquiry_id

    def list_customer_inquiries(self, status: str | None = None, category: str | None = None,
                                search: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        conds = []
        params = []
        if status and status != "all":
            conds.append("status = ?")
            params.append(status)
        if category and category != "all":
            conds.append("category = ?")
            params.append(category)
        if search:
            kw = f"%{search.strip()}%"
            conds.append("(inquiry_id LIKE ? OR name LIKE ? OR email LIKE ? OR subject LIKE ? OR message LIKE ?)")
            params.extend([kw, kw, kw, kw, kw])
        where_clause = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self.tx() as db:
            total = db.execute(f"SELECT COUNT(*) AS n FROM customer_inquiries {where_clause}", params).fetchone()["n"]
            query = f"SELECT * FROM customer_inquiries {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
            rows = [dict(r) for r in db.execute(query, params + [limit, offset]).fetchall()]
        return rows, total

    def get_customer_inquiry(self, inquiry_id: str) -> dict | None:
        with self.tx() as db:
            row = db.execute("SELECT * FROM customer_inquiries WHERE inquiry_id = ?", (inquiry_id,)).fetchone()
            return dict(row) if row else None

    def update_customer_inquiry(self, inquiry_id: str, status: str, admin_response: str | None = None,
                                resolved_by: str | None = None) -> bool:
        now = time.time()
        c_response = sanitize_text(admin_response, max_length=4000) if admin_response is not None else None
        with self.tx() as db:
            cur = db.execute("SELECT id FROM customer_inquiries WHERE inquiry_id = ?", (inquiry_id,)).fetchone()
            if not cur:
                return False
            resolved_at = now if status in ("resolved", "archived") else None
            db.execute(
                """UPDATE customer_inquiries SET
                    status = ?, admin_response = COALESCE(?, admin_response),
                    resolved_at = COALESCE(?, resolved_at), resolved_by = COALESCE(?, resolved_by),
                    updated_at = ?
                WHERE inquiry_id = ?""",
                (status, c_response, resolved_at, resolved_by, now, inquiry_id)
            )
        return True

    def record_cancellation_request(self, visitor_id: str | None = None, visitor_token_hash: str | None = None,
                                    token_masked: str | None = None, source: str = "ftc_footer",
                                    reason: str | None = None, ip: str | None = None, user_agent: str | None = None) -> str:
        request_id = new_id("cnl")
        now = time.time()
        c_reason = sanitize_text(reason, max_length=500) if reason else None
        with self.tx() as db:
            db.execute(
                """INSERT INTO cancellation_requests (
                    request_id, created_at, visitor_id, visitor_token_hash, token_masked,
                    source, reason, ip, user_agent, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'cancelled')""",
                (request_id, now, visitor_id, visitor_token_hash, token_masked, source, c_reason, ip, user_agent)
            )
        return request_id

    def list_cancellation_requests(self, status: str | None = None, search: str | None = None,
                                   limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        conds = []
        params = []
        if status and status != "all":
            conds.append("status = ?")
            params.append(status)
        if search:
            kw = f"%{search.strip()}%"
            conds.append("(request_id LIKE ? OR token_masked LIKE ? OR reason LIKE ? OR source LIKE ? OR ip LIKE ?)")
            params.extend([kw, kw, kw, kw, kw])
        where_clause = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self.tx() as db:
            total = db.execute(f"SELECT COUNT(*) AS n FROM cancellation_requests {where_clause}", params).fetchone()["n"]
            query = f"SELECT * FROM cancellation_requests {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
            rows = [dict(r) for r in db.execute(query, params + [limit, offset]).fetchall()]
        return rows, total

    def reactivate_cancellation(self, request_id: str, notes: str | None = None) -> bool:
        now = time.time()
        c_notes = sanitize_text(notes, max_length=500) if notes else None
        with self.tx() as db:
            row = db.execute("SELECT visitor_id, source FROM cancellation_requests WHERE request_id = ?", (request_id,)).fetchone()
            if not row or row['source'] == 'task_updates':
                return False
            visitor_id = row["visitor_id"]
            if visitor_id:
                db.execute("UPDATE agent_visitors SET notify = 1 WHERE id = ?", (visitor_id,))
            db.execute(
                """UPDATE cancellation_requests SET
                    status = 'reactivated', reactivated_at = ?, notes = COALESCE(?, notes)
                WHERE request_id = ?""",
                (now, c_notes, request_id)
            )
        return True

    def record_privacy_request(self, request_type: str, visitor_token_masked: str | None = None,
                               email: str | None = None, details: str | None = None,
                               ip: str | None = None, user_agent: str | None = None,
                               gpc_detected: int = 0, statutory_days: int = 45) -> str:
        from ..privacy_requests import initial_status
        status = initial_status(request_type)
        request_id = new_id("prv")
        now = time.time()
        deadline = now + (statutory_days * 86400)
        c_details = sanitize_text(details, max_length=2000) if details else None
        c_email = sanitize_email(email) or (sanitize_text(email, max_length=150) if email else None)
        proof_data = f"{request_id}:{now}:{request_type}:{c_email}:{ip}"
        proof_hash = hashlib.sha256(proof_data.encode("utf-8")).hexdigest()[:24]
        with self.tx() as db:
            db.execute(
                """INSERT INTO privacy_requests (
                    request_id, created_at, request_type, visitor_token_masked, email, details,
                    ip, user_agent, gpc_detected, status, statutory_deadline, completed_at, proof_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, now, request_type, visitor_token_masked, c_email, c_details,
                 ip, user_agent, gpc_detected, status, deadline, None, proof_hash)
            )
        return request_id

    def list_privacy_requests(self, status: str | None = None, request_type: str | None = None,
                              search: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        conds = []
        params = []
        if status and status != "all":
            conds.append("status = ?")
            params.append(status)
        if request_type and request_type != "all":
            conds.append("request_type = ?")
            params.append(request_type)
        if search:
            kw = f"%{search.strip()}%"
            conds.append("(request_id LIKE ? OR email LIKE ? OR visitor_token_masked LIKE ? OR details LIKE ? OR proof_hash LIKE ?)")
            params.extend([kw, kw, kw, kw, kw])
        where_clause = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self.tx() as db:
            total = db.execute(f"SELECT COUNT(*) AS n FROM privacy_requests {where_clause}", params).fetchone()["n"]
            query = f"SELECT * FROM privacy_requests {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
            rows = [dict(r) for r in db.execute(query, params + [limit, offset]).fetchall()]
        return rows, total

    def update_privacy_request(self, request_id: str, status: str, notes: str | None = None,
                               proof_hash: str | None = None) -> bool:
        from ..privacy_requests import validate_resolution
        now = time.time()
        with self.tx() as db:
            cur = db.execute("SELECT id, status FROM privacy_requests WHERE request_id = ?", (request_id,)).fetchone()
            if not cur:
                return False
            validate_resolution(cur['status'], status, notes, proof_hash)
            completed_at = now if status == "completed" else None
            db.execute(
                """UPDATE privacy_requests SET
                    status = ?, notes = COALESCE(?, notes), proof_hash = COALESCE(?, proof_hash),
                    completed_at = COALESCE(?, completed_at)
                WHERE request_id = ?""",
                (status, notes, proof_hash, completed_at, request_id)
            )
        return True

    def get_customer_requests_summary(self) -> dict:
        with self.tx() as db:
            needs_total = db.execute("SELECT COUNT(*) AS n FROM needs").fetchone()["n"]
            needs_active = db.execute("SELECT COUNT(*) AS n FROM needs WHERE status IN ('watching', 'active')").fetchone()["n"]
            needs_matched = db.execute("SELECT COUNT(*) AS n FROM needs WHERE status = 'matched'").fetchone()["n"]

            inq_total = db.execute("SELECT COUNT(*) AS n FROM customer_inquiries").fetchone()["n"]
            inq_pending = db.execute("SELECT COUNT(*) AS n FROM customer_inquiries WHERE status = 'pending'").fetchone()["n"]
            inq_in_progress = db.execute("SELECT COUNT(*) AS n FROM customer_inquiries WHERE status = 'in_progress'").fetchone()["n"]
            inq_resolved = db.execute("SELECT COUNT(*) AS n FROM customer_inquiries WHERE status IN ('resolved', 'archived')").fetchone()["n"]

            cnl_total = db.execute("SELECT COUNT(*) AS n FROM cancellation_requests").fetchone()["n"]
            cnl_cancelled = db.execute("SELECT COUNT(*) AS n FROM cancellation_requests WHERE status = 'cancelled'").fetchone()["n"]
            cnl_reactivated = db.execute("SELECT COUNT(*) AS n FROM cancellation_requests WHERE status = 'reactivated'").fetchone()["n"]

            prv_total = db.execute("SELECT COUNT(*) AS n FROM privacy_requests").fetchone()["n"]
            prv_completed = db.execute("SELECT COUNT(*) AS n FROM privacy_requests WHERE status = 'completed'").fetchone()["n"]
            prv_gpc = db.execute("SELECT COUNT(*) AS n FROM privacy_requests WHERE gpc_detected = 1").fetchone()["n"]

        return {
            "needs": {
                "total": needs_total,
                "active": needs_active,
                "matched": needs_matched,
            },
            "inquiries": {
                "total": inq_total,
                "pending": inq_pending,
                "in_progress": inq_in_progress,
                "resolved": inq_resolved,
            },
            "cancellations": {
                "total": cnl_total,
                "cancelled": cnl_cancelled,
                "reactivated": cnl_reactivated,
            },
            "privacy": {
                "total": prv_total,
                "completed": prv_completed,
                "gpc_count": prv_gpc,
            }
        }


