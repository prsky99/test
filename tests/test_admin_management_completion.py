"""Management completion uses real isolated handlers and synthetic customer data."""

# ruff: noqa: F401,F811
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import FastAPI
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_admin_control import operations, case_body
from tests.test_customer_organizations import orgs
from tests.test_customer_identity import customer
from tests.test_front_workflow_browser import browser
from tests.test_workspace_admin_browser import browser_context
from tests.test_admin_specialist_panels import shell
from agent_market.workspace_admin_service import router_for as operation_routes
from agent_market.customer_credit_service import router_for as credit_routes


BASE = "/admin/api/v2/catalog-tools"


def test_catalog_aliases_keep_individual_roles_reason_ssrf_and_secret_redaction(
    private_api,
):
    w = private_api
    c = w.client
    h = w.headers["owner"]
    reason = {**h, "X-Admin-Reason": quote("Synthetic catalog security review")}
    for suffix in (
        "/test-reports",
        "/credentials",
        "/capability-contracts",
        "/connections/" + str(w.rid),
    ):
        r = c.get(BASE + suffix, headers=h)
        assert r.status_code == 200, r.text
        assert (
            r.headers["cache-control"] == "no-store"
            and c.get(BASE + suffix).status_code == 401
        )
    assert c.get(BASE + "/credentials", headers=w.headers["editor"]).status_code == 403
    assert c.get(BASE + "/test-reports", headers=w.headers["editor"]).status_code == 200
    assert (
        c.get(
            BASE + "/credentials",
            headers={
                "X-Dashboard": "1",
                "Authorization": "Bearer isolated-machine-token",
            },
        ).status_code
        == 401
    )
    assert (
        c.post(
            BASE + "/register/inspect",
            headers=h,
            json={"url": "http://127.0.0.1/private"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            BASE + "/register/inspect",
            headers=reason,
            json={"url": "http://127.0.0.1/private"},
        ).status_code
        == 400
    )
    assert not w.calls
    secret = "synthetic-local-credential-only-987654"
    r = c.post(
        BASE + "/credentials",
        headers=reason,
        json={
            "key_name": "test_only",
            "key_value": secret,
            "provider": "synthetic",
            "description": "Isolated fixture",
        },
    )
    assert r.status_code == 200, r.text
    data = c.get(BASE + "/credentials", headers=h).json()
    assert secret not in json.dumps(data)
    logs = w.store.query(
        "SELECT details FROM admin_audit_logs WHERE action='CATALOG_TOOL_CHANGE'"
    )
    assert logs and secret not in str(logs)
    assert c.get(BASE + "/users", headers=h).status_code == 404


def test_account_form_requests_review_without_creating_the_account(
    private_api, browser
):
    from playwright.sync_api import expect
    from agent_market.workspace_admin_events import migrate

    w = private_api
    migrate(w.store, w.store._workspace_admin_identity_key)
    client, context, page, errors, external = browser_context(
        browser, w.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.headers["owner"]["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/system/accounts")
        page.get_by_role("button", name="관리자 생성 요청", exact=True).click()
        d = page.locator(".adm-drawer")
        d.get_by_label("관리자 아이디").fill("synthetic_new_staff")
        d.get_by_label("표시 이름").fill("Synthetic reviewed staff")
        d.get_by_label("초기 비밀번호").fill("Synthetic-only-password-987")
        d.get_by_label("계정 변경 사유").fill("Isolated reviewed creation request")
        d.get_by_label("대상 계정·역할·변경 내용을 검토했습니다").check()
        d.get_by_role("button", name="승인 요청 등록", exact=True).click()
        expect(d).to_contain_text("승인 대기")
        assert (
            w.store.query(
                "SELECT COUNT(*) FROM admin_users WHERE username='synthetic_new_staff'"
            )[0][0]
            == 0
        )
        assert (
            not d.locator("input[type=password]").count()
            and not errors
            and not external
        )
    finally:
        context.close()
        client.close()


def test_catalog_tool_form_ssrf_failure_is_visible_and_not_retried(
    private_api, browser
):
    from playwright.sync_api import expect

    w = private_api
    client, context, page, errors, external = browser_context(
        browser, w.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.headers["owner"]["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/catalog/tools?view=register")
        page.get_by_label("에이전트 HTTPS 주소").fill("http://127.0.0.1/private")
        page.get_by_role("button", name="주소 조사", exact=True).click()
        d = page.get_by_role("dialog", name="등록 주소 조사")
        d.get_by_label("변경 사유").fill("Reject isolated loopback address")
        d.get_by_role("button", name="검토한 요청 실행", exact=True).click()
        expect(page.locator("main")).to_contain_text("다시 전송하지 않았습니다.")
        assert not w.calls and not errors and not external
    finally:
        context.close()
        client.close()


def test_native_support_create_link_history_and_incident_workflows(operations, browser):
    from playwright.sync_api import expect

    w = operations
    app = FastAPI()
    app.include_router(operation_routes(w.core, w.access, core=w.ops))
    app.include_router(credit_routes(w.core, w.access, admin=True))
    shell(SimpleNamespace(app=app, actor=w.staff[1]))
    client, context, page, errors, external = browser_context(
        browser, app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps("a" * 64) + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/customers/customers")
        page.locator(".adm-table tbody tr").first.click()
        d = page.locator(".adm-drawer")
        expect(d).to_contain_text("가입 동의·크레딧 원장")
        d.get_by_role("button", name="고객 대응 생성", exact=True).click()
        d = page.locator(".adm-drawer")
        d.get_by_label("케이스 제목").fill("Synthetic management parity")
        d.get_by_label("고객에게 보이는 첫 안내").fill(
            "We are reviewing your selected request."
        )
        check = d.get_by_label("대상 고객·내용·공개 범위를 확인했습니다")
        check.check()
        d.get_by_role("button", name="확인한 내용 저장", exact=True).click()
        expect(d).not_to_be_visible()
        cases = w.ops.cases(w.staff[1])["cases"]
        assert len(cases) == 1
        page.goto("https://admin.test/admin/next#/customers/cases")
        page.get_by_text("Synthetic management parity", exact=True).click()
        d = page.locator(".adm-drawer")
        expect(d.get_by_label("담당 관리자 ID")).to_be_visible()
        expect(d.get_by_role("button", name="기존 고객 요청 연결")).to_be_visible()
        d.get_by_role("button", name="닫기", exact=True).click()
        page.goto("https://admin.test/admin/next#/security/incidents")
        page.get_by_role("button", name="장애 등록", exact=True).click()
        d = page.locator(".adm-drawer")
        d.get_by_label("현상·조치 근거").fill("Synthetic outage observed and isolated.")
        d.get_by_label("대상 고객·내용·공개 범위를 확인했습니다").check()
        d.get_by_role("button", name="확인한 내용 저장", exact=True).click()
        expect(d).not_to_be_visible()
        assert w.ops.incidents(w.staff[1])["incidents"][0]["status"] == "open"
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_completed_privacy_request_keeps_status_and_allows_reviewed_evidence_amendment(
    private_api, browser
):
    from playwright.sync_api import expect

    w = private_api
    identity = w.store.record_privacy_request(
        "ccpa_opt_out", details="Synthetic reviewed preference"
    )
    assert w.store.update_privacy_request(
        identity,
        status="completed",
        notes="Synthetic initial evidence reviewed",
        proof_hash="a" * 64,
    )
    client, context, page, errors, external = browser_context(
        browser, w.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.headers["owner"]["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/customers/requests")
        page.get_by_label("요청 종류").select_option("privacy")
        page.get_by_text("ccpa_opt_out", exact=True).click()
        d = page.locator(".adm-drawer")
        expect(d.get_by_label("검토 메모")).to_have_value(
            "Synthetic initial evidence reviewed"
        )
        expect(d.get_by_label("완료 근거 SHA-256")).to_have_value("a" * 64)
        assert (
            d.get_by_label("처리 상태", exact=True).locator("option:enabled").count()
            == 1
        )
        d.get_by_label("검토 메모").fill(
            "Synthetic amended evidence independently reviewed"
        )
        d.get_by_label("변경 사유", exact=True).fill(
            "Amend reviewed completion evidence"
        )
        d.get_by_role("button", name="저장", exact=True).click()
        expect(d).not_to_be_visible()
        row = w.store.list_privacy_requests(search=identity)[0][0]
        assert (
            row["status"] == "completed"
            and row["notes"] == "Synthetic amended evidence independently reviewed"
        )
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_catalog_test_ui_sends_one_reviewed_mcp_input(
    private_api, browser, monkeypatch
):
    import httpx
    import agent_market.gateway.dashboard as dashboard
    from playwright.sync_api import expect

    w = private_api
    # A public literal avoids DNS in this mock-only transport; no socket is opened.
    with w.store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?',('https://8.8.8.8/synthetic-mcp',w.rid))
    calls = []

    def remote(request):
        calls.append(json.loads(request.content))
        return w.remote.handle_request(request)

    monkeypatch.setattr(
        dashboard,
        "public_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(remote)),
    )
    client, context, page, errors, external = browser_context(
        browser, w.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.headers["owner"]["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/catalog/tools?agent=" + str(w.rid))
        page.get_by_role("button", name="도구 정보 확인",exact=True).click()
        d=page.locator('dialog.adm-dialog')
        d.locator('textarea').fill('Synthetic tool schema inspection')
        d.get_by_role('button',name='도구 정보 확인',exact=True).click()
        page.get_by_label('query',exact=True).fill('Synthetic reviewed battery research')
        before=len([r for r in calls if r.get('method')=='tools/call'])
        page.get_by_role("button", name="검토한 입력 1회 실행", exact=True).click()
        expect(d).to_contain_text("Synthetic reviewed battery research")
        d.locator('textarea').fill("Synthetic exact input verification")
        d.get_by_role("button", name="검토한 입력 1회 실행", exact=True).click()
        expect(page.locator("main")).to_contain_text("테스트 응답을 받았습니다.")
        executions=[r for r in calls if r.get('method')=='tools/call']
        assert len(executions)==before+1
        assert executions[-1]['params']['arguments']['query']=='Synthetic reviewed battery research'
        assert not errors and not external
    finally:
        context.close()
        client.close()
