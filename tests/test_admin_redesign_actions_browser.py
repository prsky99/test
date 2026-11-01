"""Reviewed real-domain interactions in isolated browsers and stores."""

# ruff: noqa: F401,F811
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from agent_market.gateway.dashboard import dashboard_router
from agent_market.workspace_platform import platform_for
from agent_market.workspace_access import SessionActor
from agent_market.workspace_admin_events import migrate
from tests.test_front_workflow_browser import browser
from tests.test_dashboard import dash
from tests.test_admin_next_browser import open_console, sign_in, ORIGIN
from tests.test_workflow_fallback import routing
from tests.test_owned_data_agents import engine
from tests.test_owned_data_agents_activation import operating

ROOT = Path("reports/admin-redesign-implementation-2026-10-24/screenshots")


def shot(page, name):
    ROOT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ROOT / (name + ".png")), full_page=True)


def confirm(page, label, reason="Isolated administrative UX verification"):
    dialog = page.locator("dialog.adm-dialog")
    expect(dialog).to_be_visible()
    dialog.locator("textarea").fill(reason)
    dialog.get_by_role("button", name=label, exact=True).click()


def test_key_create_rotate_delete_masks_secret_and_updates_real_store(dash, browser):
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/agents/a07")
        expect(page.locator("#adm-main")).to_have_attribute("data-screen", "A07")
        shot(page, "A07-before-create")
        page.get_by_role("button", name="제공자 연결 추가", exact=True).first.click()
        drawer = page.locator(".adm-drawer")
        drawer.get_by_label("키 이름", exact=True).fill("isolated-ui-key")
        drawer.get_by_label("제공자", exact=True).fill("synthetic")
        drawer.get_by_label("새 API 키", exact=True).fill(
            "secret-never-in-dom-or-audit"
        )
        drawer.get_by_role("button", name="연결 저장 검토").click()
        expect(page.locator("dialog.adm-dialog")).not_to_contain_text("secret-never")
        confirm(page, "API 키 저장")
        expect(page.locator(".adm-drawer")).to_have_count(0)
        row = page.locator("tbody tr", has_text="isolated-ui-key")
        expect(row).to_be_visible()
        expect(page.locator("#adm-main")).not_to_contain_text("secret-never")
        row.get_by_role("button", name="키 교체", exact=True).click()
        drawer.get_by_label("새 API 키", exact=True).fill("rotated-secret-never-in-dom")
        drawer.get_by_role("button", name="연결 저장 검토").click()
        confirm(page, "API 키 저장")
        expect(page.locator(".adm-drawer")).to_have_count(0)
        shot(page, "A07-after-rotate")
        row.get_by_role("button", name="연결 삭제", exact=True).click()
        confirm(page, "연결 삭제")
        expect(row).to_have_count(0)
        shot(page, "A07-after-delete")
        assert not errors and not external
    finally:
        context.close()


