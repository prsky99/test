"""Real private contracts through renewal aliases; only isolated mock providers."""

# ruff: noqa: F401,F811
import json
from types import SimpleNamespace
from urllib.parse import quote
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_access import WorkspaceAccess, SessionActor
from agent_market.workspace_admin_specialists import router_for as aliases, RENEWAL
from agent_market.workspace_service import router_for as workspaces
from agent_market.workspace_growth_service import router_for as growth_routes
from agent_market.advancement_service import router_for as advancement_routes
from agent_market.workflow_product_composer_service import router_for as product_routes
from agent_market.workflows import runtime_for
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_growth import growth, review_body, support_body
from tests.test_workspace_typed_flows import typed_world, routing, run, save
from tests.test_workflow_product_composer import product_world
from tests.test_admin_specialist_panels import shell
from tests.test_workspace_admin_browser import browser_context
from tests.test_front_workflow_browser import browser

# These fixtures retain signed TEST_UNIT transport wholly inside a synthetic DB.
from tests.test_provider_claims import provider
from tests.test_workspace_agreements import agreement
from tests.test_workspace_sandbox_payments import sandbox


@pytest.fixture(params=["growth", "advancement", "product"])
def panel(request):
    kind = request.param
    if kind == "growth":
        g = request.getfixturevalue("growth")
        w = g.w
        ws = w.ws
        access = w.access
        execution = w.execution
        raw = w.raw
        source = growth_routes(g.factory, g.support)
        w.growth = g
        reads = ["/app-factory/options", "/sdk-lifecycle", "/support-outcomes"]
        write = "/app-factory/reviews"
    elif kind == "product":
        x = request.getfixturevalue("product_world")
        w = x.w
        ws = x.ws
        access = x.access
        execution = x.execution
        raw = w.headers["owner"]["Authorization"][7:]
        w.actor = x.actor
        w.product = x
        source = product_routes(x.composer)
        reads = ["/product-composer/options"]
        write = "/product-composer/prepare"
    else:
        w = request.getfixturevalue("private_api")
        ws = w.ws["id"]
        access = WorkspaceAccess(w.store, runtime_for(w.store).key)
        execution = None
        raw = w.headers["owner"]["Authorization"][7:]
        w.actor = SessionActor(1, session_reference(raw))
        source = advancement_routes(access)
        reads = [
            "/advancement/ledger/options",
            "/advancement/ledger",
            "/advancement/runtime-meter",
            "/advancement/support",
            "/advancement/support/assistant",
            "/advancement/readiness",
            "/advancement/operating-preparation",
        ]
        write = "/advancement/ledger/approve"
    app = FastAPI()
    app.include_router(
        workspaces(
            w.store, runtime_for(w.store).key, access=access, execution=execution
        )
    )
    app.include_router(source)
    app.include_router(aliases(w.store, source))
    shell(SimpleNamespace(app=app, actor=w.actor))
    p = SimpleNamespace(
        w=w,
        app=app,
        ws=ws,
        raw=raw,
        kind=kind,
        reads=reads,
        write=write,
        base=RENEWAL + "/" + ws,
        access=access,
        headers={"Authorization": "Bearer " + raw, "X-Dashboard": "1"},
    )
    p.reason = {
        **p.headers,
        "X-Admin-Reason": quote("Synthetic growth migration verification"),
    }
    with TestClient(app, base_url="https://admin.test") as client:
        p.client = client
        yield p


def test_aliases_membership_origin_reason_audit_no_dispatch(panel):
    p = panel
    c = p.client
    before = len(p.w.calls)
    for suffix in p.reads:
        r = c.get(p.base + suffix, headers=p.headers)
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        assert c.get(p.base + suffix).status_code == 401
        assert (
            c.get(
                (p.base + suffix).replace(p.ws, "ws_" + "f" * 32), headers=p.headers
            ).status_code
            == 404
        )
    assert c.post(p.base + p.write, headers=p.headers, json={}).status_code == 400
    assert c.post(
        p.base + p.write, headers={**p.reason, "Origin": "https://evil.test"}, json={}
    ).status_code in (401, 403)
    r = c.post(p.base + p.write, headers=p.reason, json={})
    assert r.status_code == 400, r.text
    rows = p.w.store.query(
        "SELECT status,details FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'"
    )
    assert {r[0] for r in rows} == {"REQUESTED", "FAILED"} and p.raw not in str(rows)
    assert c.post(p.base + "/members", headers=p.reason, json={}).status_code == 404
    assert c.post(p.base + "/drafts", headers=p.reason, json={}).status_code == 404
    assert len(p.w.calls) == before


