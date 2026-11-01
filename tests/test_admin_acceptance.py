"""Fixed step-8 evidence, graph and operator boundaries on isolated data."""

# ruff: noqa: F401,F811
import json
import time

import pytest
from agent_market.gateway import admin_auth
from agent_market.workspace_admin_insights import aggregate
from tests.test_dashboard import dash
from tests.test_admin_reviewed_commands import reviewed
from tests.test_front_workflow_browser import browser
from tests.test_workspace_admin_browser import browser_context
from tests.test_admin_public_operations import graph

BASE = "/admin/api/v2/insights"


def staff(world, role):
    with world.store.tx() as db:
        user = admin_auth.create_admin_user(
            db, "acceptance-" + role, "Synthetic-acceptance-password", role, role
        )
        token = admin_auth.create_session(
            db, user["id"], user["username"], user["role"], user["name"]
        )
    return user, {"X-Dashboard": "1", "Authorization": "Bearer " + token}


def test_sample_metrics_do_not_fabricate_pacing_or_baseline_alerts():
    now = time.time()
    values = []
    for index in range(35):
        created = now - (index * 5 if index < 25 else 700)
        values.append(
            {
                "resource_id": 7,
                "protocol": "mcp",
                "source": "workspace",
                "status": "failed",
                "error_code": "UPSTREAM_TIMEOUT",
                "created": created,
                "dispatched": created + 0.05,
                "finished": created + 9,
                "elapsed_ms": 9000,
            }
        )
    data = aggregate(values, 1, now)
    assert data["sample_complete"] and not data["pacing"]["available"]
    assert data["protocols"][0]["pre_dispatch_p95_ms"] == pytest.approx(50, abs=0.01)
    assert {r["code"] for r in data["alerts"]} == {
        "LOW_SUCCESS_5M",
        "HIGH_LATENCY_5M",
    }  # 25/10 is not triple
    limited = aggregate(values * 144, 1, now)
    assert not limited["sample_complete"] and limited["sample_size"] == 5000
    assert not any(r["code"] == "ERROR_GROWTH_10M" for r in limited["alerts"])
    assert aggregate([], 24, now)["protocols"] == []