def test_new_workbench_executes_owned_recipe_with_edited_inputs(operating, browser):
    front, _, _, calls, _ = operating
    app = FastAPI()
    app.include_router(
        dashboard_router(
            front.store,
            front.store._path,
            "synthetic-machine",
            None,
            front=front,
            ssl_manager=Mock(get_status=lambda: {}),
        )
    )
    client = TestClient(app, base_url=ORIGIN)
    context, page, errors, external = open_console(
        (SimpleNamespace(app=app), client), browser
    )
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/agents/a03")
        query = page.get_by_label("에이전트 이름 검색", exact=True)
        query.fill("Technology")
        page.get_by_role("button", name="에이전트 검색", exact=True).click()
        page.locator(".adm-selection-item").first.click()
        shot(page, "A03-before-discovery")
        page.get_by_role("button", name="도구 정보 확인", exact=True).click()
        confirm(page, "도구 정보 확인")
        expect(page.get_by_label("query", exact=True)).to_be_visible()
        page.get_by_label("query", exact=True).fill("Isolated browser climate research")
        page.get_by_label("limit", exact=True).fill("1")
        before = len(calls)
        page.get_by_role("button", name="검토한 입력 1회 실행", exact=True).click()
        expect(page.locator("dialog.adm-dialog")).to_contain_text(
            "Isolated browser climate research"
        )
        confirm(page, "검토한 입력 1회 실행")
        expect(
            page.get_by_role("heading", name="테스트 결과", exact=True)
        ).to_be_visible()
        expect(page.locator("#adm-main")).to_contain_text(
            "Isolated browser climate research"
        )
        assert len(calls) > before
        shot(page, "A03-after-owned-execution")
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_two_agent_workflow_create_deep_open_review_run_and_search(routing, browser):
    rt, _, ids, calls, _, _, _ = routing
    front = SimpleNamespace(store=rt.store, proxy=rt.proxy, courier=None)
    app = FastAPI()
    app.include_router(
        dashboard_router(
            rt.store,
            rt.store._path,
            "synthetic-machine",
            None,
            front=front,
            ssl_manager=Mock(get_status=lambda: {}),
        )
    )
    client = TestClient(app, base_url=ORIGIN)
    migrate(rt.store, rt.key)
    context, page, errors, external = open_console(
        (SimpleNamespace(app=app), client), browser
    )
    try:
        sign_in(page)
        from agent_market.gateway import admin_auth

        raw = page.evaluate("sessionStorage.getItem('adminToken')")
        with rt.store.tx() as db:
            user = admin_auth.get_session_user(db, raw)
        platform_for(front).access.provision(
            {"name": "Browser graph team", "owner_id": user["user_id"]},
            SessionActor(user["user_id"], admin_auth.session_reference(raw)),
        )
        page.goto(ORIGIN + "/admin/next#/workflows/w03")
        expect(page.get_by_label("연결할 에이전트", exact=True)).to_be_enabled()
        page.get_by_label("워크플로 이름", exact=True).fill("Browser evidence workflow")
        page.get_by_label("연결할 에이전트", exact=True).select_option(
            str(ids[0]) + "|docs.search.v1"
        )
        page.get_by_label("query", exact=True).fill("Current documentation")
        page.get_by_role("button", name="단계 연결", exact=True).click()
        page.get_by_label("연결할 에이전트", exact=True).select_option(
            str(ids[1]) + "|docs.search.v1"
        )
        source = page.get_by_label("query 입력 출처", exact=True)
        options = source.locator("option").evaluate_all("xs=>xs.map(x=>x.value)")
        source.select_option(next(x for x in options if x.endswith("|title")))
        page.get_by_role("button", name="단계 연결", exact=True).click()
        expect(page.locator(".adm-flow-svg circle")).to_have_count(2)
        shot(page, "W03-before-save-two-agents")
        assert not calls
        page.get_by_role("button", name="연결 검토 후 저장", exact=True).click()
        confirm(page, "검토한 워크플로 저장")
        link = page.get_by_role("link", name="저장한 워크플로 실행 검토", exact=True)
        expect(link).to_be_visible()
        assert not calls
        link.click()
        dialog = page.locator("dialog.adm-specialist-dialog")
        expect(dialog.get_by_label("워크플로 이름", exact=True)).to_have_value(
            "Browser evidence workflow"
        )
        expect(dialog.locator('.adm-typed-preview')).to_be_in_viewport()
        shot(page, "E01-before-review-saved-flow")
        dialog.get_by_label("전문 패널 변경 사유", exact=True).fill(
            "Isolated whole graph review"
        )
        dialog.get_by_role("button", name="전체 실행 내용 검토", exact=True).click()
        expect(dialog).to_contain_text("모든 에이전트, 입력값")
        assert not calls
        dialog.locator("input[type=checkbox]").check()
        dialog.get_by_role("button", name="검토한 워크플로 실행", exact=True).click()
        expect(dialog).to_contain_text("Private run recorded: succeeded")
        assert calls == ["primary.example", "alternate.example"]
        shot(page, "E01-after-two-agent-execution")
        dialog.evaluate('(node)=>node.scrollTop=0')
        shot(page, "E01-after-two-agent-execution-top")
        dialog.get_by_role("button", name="닫기", exact=True).click()
        page.goto(ORIGIN + "/admin/next#/workflows/w01")
        expect(page.locator("#adm-main")).to_contain_text("Browser evidence workflow")
        shot(page, "W01-after-saved-workflow-search")
        assert not errors and not external
    finally:
        context.close()
        client.close()


