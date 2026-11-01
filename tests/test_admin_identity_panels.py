"""Renewal agreement and identity panels retain current owner and exact-purpose authority."""

# ruff: noqa: F401,F811
import json
from contextlib import contextmanager
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.workspace_admin_specialists import router_for as aliases, RENEWAL
from agent_market.workspace_service import router_for as workspaces
from agent_market.advancement_service import router_for as advancement_routes
from agent_market.provider_claims_service import router_for as claim_routes
from agent_market.customer_identity_service import router_for as customer_routes
from agent_market.workspace_access import SessionActor
from agent_market.gateway.admin_auth import session_reference
from tests.test_provider_claims import provider
from tests.test_workspace_agreements import agreement
from tests.test_admin_specialist_panels import shell
from tests.test_workspace_admin_browser import browser_context
from tests.test_front_workflow_browser import browser


@contextmanager
def make_panel(w, kind):
    app = FastAPI()
    sources = [
        customer_routes(
            w.store,
            b"synthetic-workspace-key-32-bytes!!",
            identity=w.core,
            public=False,
        ),
        claim_routes(w.store, b"synthetic-provider-claim-key32!!!", claims=w.claims),
    ]
    if kind == "agreement":
        sources.append(advancement_routes(w.access, agreements=w.agreements))
    app.include_router(workspaces(w.store, b"n" * 32, access=w.access))
    for source in sources:
        app.include_router(source)
        app.include_router(aliases(w.store, source))
    shell(SimpleNamespace(app=app, actor=w.staff[1]))
    p = SimpleNamespace(
        w=w,
        app=app,
        kind=kind,
        base=RENEWAL + "/" + w.ws,
        headers={"Authorization": "Bearer " + w.raw_staff, "X-Dashboard": "1"},
    )
    p.reason = {
        **p.headers,
        "X-Admin-Reason": quote("Synthetic owner agreement and control review"),
    }
    p.reads = (
        [
            "/advancement/agreements/options",
            "/advancement/agreements",
            "/advancement/agreements/summary",
        ]
        if kind == "agreement"
        else ["/customers", "/provider-claims", "/provider-claims/options"]
    )
    p.write = (
        "/advancement/agreements" if kind == "agreement" else "/provider-claims/prepare"
    )
    with TestClient(app, base_url="https://admin.test") as c:
        p.client = c
        yield p


@pytest.fixture(params=["agreement", "identity"])
def panel(request):
    w = request.getfixturevalue(
        "agreement" if request.param == "agreement" else "provider"
    )
    with make_panel(w, request.param) as p:
        yield p


@pytest.fixture
def identity_panel(provider):
    with make_panel(provider, "identity") as p:
        yield p


@pytest.fixture
def agreement_panel(agreement):
    with make_panel(agreement, "agreement") as p:
        yield p