def test_native_evidence_excludes_customer_payloads_and_internal_bindings(reviewed):
    world, c, h = reviewed
    rid = world.store.query("SELECT id FROM resources LIMIT 1")[0]["id"]
    now = time.time()
    with world.store.tx() as db:
        db.execute(
            "INSERT INTO platform_operations(id,kind,source,protocol,resource_id,status,created) VALUES('ex_synthetic','execution','workspace','mcp',?,'succeeded',?)",
            (rid, now),
        )
        db.execute(
            "INSERT INTO platform_attempts(id,operation_id,ordinal,resource_id,protocol,status,created,finished,elapsed_ms) VALUES('attempt_synthetic','ex_synthetic',1,?,'mcp','succeeded',?,?,5)",
            (rid, now, now),
        )
    response = c.get(BASE + "/agents/" + str(rid), headers=h)
    assert response.status_code == 200, response.text
    assert response.json()["calls"][0]["source"] == "workspace"
    assert not any(
        key in response.text
        for key in ("input", "output", "credential_refs", "binding_hash", "customer_id")
    )
    assert "no-store" in response.headers["cache-control"]
    _, op = staff(world, "operator")
    _, viewer = staff(world, "viewer")
    assert "audit" not in c.get(BASE + "/agents/" + str(rid), headers=op).json()
    assert c.get(BASE + "/gateway", headers=viewer).status_code == 403
    assert (
        c.get(
            BASE + "/gateway",
            headers={"X-Dashboard": "1", "Authorization": "Bearer secret"},
        ).status_code
        == 401
    )
    assert (
        c.get(
            BASE + "/gateway", headers={**h, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_notes_are_private_audited_and_operator_cannot_write_them(reviewed):
    world, c, h = reviewed
    rid = world.store.query("SELECT id FROM resources LIMIT 1")[0]["id"]
    value = {
        "note": "<img src=x onerror=alert(1)> Internal review",
        "reason": "Synthetic internal note evidence",
    }
    response = c.post(BASE + "/agents/" + str(rid) + "/notes", headers=h, json=value)
    assert response.status_code == 200, response.text
    evidence = c.get(BASE + "/agents/" + str(rid), headers=h).json()["audit"]
    assert evidence[0]["note"] == value["note"]
    _, op = staff(world, "operator")
    assert (
        c.post(
            BASE + "/agents/" + str(rid) + "/notes", headers=op, json=value
        ).status_code
        == 403
    )
    assert (
        c.post(
            BASE + "/agents/" + str(rid) + "/notes",
            headers=h,
            json={**value, "note": "Bearer secret-token"},
        ).status_code
        == 400
    )


def test_operator_assignment_has_no_customer_content_and_cas_blocks_stale_write(
    reviewed,
):
    world, c, h = reviewed
    user, op = staff(world, "operator")
    _, viewer = staff(world, "viewer")
    now = time.time()
    with world.store.tx() as db:
        db.execute(
            "INSERT INTO workspace_admin_cases VALUES('case_synthetic','cu_private','ws_private','new','urgent',NULL,1,?,?,NULL,'Private customer subject')",
            (now, now),
        )
    response = c.get(BASE + "/assignments", headers=op)
    assert response.status_code == 200, response.text
    assert not any(
        value in response.text
        for value in (
            "cu_private",
            "ws_private",
            "subject",
            "message",
            "Private customer",
        )
    )
    body = {
        "revision": 1,
        "assigned_to": user["id"],
        "reason": "Synthetic operator assignment",
    }
    assert (
        c.post(
            BASE + "/assignments/case_synthetic",
            headers=op,
            json={**body, "message": "forbidden"},
        ).status_code
        == 400
    )
    applied = c.post(BASE + "/assignments/case_synthetic", headers=op, json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision"] == 2
    assert (
        c.post(BASE + "/assignments/case_synthetic", headers=op, json=body).status_code
        == 409
    )
    assert c.get("/admin/api/v2/requests/inquiries", headers=op).status_code == 403
    assert c.get(BASE + "/assignments", headers=viewer).status_code == 403
    with world.store.tx() as db:
        db.execute("UPDATE admin_users SET active=0 WHERE id=?", (user["id"],))
    assert c.post(
        BASE + "/assignments/case_synthetic", headers=op, json={**body, "revision": 2}
    ).status_code in (401, 403)


def test_operator_cannot_expand_check_and_pause_into_privileged_actions(reviewed):
    world, c, h = reviewed
    _, op = staff(world, "operator")
    rid = world.store.query("SELECT id FROM resources LIMIT 1")[0]["id"]
    for action in ("activate", "deactivate"):
        assert (
            c.post(
                "/admin/api/v2/catalog/agents/" + str(rid) + "/actions",
                headers=op,
                json={
                    "action": action,
                    "reason": "Forbidden operator mutation",
                    "expected_active": True,
                },
            ).status_code
            == 403
        )
    assert (
        c.post(
            "/admin/api/v2/catalog/collector/actions",
            headers=op,
            json={"action": "rescan", "reason": "Forbidden collector expansion"},
        ).status_code
        == 400
    )
    # The isolated collector is synthetic; the original pause/resume handler runs.
    pause = c.post(
        "/admin/api/v2/catalog/collector/actions",
        headers=op,
        json={"action": "pause", "reason": "Synthetic operator pause"},
    )
    assert pause.status_code == 200, pause.text
    assert pause.json()["result"]["paused"] is True
    resume = c.post(
        "/admin/api/v2/catalog/collector/actions",
        headers=op,
        json={"action": "resume", "reason": "Synthetic operator resume"},
    )
    assert resume.status_code == 200 and resume.json()["result"]["paused"] is False
    logs = c.get("/admin/api/audit/logs?limit=10", headers=h).json()["logs"]
    assert any(r["action"] == "COLLECTOR_ACTION_INTENT" for r in logs)


def test_public_graph_state_never_returns_inputs_or_outputs(reviewed):
    world, c, h = reviewed
    wid = world.store.create_workflow(graph(world))
    now = time.time()
    with world.store.tx() as db:
        db.execute(
            "INSERT INTO workflow_runs(id,workflow_id,digest,snapshot,actor,source,status,created,result) VALUES('wr_synthetic',?,'digest','private snapshot','customer','public','succeeded',?,'private output')",
            (wid, now),
        )
        db.execute(
            "INSERT INTO workflow_node_runs(run_id,node_id,status,input,output) VALUES('wr_synthetic','lookup','succeeded','private input','private output')"
        )
    response = c.get(BASE + "/workflows/" + str(wid) + "/state", headers=h)
    assert response.status_code == 200, response.text
    assert response.json()["steps"][0]["status"] == "succeeded"
    assert response.json()["agents"] and set(response.json()["agents"][0]) == {
        "id",
        "kind",
        "active",
        "health_status",
        "eval_grade",
    }
    assert "private" not in response.text
    _, op = staff(world, "operator")
    assert (
        c.get(BASE + "/workflows/" + str(wid) + "/state", headers=op).status_code == 403
    )


def test_native_graph_edit_preserves_draft_review_and_blocks_cycles(reviewed, browser):
    from playwright.sync_api import expect

    world, c, h = reviewed
    _, context, page, errors, external = browser_context(
        browser, world.app, "https://admin.test"
    )
    token = next(v[7:] for k, v in h.items() if k.lower() == "authorization")
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps(token) + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/public/templates")
        page.get_by_role("button", name="새 공개용 초안", exact=True).click()
        drawer = page.locator(".adm-drawer")
        value = graph(world)
        drawer.get_by_label("영어 이름", exact=True).fill(value["name"])
        editor = drawer.get_by_label("노드·연결 JSON", exact=True)
        editor.fill(json.dumps({"nodes": value["nodes"], "edges": []}))
        editor.dispatch_event("change")
        expect(drawer.get_by_role("img", name="에이전트 연결 흐름")).to_be_visible()
        drawer.get_by_label("새 단계 에이전트 ID").fill(
            str(value["nodes"][0]["resource_id"])
        )
        drawer.get_by_label("새 단계 프로토콜").select_option("mcp")
        drawer.get_by_label("새 단계 도구").fill("search")
        drawer.get_by_role("button", name="에이전트 단계 추가", exact=True).click(
            timeout=5000
        )
        assert len(json.loads(editor.input_value())["nodes"]) == 2
        drawer.get_by_label("연결 시작 단계").select_option(index=0)
        drawer.get_by_label("연결 대상 단계").select_option(index=1)
        drawer.get_by_role("button", name="단계 연결", exact=True).click()
        assert len(json.loads(editor.input_value())["edges"]) == 1
        drawer.get_by_label("연결 시작 단계").select_option(index=1)
        drawer.get_by_label("연결 대상 단계").select_option(index=0)
        drawer.get_by_role("button", name="단계 연결", exact=True).click()
        expect(drawer).to_contain_text("순환 연결은 허용하지 않습니다.")
        assert len(json.loads(editor.input_value())["edges"]) == 1
        drawer.get_by_role("button", name="1. Lookup · 실행 기록 없음", exact=True).click()
        drawer.get_by_label("선택 단계 영어 이름", exact=True).fill("Research Lookup")
        drawer.get_by_label("선택 단계 입력 JSON", exact=True).fill(
            '{"query":"public reference"}'
        )
        drawer.get_by_role("button", name="선택 단계 변경안 반영", exact=True).click()
        assert (
            json.loads(editor.input_value())["nodes"][0]["data"]["input"]["query"]
            == "public reference"
        )
        drawer.get_by_role("button", name="비공개 초안 저장", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic graph draft save"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text("변경 결과")
        assert (
            world.store.query(
                "SELECT is_template FROM agent_workflows WHERE name=?", (value["name"],)
            )[0]["is_template"]
            == 0
        )
        assert not errors and not external
    finally:
        context.close()


def test_native_operator_assignment_and_evidence_are_safe_text(reviewed, browser):
    from playwright.sync_api import expect

    world, c, h = reviewed
    user, op = staff(world, "operator")
    now = time.time()
    with world.store.tx() as db:
        db.execute(
            "INSERT INTO workspace_admin_cases VALUES('case_ui','private_customer','private_workspace','new','normal',NULL,1,?,?,NULL,'private subject')",
            (now, now),
        )
    _, context, page, errors, external = browser_context(
        browser, world.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(op["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/customers/assignments")
        expect(
            page.get_by_role("table", name="본문 없는 케이스 배정 목록")
        ).to_contain_text("case_ui")
        assert "private_customer" not in page.locator("main").inner_text()
        page.get_by_text("case_ui", exact=True).click()
        page.get_by_label("담당 직원 ID", exact=True).fill(str(user["id"]))
        page.get_by_role("button", name="배정 변경", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic UI operator assignment"
        )
        dialog.get_by_role("button", name="변경", exact=True).click()
        expect(
            page.get_by_role("table", name="본문 없는 케이스 배정 목록")
        ).to_contain_text(str(user["id"]))
        assert not errors and not external
    finally:
        context.close()


def test_native_insights_notes_and_gateway_chart_use_current_safe_records(
    reviewed, browser
):
    from playwright.sync_api import expect

    world, c, h = reviewed
    rid = world.store.query("SELECT id FROM resources LIMIT 1")[0]["id"]
    _, context, page, errors, external = browser_context(
        browser, world.app, "https://admin.test"
    )
    token = next(v[7:] for k, v in h.items() if k.lower() == "authorization")
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps(token) + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/catalog?agent=" + str(rid))
        page.get_by_role("tab", name="호출·버전·증거·감사", exact=True).click()
        expect(page.get_by_role("table", name="기록된 연결 버전")).to_be_visible()
        page.get_by_label("새 내부 메모", exact=True).fill(
            "<img src=x onerror=alert(1)> Synthetic review"
        )
        page.get_by_role("button", name="내부 메모 기록", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic safe note audit"
        )
        dialog.get_by_role("button", name="기록", exact=True).click()
        expect(page.get_by_role("table", name="에이전트 관리 기록")).to_contain_text(
            "Synthetic review"
        )
        assert not page.locator(".adm-drawer img").count()
        page.goto("https://admin.test/admin/next#/gateway")
        expect(
            page.get_by_role("img", name="시간대별 실제 호출 표본 그래프")
        ).to_be_visible()
        expect(page.locator("main")).to_contain_text("페이싱 전용 시간이 아닙니다.")
        assert not errors and not external
    finally:
        context.close()