def test_revoked_workspace_blocks_previous_alias(panel):
    p = panel
    revision = p.w.store.query(
        "SELECT revision FROM organization_workspaces WHERE id=?", (p.ws,)
    )[0][0]
    p.access.set_active(p.ws, {"active": False, "revision": revision}, p.w.actor)
    assert p.client.get(p.base + p.reads[0], headers=p.headers).status_code == 404
    body = (
        review_body(p.w.growth)
        if p.kind == "growth"
        else {"resource_id": p.w.rid, "input": p.w.product.inputs}
        if p.kind == "product"
        else {
            "operation_id": "slop_" + "1" * 32,
            "asset": "TEST_UNIT",
            "units": 1,
            "authorized": True,
            "notice": "workspace-shadow-accounting-v1",
        }
    )
    assert (
        p.client.post(p.base + p.write, headers=p.reason, json=body).status_code == 404
    )


def test_desktop_review_save_policy_and_single_test(panel, browser):
    from playwright.sync_api import expect

    p = panel
    w = p.w
    before = len(w.calls)
    client, context, page, errors, external = browser_context(
        browser, p.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps(p.raw) + ");"
    )
    if hasattr(w, "now"):
        context.add_init_script("Date.now=()=>" + str(w.now * 1000) + ";")
    names = {
        "growth": "앱 구성·SDK·지원 결과",
        "advancement": "운영 시뮬레이션·초안 지원",
        "product": "계약 기반 제품 비교",
    }
    try:
        page.goto("https://admin.test/admin/next#/customers/specialists")
        page.get_by_label("직원 워크스페이스", exact=True).select_option(p.ws)
        page.get_by_role("button", name=names[p.kind] + " 열기", exact=True).click()
        d = page.locator("dialog[open]")
        expect(d).to_be_visible()
        reason = d.get_by_label("전문 패널 변경 사유")
        if p.kind == "growth":
            expect(d).to_contain_text("현재 비공개 기록을 조회했습니다.")
            d.locator("#factoryTemplate").select_option("documentation_crosscheck")
            d.locator("#factoryPurpose").fill("Current reference documentation")
            for key, rid in zip(("factoryAgentFirst", "factoryAgentSecond"), w.ids[:2]):
                d.locator("#" + key).fill(str(rid))
            d.locator("#factoryPrepare").click()
            expect(reason).to_be_focused()
            reason.fill("Review and save synthetic application graph")
            d.locator("#factoryPrepare").click()
            expect(d).to_contain_text("구성을 검토하세요.")
            d.locator("#factorySaveConsent").check()
            d.locator("#factoryName").fill("Revised synthetic graph")
            expect(d.locator("#factorySaveConsent")).not_to_be_checked()
            expect(d.locator("#factorySave")).to_be_disabled()
            d.locator("#factoryPrepare").click()
            expect(d).to_contain_text("구성을 검토하세요.")
            d.locator("#factorySaveConsent").check()
            d.locator("#factorySave").click()
            expect(d).to_contain_text("Saved private workflow")
            d.get_by_role("button", name="SDK 정책", exact=True).click()
            expect(d.locator("#sdkPolicyApply")).to_be_visible()
            d.locator("#sdkPolicyConsent").check()
            d.locator("#sdkPolicyMinutes").fill("60")
            expect(d.locator("#sdkPolicyConsent")).not_to_be_checked()
            expect(d.locator("#sdkPolicyAccepting")).to_be_checked()
            d.locator("#sdkPolicyConsent").check()
            d.locator("#sdkPolicyApply").click()
            expect(d).to_contain_text("revision 1")
            d.get_by_role("button", name="지원 결과", exact=True).click()
            expect(d.locator("#supportRecord")).to_be_visible()
            assert len(w.calls) == before
        elif p.kind == "advancement":
            consent = d.get_by_label(
                "이 시뮬레이션 작업만 승인합니다. 결제 동의가 아닙니다.", exact=True
            )
            consent.check()
            d.get_by_role("button", name="시뮬레이션 승인", exact=True).click()
            expect(reason).to_be_focused()
            expect(consent).to_be_checked()
            reason.fill("Synthetic private simulation and draft review")
            d.get_by_label("승인할 정수 단위", exact=True).fill("12")
            expect(consent).not_to_be_checked()
            consent.check()
            d.get_by_role("button", name="시뮬레이션 승인", exact=True).click()
            expect(d).to_contain_text("approved 12")
            d.get_by_label(
                "이 시뮬레이션 이벤트를 검토하고 한 번만 승인합니다."
            ).check()
            d.get_by_role("button", name="시뮬레이션 결과 기록", exact=True).click()
            expect(d).to_contain_text("settled 12")
            d.get_by_role("button", name="실행 시뮬레이션", exact=True).click()
            enabled = d.get_by_label(
                "이 워크스페이스의 새로 승인된 비공개 실행에 시뮬레이션을 적용합니다."
            )
            enabled.check()
            d.get_by_label("성공한 논리 실행당 TEST_UNIT").fill("2")
            expect(enabled).to_be_checked()
            d.get_by_role("button", name="초안 지원", exact=True).click()
            d.locator("select").nth(0).select_option(w.draft["id"])
            expect(d.locator("select").nth(1)).to_contain_text("Snapshot 1")
            d.locator("select").nth(1).select_option(w.snapshot["id"])
            d.get_by_label("변경할 초안 이름", exact=True).fill(
                "Reviewed synthetic draft"
            )
            d.get_by_label(
                "변경안을 준비하기 전에 이 비공개 초안 변경 내용을 검토합니다."
            ).check()
            d.get_by_role("button", name="정확한 변경안 준비", exact=True).click()
            expect(d).to_contain_text('replace /name: "Reviewed synthetic draft"')
            d.get_by_label("이 변경안 그대로 새 비공개 초안 버전에 적용합니다.").check()
            d.get_by_role("button", name="검토한 변경안 적용", exact=True).click()
            expect(d).to_contain_text("Private draft revision 2 saved")
            d.get_by_role("button", name="운영 준비 근거", exact=True).click()
            expect(d).to_contain_text("Not ready")
            assert len(w.calls) == before
        else:
            expect(d).to_contain_text("비교 기준을 명시하세요.")
            d.locator("#workspaceProductQuery").fill(w.product.inputs["query"])
            d.locator("#workspaceProductLimit").fill(str(w.product.inputs["limit"]))
            d.locator("#workspaceProductCriteria").fill(
                "\n".join(
                    row["criterion_id"] + "," + row["dimension"]
                    for row in w.product.inputs["criteria"]
                )
            )
            d.locator("#workspaceProductPrepare").click()
            expect(reason).to_be_focused()
            reason.fill("Review exact synthetic product input and one test")
            d.locator("#workspaceProductPrepare").click()
            expect(d.locator("#workspaceProductSave")).to_be_enabled()
            d.locator("#workspaceProductSave").click()
            expect(d.locator("#workspaceProductTestPrepare")).to_be_enabled()
            assert len(w.calls) == before
            d.locator("#workspaceProductTestPrepare").click()
            expect(d.locator("#workspaceProductConsent")).to_be_enabled()
            d.locator("#workspaceProductConsent").check()
            d.locator("#workspaceProductRun").click()
            expect(d.locator("#workspaceProductResults")).to_contain_text(
                "Product contract: passed"
            )
            calls = len(w.calls)
            assert w.calls[before:].count("tools/call") == 1
            d.locator("#workspaceProductHistory").click()
            expect(d).to_contain_text("읽기 전용 이력을 조회했습니다.")
            assert len(w.calls) == calls
        assert d.evaluate("node => node.scrollWidth <= node.clientWidth + 2")
        page.screenshot(
            path="reports/admin-renewal-design-2026-10-21/growth/" + p.kind + ".png",
            full_page=True,
        )
        page.evaluate("location.hash='#/home'")
        expect(page.locator("dialog[open]")).to_have_count(0)
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_adapter_keeps_shell_globals_and_unowned_intervals_out():
    from scripts.build_admin_specialist_panels import PANELS, build

    for kind in ("growth", "advancement", "product"):
        source = build(kind, PANELS[kind])
        assert (
            Path(
                "agent_market/gateway/admin_next/areas/panel-" + kind + ".js"
            ).read_text()
            == source
        )
        assert (
            "window.Workspace" not in source and "window.AdvancementAdmin" not in source
        )
        assert (
            "window.addEventListener" not in source and "workspaceSelect" not in source
        )
    source = build("product", PANELS["product"])
    assert "clearInterval(expiryTimer)" in source