def test_alias_auth_owner_scope_reason_audit_without_provider_call(panel):
    p = panel
    w = p.w
    c = p.client
    before = len(w.provider_calls)
    for suffix in p.reads:
        r = c.get(p.base + suffix, headers=p.headers)
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        assert c.get(p.base + suffix, headers={"X-Dashboard": "1"}).status_code == 401
        assert c.get(
            (p.base + suffix).replace(w.ws, "ws_" + "f" * 32), headers=p.headers
        ).status_code in (401, 404)
        assert (
            c.get(
                p.base + suffix, headers={**p.headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
    assert c.post(p.base + p.write, headers=p.headers, json={}).status_code == 400
    assert (
        c.post(
            p.base + p.write,
            headers={**p.reason, "Origin": "https://evil.test"},
            json={},
        ).status_code
        == 401
    )
    r = c.post(p.base + p.write, headers=p.reason, json={})
    assert r.status_code == 400, r.text
    rows = w.store._db.execute(
        "SELECT status,details FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'"
    ).fetchall()
    assert {r[0] for r in rows} == {"REQUESTED", "FAILED"} and w.raw_staff not in str(
        rows
    )
    for path in ("/members", "/drafts", "/customers/any/token"):
        assert c.post(p.base + path, headers=p.reason, json={}).status_code == 404
    assert len(w.provider_calls) == before


def test_customer_roles_and_revision_are_explicit_no_staff_escalation(identity_panel):
    p = identity_panel
    w = p.w
    c = p.client
    customer = "cu_" + "a" * 32
    now = time.time()
    with w.store.tx() as db:
        db.execute(
            "INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)",
            (customer, "https://accounts.google.com", "b" * 64, now, now),
        )
    body = {"customer_id": customer, "role": "viewer", "active": True, "revision": 0}
    r = c.post(p.base + "/customers", headers=p.reason, json=body)
    assert r.status_code == 200, r.text
    assert c.post(p.base + "/customers", headers=p.reason, json=body).status_code == 409
    assert (
        c.post(
            p.base + "/customers",
            headers=p.reason,
            json=body | {"role": "superadmin", "revision": 1},
        ).status_code
        == 400
    )
    r = c.post(
        p.base + "/customers",
        headers=p.reason,
        json=body | {"role": "runner", "revision": 1},
    )
    assert r.status_code == 200, r.text
    r = c.post(
        p.base + "/customers",
        headers=p.reason,
        json=body | {"active": False, "revision": 2},
    )
    assert r.status_code == 200, r.text
    data = c.get(p.base + "/customers", headers=p.headers).json()["customers"]
    assert data[0]["active"] == 0 and data[0]["revision"] == 3
    assert not w.provider_calls


def test_native_dialog_review_and_current_authority(panel, browser):
    from playwright.sync_api import expect

    p = panel
    w = p.w
    before = len(w.provider_calls)
    if p.kind == "identity":
        customer = "cu_" + "a" * 32
        now = time.time()
        with w.store.tx() as db:
            db.execute(
                "INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)",
                (customer, "https://accounts.google.com", "b" * 64, now, now),
            )
    client, context, page, errors, external = browser_context(
        browser, p.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(w.raw_staff)
        + ');localStorage.setItem("adm-theme",'
        + json.dumps("dark" if p.kind == "identity" else "light")
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/customers/specialists")
        page.get_by_label("직원 워크스페이스", exact=True).select_option(w.ws)
        name = (
            "제공자 합의·시뮬레이션"
            if p.kind == "agreement"
            else "고객 접근·제공자 소유권"
        )
        page.get_by_role("button", name=name + " 열기", exact=True).click()
        d = page.locator("dialog[open]")
        expect(d).to_be_visible()
        reason = d.get_by_label("전문 패널 변경 사유")
        if p.kind == "agreement":
            expect(d).to_contain_text("현재 기록을 조회했습니다.")
            d.get_by_role("button", name="배분 미리보기", exact=True).click()
            expect(reason).to_be_focused()
            reason.fill("Synthetic integer allocation and original-term refund")
            d.get_by_role("button", name="배분 미리보기", exact=True).click()
            consent = d.get_by_label(
                "이 정확한 배분을 TEST_UNIT 시뮬레이션에 한 번 기록합니다. 실제 결제·지급은 발생하지 않습니다."
            )
            expect(consent).not_to_be_checked()
            consent.check()
            d.get_by_label("Gross TEST_UNIT for version 1").fill("101")
            expect(
                d.get_by_role("button", name="시뮬레이션 정산 기록", exact=True)
            ).to_have_count(0)
            d.get_by_role("button", name="배분 미리보기", exact=True).click()
            expect(consent).not_to_be_checked()
            consent.check()
            d.get_by_role("button", name="시뮬레이션 정산 기록", exact=True).click()
            expect(d).to_contain_text("cumulative refund 0 TEST_UNIT")
            refund = d.get_by_label(
                "원래 약정 조건으로 이 증분 시뮬레이션 환불을 한 번 기록합니다."
            )
            refund.check()
            d.locator("input[type=number]").last.fill("21")
            expect(refund).not_to_be_checked()
            refund.check()
            d.get_by_role("button", name="시뮬레이션 환불 기록", exact=True).click()
            expect(d).to_contain_text("cumulative refund 21 TEST_UNIT")
            d.get_by_label(
                "새 시뮬레이션 기록에 대한 이 합의 버전의 사용을 철회합니다."
            ).check()
            d.get_by_role("button", name="합의 버전 철회", exact=True).click()
            expect(d).to_contain_text("revoked · revision 2")
            assert w.agreements.summary(w.ws, w.staff[1])["balanced"]
        else:
            expect(d).to_contain_text("고객 접근은 명시적으로 부여합니다.")
            d.get_by_label("고객 ID", exact=True).fill(customer)
            d.get_by_role("button", name="고객 접근 저장", exact=True).click()
            expect(reason).to_be_focused()
            reason.fill("Synthetic customer link and endpoint proof lifecycle")
            d.get_by_role("button", name="고객 접근 저장", exact=True).click()
            expect(d).to_contain_text(customer + " · viewer · active · revision 1")
            d.get_by_label("등록된 에이전트 ID", exact=True).fill("1")
            d.get_by_role("button", name="HTTPS 확인 준비", exact=True).click()
            expect(d.locator("pre")).to_contain_text("provider-https-control-v1")
            authority = d.get_by_label(
                "엔드포인트 소유권을 확인하기 위해 표시된 정확한 주소에 HTTPS 요청 한 번을 보내도록 승인합니다."
            )
            expect(authority).not_to_be_checked()
            expect(
                d.get_by_role("button", name="엔드포인트 소유권 확인", exact=True)
            ).to_be_disabled()
            authority.check()
            d.get_by_role("button", name="현재 기록 새로고침", exact=True).click()
            expect(authority).not_to_be_checked()
            expect(
                d.get_by_role("button", name="엔드포인트 소유권 확인", exact=True)
            ).to_be_disabled()
            d.get_by_role("button", name="새 확인 준비", exact=True).click()
            expect(d.locator("pre")).to_contain_text("provider-https-control-v1")
            w.proof = json.loads(d.locator("pre").inner_text().split("\n", 1)[1])
            authority.check()
            d.get_by_role("button", name="엔드포인트 소유권 확인", exact=True).click()
            expect(d).to_contain_text("verified · revision 3")
            d.get_by_role("button", name="소유권 확인 철회", exact=True).last.click()
            expect(d).to_contain_text("revoked · revision 4")
        assert len(w.provider_calls) == before + (1 if p.kind == "identity" else 0)
        assert d.evaluate("node=>node.scrollWidth<=node.clientWidth+2")
        page.screenshot(
            path="reports/admin-renewal-design-2026-10-21/identity/" + p.kind + ".png",
            full_page=True,
        )
        page.evaluate("location.hash='#/home'")
        expect(page.locator("dialog[open]")).to_have_count(0)
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_new_agreement_version_is_reasoned_and_never_legal_or_payment_approval(
    agreement_panel,
):
    p = agreement_panel
    w = p.w
    r = p.client.post(
        p.base + "/advancement/agreements",
        headers=p.reason,
        json=w.body | {"revision": 1},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["legal_verification"] == "unverified"
    assert not any(
        result[k]
        for k in (
            "actual_money",
            "commercial_enabled",
            "payment_enabled",
            "provider_payout_enabled",
        )
    )
    assert len(w.provider_calls) == 1


def test_factories_are_synchronized_and_have_no_legacy_globals():
    from scripts.build_admin_specialist_panels import PANELS, build

    for kind in ("agreement", "identity"):
        s = build(kind, PANELS[kind])
        assert (
            Path(
                "agent_market/gateway/admin_next/areas/panel-" + kind + ".js"
            ).read_text()
            == s
        )
        assert (
            "workspaceSelect" not in s
            and "window.Workspace" not in s
            and "setInterval" not in s
        )
        assert "scopeIdentity()" in s and "innerHTML" not in s


def staff_headers(w, user_id, raw):
    ref = session_reference(raw)
    with w.store.tx() as db:
        db.execute("UPDATE admin_sessions SET token=? WHERE user_id=?", (ref, user_id))
    w.staff[user_id] = SessionActor(user_id, ref)
    return {
        "Authorization": "Bearer " + raw,
        "X-Dashboard": "1",
        "X-Admin-Reason": quote("Synthetic current owner review"),
    }


def test_transfer_aliases_retire_old_proof_and_require_target_owner_fresh_nonce(
    identity_panel,
):
    p = identity_panel
    w = p.w
    c = p.client
    fresh = c.post(
        p.base + "/provider-claims/prepare", headers=p.reason, json={"resource_id": 1}
    ).json()
    w.proof = fresh["challenge"]
    body = {
        "claim_id": fresh["claim"]["id"],
        "revision": fresh["claim"]["revision"],
        "authorized": True,
        "notice": "provider-https-control-v1",
    }
    r = c.post(p.base + "/provider-claims/verify", headers=p.reason, json=body)
    assert r.status_code == 200, r.text
    verified = r.json()["claim"] if "claim" in r.json() else r.json()
    target = w.access.provision(
        {"name": "Separate synthetic owner", "owner_id": 4}, w.staff[1]
    )["id"]
    target_headers = staff_headers(w, 4, "c" * 64)
    claim = verified.get("id", fresh["claim"]["id"])
    revision = verified.get("revision", 3)
    r = c.post(
        p.base + "/provider-claims/" + claim + "/transfer",
        headers=p.reason,
        json={"revision": revision, "target_workspace_id": target},
    )
    assert r.status_code == 200, r.text
    transfer = r.json()["transfer_id"]
    path = RENEWAL + "/" + target + "/provider-claims/transfers/" + transfer + "/accept"
    assert c.post(path, headers=p.reason, json={"revision": 1}).status_code == 404
    r = c.post(path, headers=target_headers, json={"revision": 1})
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert (
        accepted["challenge"]["nonce"] != fresh["challenge"]["nonce"]
        and len(w.provider_calls) == 1
    )
    assert c.post(path, headers=target_headers, json={"revision": 1}).status_code in (
        404,
        409,
    )
    w.proof = accepted["challenge"]
    body |= {
        "claim_id": accepted["claim"]["id"],
        "revision": accepted["claim"]["revision"],
    }
    r = c.post(
        RENEWAL + "/" + target + "/provider-claims/verify",
        headers=target_headers,
        json=body,
    )
    assert r.status_code == 200, r.text
    assert len(w.provider_calls) == 2
    claims = c.get(p.base + "/provider-claims", headers=p.headers).json()["claims"]
    assert claims[0]["status"] == "transferred"


def test_superadmin_is_not_workspace_owner_and_arbitrary_url_is_rejected(
    identity_panel,
):
    p = identity_panel
    w = p.w
    foreign = staff_headers(w, 5, "d" * 64)
    assert p.client.get(p.base + "/provider-claims", headers=foreign).status_code == 404
    assert p.client.get(p.base + "/customers", headers=foreign).status_code == 401
    assert (
        p.client.post(
            p.base + "/provider-claims/prepare",
            headers=foreign,
            json={"resource_id": 1},
        ).status_code
        == 404
    )
    r = p.client.post(
        p.base + "/provider-claims/prepare",
        headers=p.reason,
        json={"resource_id": 1, "url": "http://127.0.0.1/private"},
    )
    assert r.status_code == 400 and not w.provider_calls


def test_changed_input_and_closed_identity_discard_pending_challenges(
    identity_panel, browser
):
    from playwright.sync_api import expect

    p = identity_panel
    w = p.w
    client, context, page, errors, external = browser_context(
        browser, p.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps(w.raw_staff) + ");"
    )
    held = []

    def hold(route):
        req = route.request
        result = client.post(
            p.base + "/provider-claims/prepare",
            headers=req.headers,
            content=req.post_data,
        )
        held.append((route, result))
        page.evaluate("window.__heldIdentityPlan=(window.__heldIdentityPlan||0)+1")

    page.route("**/v2/workspace-panels/*/provider-claims/prepare", hold)
    try:
        page.goto("https://admin.test/admin/next#/customers/specialists")
        page.get_by_label("직원 워크스페이스", exact=True).select_option(w.ws)
        page.get_by_role(
            "button", name="고객 접근·제공자 소유권 열기", exact=True
        ).click()
        d = page.locator("dialog[open]")
        d.get_by_label("전문 패널 변경 사유").fill("Synthetic delayed challenge review")
        resource = d.get_by_label("등록된 에이전트 ID", exact=True)
        resource.fill("1")
        prepare = d.get_by_role("button", name="HTTPS 확인 준비", exact=True)
        prepare.click()
        page.wait_for_function("window.__heldIdentityPlan===1")
        resource.fill("2")
        route, result = held.pop()
        assert result.status_code == 200, result.text
        route.fulfill(status=200, content_type="application/json", body=result.content)
        expect(prepare).to_be_enabled()
        expect(d.locator("pre")).to_be_empty()
        expect(
            d.get_by_role("button", name="엔드포인트 소유권 확인", exact=True)
        ).to_be_disabled()
        resource.fill("1")
        prepare.click()
        page.wait_for_function("window.__heldIdentityPlan===2")
        d.get_by_role("button", name="닫기", exact=True).click()
        route, result = held.pop()
        try:
            route.fulfill(
                status=200, content_type="application/json", body=result.content
            )
        except Exception:
            pass  # Closing deliberately aborts the pending read/command response.
        expect(page.locator("dialog[open]")).to_have_count(0)
        assert not w.provider_calls and not errors and not external
    finally:
        for route, _ in held:
            route.abort()
        context.close()
        client.close()


def test_advancement_opens_new_agreement_panel_with_fresh_reason(
    agreement_panel, browser
):
    from playwright.sync_api import expect

    p = agreement_panel
    w = p.w
    client, context, page, errors, external = browser_context(
        browser, p.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",' + json.dumps(w.raw_staff) + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/customers/specialists")
        page.get_by_label("직원 워크스페이스", exact=True).select_option(w.ws)
        page.get_by_role(
            "button", name="운영 시뮬레이션·초안 지원 열기", exact=True
        ).click()
        old = page.locator("dialog[open]")
        old.get_by_label("전문 패널 변경 사유").fill("Previous separate purpose")
        old.get_by_role("button", name="제공자 합의", exact=True).click()
        current = page.get_by_role("dialog", name="제공자 합의·시뮬레이션", exact=True)
        expect(current).to_be_visible()
        expect(current).to_contain_text("현재 기록을 조회했습니다.")
        expect(current.get_by_label("전문 패널 변경 사유")).to_have_value("")
        assert "/admin/next" in page.url and page.locator("dialog[open]").count() == 1
        assert len(w.provider_calls) == 1 and not errors and not external
    finally:
        context.close()
        client.close()