def test_all_specialist_panels_open_with_real_staff_membership(private_api, browser):
    w = private_api
    context, page, errors, external = open_console(
        (SimpleNamespace(app=w.app), w.client), browser
    )
    failures = []
    try:
        page.evaluate(
            "token=>sessionStorage.setItem('adminToken',token)",
            w.headers["owner"]["Authorization"][7:],
        )
        page.reload()
        expect(page.locator("#adm-layout")).to_be_visible()
        for i in range(1, 19):
            key = "E" + str(i).zfill(2)
            page.goto(
                ORIGIN
                + "/admin/next#/workflows/"
                + key.lower()
                + "?workspace="
                + w.ws["id"]
            )
            try:
                expect(page.locator("#adm-main")).to_have_attribute("data-screen", key)
                dialog = page.locator("dialog.adm-specialist-dialog")
                expect(dialog).to_be_visible()
                expect(dialog).not_to_have_attribute("aria-busy", "true", timeout=15000)
                assert len(dialog.inner_text()) > 80
                assert dialog.evaluate(
                    "(e)=>e.getBoundingClientRect().width<=innerWidth"
                )
                shot(page, key + "-authorized-panel")
                dialog.get_by_role("button", name="닫기", exact=True).first.click()
                expect(dialog).not_to_be_visible()
            except Exception as error:
                failures.append((key, str(error)[:350]))
        assert not failures, failures
        assert not errors and not external
    finally:
        context.close()


from tests.test_workspace_execution_api import private_api  # noqa: E402


def test_bootstrap_failure_does_not_block_other_tasks_and_expiry_restores_safe_route(
    dash, browser
):
    context, page, errors, external = open_console(dash, browser)
    context.route(
        "**/admin/api/v2/home/bootstrap",
        lambda route: route.fulfill(
            status=503, json={"detail": "Synthetic aggregate outage"}
        ),
    )
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/agents/a06")
        expect(page.get_by_label("에이전트 이름", exact=True)).to_be_visible()
        page.get_by_label("에이전트 이름", exact=True).fill("Unsaved private draft")
        shot(page, "X02-before-session-expiry")
        with dash[0].store.tx() as db:
            db.execute("DELETE FROM admin_sessions")
        page.evaluate(
            "async()=>{const api=await import('/admin/next/assets/core/api.js');try{await api.read('/admin/api/v2/auth/me',{force:true});}catch{}}"
        )
        expect(page.locator("#adm-login")).to_be_visible()
        expect(page.locator("#adm-main")).to_be_empty()
        expect(page.locator("dialog[open],.adm-drawer")).to_have_count(0)
        shot(page, "X02-after-session-expiry")
        sign_in(page)
        expect(page.locator("#adm-main")).to_have_attribute("data-screen", "A06")
        expect(page.get_by_label("에이전트 이름", exact=True)).to_have_value("")
        page.goto(ORIGIN + "/admin/next#/unknown/missing")
        expect(
            page.get_by_role("heading", name="페이지를 찾을 수 없습니다", exact=True)
        ).to_be_visible()
        shot(page, "X06-after-unknown-route")
        page.get_by_role("link", name="운영 요약으로", exact=True).click()
        expect(page.locator("#adm-main")).to_have_attribute("data-screen", "H01")
        assert (
            not [e for e in errors if "503" not in e and "401" not in e]
            and not external
        )
    finally:
        context.close()