def test_support_record_and_withdrawal_aliases_use_retained_mock_run(growth):
    g = growth
    w = g.w
    flow = save(w)
    result, _ = run(w, flow)
    before = len(w.calls)
    app = FastAPI()
    app.include_router(aliases(w.store, growth_routes(g.factory, g.support)))
    headers = {
        **g.headers,
        "Origin": "https://admin.test",
        "X-Admin-Reason": quote("Review synthetic retained support outcome"),
    }
    path = RENEWAL + "/" + w.ws + "/support-outcomes"
    with TestClient(app, base_url="https://admin.test") as c:
        r = c.post(
            path + "/records", headers=headers, json=support_body(g, flow, result)
        )
        assert r.status_code == 200, r.text
        case = r.json()["result"]
        body = {
            "case_id": case["case_id"],
            "revision": 1,
            "authorized": True,
            "notice": "workspace-support-outcome-withdraw-v1",
        }
        r = c.post(path + "/withdrawals", headers=headers, json=body)
        assert r.status_code == 200, r.text
        report = c.get(path, headers=headers).json()["result"]
        assert (
            report["logical_run_samples"] == 0 and report["excluded"]["withdrawn"] == 1
        )
    assert len(w.calls) == before


def test_sandbox_panel_aliases_keep_separate_prepare_dispatch_and_agreement_reason(
    sandbox, browser
):
    from playwright.sync_api import expect

    w = sandbox
    app = FastAPI()
    source = advancement_routes(
        w.access, agreements=w.agreements, sandbox_payments=w.payments
    )
    app.include_router(source)
    app.include_router(aliases(w.store, source))
    app.include_router(workspaces(w.store, b"n" * 32, access=w.access))
    shell(SimpleNamespace(app=app, actor=w.staff[1]))
    client, context, page, errors, external = browser_context(
        browser, app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.raw_staff)
        + ');localStorage.setItem("adm-theme","dark");'
    )
    before = len(w.provider_calls)
    headers = {
        "Authorization": "Bearer " + w.raw_staff,
        "X-Dashboard": "1",
        "X-Admin-Reason": "Synthetic sandbox boundary",
    }
    try:
        assert (
            client.get(
                RENEWAL + "/" + w.ws + "/advancement/agreements", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                RENEWAL + "/" + w.ws + "/advancement/agreements",
                headers={k: v for k, v in headers.items() if k != "X-Admin-Reason"},
                json={},
            ).status_code
            == 400
        )
        page.goto("https://admin.test/admin/next#/customers/specialists")
        page.get_by_label("직원 워크스페이스", exact=True).select_option(w.ws)
        page.get_by_role(
            "button", name="운영 시뮬레이션·초안 지원 열기", exact=True
        ).click()
        d = page.locator("dialog[open]")
        d.get_by_label("전문 패널 변경 사유").fill("Synthetic signed TEST_UNIT review")
        d.get_by_role("button", name="서명 이벤트 샌드박스", exact=True).click()
        d.get_by_label("Sandbox agreement or settlement").select_option(
            w.agreement["id"]
        )
        d.get_by_label("샌드박스 TEST_UNIT 정수").fill("101")
        prepare = d.get_by_label("이 TEST_UNIT 이벤트를 전송하지 않고 준비만 합니다.")
        expect(prepare).not_to_be_checked()
        prepare.check()
        d.get_by_role("button", name="샌드박스 이벤트 준비", exact=True).click()
        expect(d).to_contain_text("capture · 101 TEST_UNIT · prepared")
        dispatch = d.get_by_label("이 서명된 샌드박스 이벤트만 한 번 전송합니다.")
        expect(dispatch).not_to_be_checked()
        dispatch.check()
        d.get_by_role("button", name="샌드박스 이벤트 1회 전송", exact=True).click()
        expect(d).to_contain_text("capture · 101 TEST_UNIT · recorded")
        assert (
            len(w.provider_calls) == before
        )  # No new HTTPS claim check or external payment call.
        assert w.agreements.summary(w.ws, w.staff[1])["balanced"]
        assert not errors and not external
        page.screenshot(
            path="reports/admin-renewal-design-2026-10-21/growth/sandbox-dark.png",
            full_page=True,
        )
    finally:
        context.close()
        client.close()
