"""Real click-through evidence against an isolated app and synthetic finance accounts."""

# ruff: noqa: F811 -- imported isolated fixtures are injected by pytest.
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_admin_finance_workbench import finance  # noqa: F401
from tests.test_dashboard import dash  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_admin_next_browser import open_console, ORIGIN

SHOTS = Path("reports/admin-task-redesign-2026-10-24/screenshots")


def capture(page, **options):
    # Full-page evidence must not strand a sticky header at the current scroll offset.
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(**options)


def enter(dash, browser, width=1440, theme="light"):
    context, page, errors, external = open_console(
        dash, browser, width=width, theme=theme
    )
    page.locator("#adm-user").fill("sadmin")
    page.locator("#adm-pass").fill("Renewal-fixture-password")
    page.get_by_role("button", name="로그인", exact=True).click()
    expect(page.locator("#adm-layout")).to_be_visible()
    page.goto(ORIGIN + "/admin/next#/customers/u09")
    expect(page.get_by_role("heading", name="결제·정산", exact=True)).to_be_visible()
    expect(page.locator(".fin-table tbody tr")).to_have_count(2)
    return context, page, errors, external


@pytest.mark.parametrize(
    "width,theme", [(1440, "light"), (768, "light"), (390, "light"), (390, "dark")]
)
def test_responsive_real_data_views(finance, dash, browser, width, theme):
    context, page, errors, external = enter(dash, browser, width, theme)
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        capture(
            page, path=str(SHOTS / f"finance-{width}-{theme}-holds.png"), full_page=True
        )
        page.get_by_role("button", name="상세 보기", exact=True).first.click()
        expect(
            page.get_by_role("heading", name="거래 상세", exact=True)
        ).to_be_visible()
        capture(
            page,
            path=str(SHOTS / f"finance-{width}-{theme}-detail.png"),
            full_page=True,
        )
        page.get_by_role("button", name="계정 잔액", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(1)
        expect(page.locator(".fin-table tbody")).to_contain_text("16")
        page.get_by_label("계정 ID 검색", exact=True).fill("nonexistent")
        page.get_by_role("button", name="조건 적용", exact=True).click()
        expect(
            page.get_by_text("선택한 조건의 기록이 없습니다.", exact=True)
        ).to_be_visible()
        capture(
            page, path=str(SHOTS / f"finance-{width}-{theme}-empty.png"), full_page=True
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "document overflow"
        assert not page.locator(".adm-finance").get_by_text("null", exact=True).count()
        assert not errors and not external, (errors, external)
    finally:
        context.close()


def test_deposit_input_review_apply_receipt_and_retained_filters(
    finance, dash, browser
):
    world, _, _, _, _ = finance
    context, page, errors, external = enter(dash, browser)
    SHOTS.mkdir(parents=True, exist_ok=True)
    evidence = []

    def shot(name):
        path = SHOTS / name
        capture(page, path=str(path), full_page=True)
        return str(path)

    try:
        before = shot("deposit-01-before.png")
        page.get_by_role("button", name="잔액 충전", exact=True).click()
        dialog = page.get_by_role("dialog", name="잔액 충전", exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_label("금융 계정 ID", exact=True).fill("qa-finance-main")
        dialog.get_by_label("금액 (USDC)").fill("1.250001")
        dialog.get_by_label("처리 사유").fill("격리 검증 계정 장부 충전 검토")
        inp = shot("deposit-02-input.png")
        dialog.get_by_role("button", name="변경 내용 검토", exact=True).click()
        expect(dialog.get_by_text("21.250001 USDC", exact=True)).to_be_visible()
        review = shot("deposit-03-review.png")
        assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000
        dialog.get_by_role("button", name="검토 요청 등록", exact=True).click()
        expect(dialog.get_by_text("검토 대기", exact=True)).to_be_visible()
        pending = shot("deposit-04-pending.png")
        assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000
        dialog.get_by_label("검토 사유", exact=True).fill(
            "대상 계정과 단위를 대조했습니다"
        )
        dialog.get_by_role("checkbox").check()
        dialog.get_by_role("button", name="승인하고 장부 적용", exact=True).click()
        expect(
            dialog.get_by_text("장부 적용이 확인되었습니다.", exact=True)
        ).to_be_visible()
        expect(dialog.locator(".fin-receipt")).to_contain_text("21.250001")
        after = shot("deposit-05-applied.png")
        assert world.store.get_credit("qa-finance-main")["balance"] == 21_250_001
        evidence.extend(
            [
                {"action": "충전 입력 열기", "before": before, "after": inp},
                {"action": "최신 금액 검토", "before": inp, "after": review},
                {
                    "action": "요청 접수: 장부 미변경",
                    "before": review,
                    "after": pending,
                },
                {
                    "action": "승인·장부 적용·증빙 확인",
                    "before": pending,
                    "after": after,
                },
            ]
        )
        dialog.get_by_role("button", name="닫기", exact=True).click()
        expect(page.get_by_role("button", name="잔액 충전", exact=True)).to_be_focused()
        page.get_by_role("button", name="잔액 충전", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("button", name="처리 기록", exact=True).click()
        expect(page.locator(".fin-table tbody")).to_contain_text("적용 완료")
        shot("deposit-06-history.png")
        assert not errors and not external, (errors, external)
        Path("reports/admin-task-redesign-2026-10-24/click-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2)
        )
    finally:
        context.close()


def test_refund_context_and_modal_cleanup_on_navigation(finance, dash, browser):
    context, page, errors, external = enter(dash, browser)
    try:
        page.get_by_role("button", name="상세 보기", exact=True).last.click()
        page.get_by_role("button", name="이 거래 보류 해제", exact=True).click()
        dialog = page.get_by_role("dialog", name="보류 해제", exact=True)
        dialog.get_by_label("처리 사유").fill("외부 실행 상태 확인 후 보류 해제")
        dialog.get_by_role("button", name="변경 내용 검토", exact=True).click()
        expect(dialog.get_by_text("1 USDC", exact=True)).to_be_visible()
        expect(dialog.get_by_text("19 USDC", exact=True)).to_be_visible()
        capture(page, path=str(SHOTS / "refund-review.png"), full_page=True)
        # Session/route cleanup closes the real native modal and removes private data.
        page.evaluate("location.hash='#/agents/a01'")
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert not errors and not external, (errors, external)
    finally:
        context.close()


def approve_dialog(page, title):
    dialog = page.get_by_role("dialog", name=title, exact=True)
    dialog.get_by_label("처리 사유").fill("외부 실행 여부와 장부를 확인한 격리 검증")
    dialog.get_by_role("button", name="변경 내용 검토", exact=True).click()
    expect(
        dialog.get_by_role("button", name="검토 요청 등록", exact=True)
    ).to_be_visible()
    dialog.get_by_role("button", name="검토 요청 등록", exact=True).click()
    expect(dialog.get_by_text("검토 대기", exact=True)).to_be_visible()
    dialog.get_by_label("검토 사유", exact=True).fill("계정과 대상 금액 검토 완료")
    dialog.get_by_role("checkbox").check()
    dialog.get_by_role("button", name="승인하고 장부 적용", exact=True).click()
    expect(
        dialog.get_by_text("장부 적용이 확인되었습니다.", exact=True)
    ).to_be_visible()
    return dialog


def test_refund_withdraw_sweep_and_connections_end_to_end(finance, dash, browser):
    import time

    world, _, _, old, _ = finance
    context, page, errors, external = enter(dash, browser)
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        page.get_by_role("button", name="상세 보기", exact=True).last.click()
        capture(page, path=str(SHOTS / "refund-01-before.png"), full_page=True)
        page.get_by_role("button", name="이 거래 보류 해제", exact=True).click()
        dialog = approve_dialog(page, "보류 해제")
        capture(page, path=str(SHOTS / "refund-02-applied.png"), full_page=True)
        assert world.store.get_credit("qa-finance-main")["held"] == 1_000_000
        dialog.get_by_role("button", name="닫기", exact=True).click()
        page.get_by_role("button", name="계정 잔액", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(1)
        page.get_by_role("button", name="상세 보기", exact=True).click()
        capture(page, path=str(SHOTS / "withdraw-01-before.png"), full_page=True)
        page.get_by_role("button", name="사용 가능 잔액 회수", exact=True).click()
        dialog = page.get_by_role("dialog", name="잔액 회수", exact=True)
        dialog.get_by_label("금액 (USDC)").fill("2")
        dialog.get_by_label("기록할 지갑 주소", exact=True).fill("0x" + "1" * 40)
        dialog = approve_dialog(page, "잔액 회수")
        capture(page, path=str(SHOTS / "withdraw-02-applied.png"), full_page=True)
        assert world.store.get_credit("qa-finance-main")["balance"] == 18_000_000
        dialog.get_by_role("button", name="닫기", exact=True).click()
        expired = world.store.hold_credit("qa-finance-main", 2_000_000, 0, "qa-late")
        with world.store.tx() as db:
            db.execute(
                "UPDATE clearing_ledger SET created_at=? WHERE tx_id=?",
                (time.time() - 3600, expired),
            )
        page.get_by_role("button", name="보류 확인", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(2)
        capture(page, path=str(SHOTS / "sweep-01-before.png"), full_page=True)
        page.get_by_role("button", name="오래된 보류 정리", exact=True).click()
        dialog = approve_dialog(page, "오래된 보류 일괄 해제")
        capture(page, path=str(SHOTS / "sweep-02-applied.png"), full_page=True)
        assert world.store.get_credit("qa-finance-main")["held"] == 1_000_000
        dialog.get_by_role("button", name="닫기", exact=True).click()
        page.get_by_role("button", name="정산 거래", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(4)
        page.get_by_label("거래 상태", exact=True).select_option("refunded")
        page.get_by_role("button", name="조건 적용", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(2)
        page.get_by_role("button", name="상세 보기", exact=True).first.click()
        expect(
            page.get_by_role("button", name="이 거래 보류 해제", exact=True)
        ).to_have_count(0)
        page.get_by_role("button", name="결제 원장", exact=True).click()
        expect(
            page.get_by_text("선택한 조건의 기록이 없습니다.", exact=True)
        ).to_be_visible()
        page.get_by_text("결제 연결 설정 확인", exact=True).click()
        expect(page.get_by_text("설정값 조회입니다.", exact=False)).to_be_visible()
        capture(page, path=str(SHOTS / "ledger-and-connection.png"), full_page=True)
        assert not errors and not external, (errors, external)
    finally:
        context.close()


def test_unknown_request_response_disables_resubmit_and_opens_actual_queue(
    finance, dash, browser
):
    _, client, staff, _, _ = finance
    context, page, errors, external = enter(dash, browser)
    calls = []

    def saved_but_lost(route):
        calls.append(route.request.url)
        response = client.post(
            "/admin/api/v2/finance/requests",
            headers=staff,
            content=route.request.post_data,
        )
        assert response.status_code == 202
        route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"Synthetic lost response"}',
        )

    context.route("**/admin/api/v2/finance/requests", saved_but_lost)
    try:
        page.get_by_role("button", name="잔액 충전", exact=True).click()
        dialog = page.get_by_role("dialog", name="잔액 충전", exact=True)
        dialog.get_by_label("금융 계정 ID", exact=True).fill("qa-finance-main")
        dialog.get_by_label("금액 (USDC)").fill("1")
        dialog.get_by_label("처리 사유").fill("응답 유실 후 중복 요청 방지 검증")
        dialog.get_by_role("button", name="변경 내용 검토", exact=True).click()
        dialog.get_by_role("button", name="검토 요청 등록", exact=True).click()
        expect(
            dialog.get_by_text("저장 결과를 확인할 수 없습니다.", exact=False)
        ).to_be_visible()
        expect(
            dialog.get_by_role("button", name="검토 요청 등록", exact=True)
        ).to_be_disabled()
        capture(
            page, path=str(SHOTS / "request-unknown-no-resubmit.png"), full_page=True
        )
        dialog.get_by_role("button", name="처리 기록 확인", exact=True).click()
        expect(page.locator(".fin-table tbody tr")).to_have_count(1)
        expect(page.locator(".fin-table tbody")).to_contain_text("검토 대기")
        capture(
            page,
            path=str(SHOTS / "request-unknown-recovered-queue.png"),
            full_page=True,
        )
        assert len(calls) == 1 and not external
        assert all("503" in error for error in errors), errors
    finally:
        context.close()


def test_global_search_routes_all_three_tasks_without_script_error(
    finance, dash, browser
):
    context, page, errors, external = enter(dash, browser)
    try:
        for kind, route in [
            ("agent", "/agents/a01"),
            ("workflow", "/workflows/w01"),
            ("customer", "/customers/u01"),
        ]:
            page.goto(ORIGIN + "/admin/next#/home/x03")
            search = page.get_by_label("이름·업무 검색", exact=True)
            expect(search).to_be_visible()
            search.fill("qa-finance")
            page.get_by_label("검색할 업무", exact=True).select_option(kind)
            page.get_by_role("button", name="검색", exact=True).click()
            expect(page).to_have_url(
                __import__("re").compile(route + r"\?q=qa-finance")
            )
        assert not errors and not external, (errors, external)
    finally:
        context.close()


def test_unknown_application_can_be_reconciled_in_same_dialog(finance, dash, browser):
    from tests.test_admin_finance_workbench import request, approve

    world, _, _, _, _ = finance
    item = request(finance)
    assert approve(finance, item).json()["item"]["status"] == "applied"
    # Fault injection: the financial commit succeeded but its response was lost.
    # Keep the signed request untouched; this is isolated test data only.
    with world.store.tx() as db:
        db.execute(
            "UPDATE admin_reviewed_commands SET status='unknown',result=? WHERE id=?",
            ('{"error":"격리 검증: 적용 응답 유실"}', item["id"]),
        )
    context, page, errors, external = enter(dash, browser)
    try:
        page.get_by_role("button", name="처리 기록", exact=True).click()
        expect(page.locator(".fin-table tbody")).to_contain_text("결과 확인 필요")
        page.get_by_role("button", name="요청 확인", exact=True).click()
        dialog = page.get_by_role("dialog", name="잔액 충전", exact=True)
        before = SHOTS / "application-unknown-before.png"
        after = SHOTS / "application-unknown-evidence.png"
        capture(page, path=str(before), full_page=True)
        expect(
            dialog.get_by_role("button", name="승인하고 장부 적용", exact=True)
        ).to_have_count(0)
        page.keyboard.press("Tab")
        assert page.evaluate(
            'document.querySelector("dialog").contains(document.activeElement)'
        )
        page.keyboard.press("Shift+Tab")
        assert page.evaluate(
            'document.querySelector("dialog").contains(document.activeElement)'
        )
        dialog.get_by_role("button", name="장부 적용 기록 대조", exact=True).click()
        expect(
            dialog.get_by_text(
                "이 요청의 장부 적용 기록이 확인되었습니다. 중복 실행하지 마세요.",
                exact=True,
            )
        ).to_be_visible()
        expect(dialog.locator(".fin-receipt").last).to_contain_text("21.25")
        capture(page, path=str(after), full_page=True)
        assert world.store.get_credit("qa-finance-main")["balance"] == 21_250_000
        assert not errors and not external, (errors, external)
    finally:
        context.close()


def test_expired_preview_can_be_cancelled_without_waiting_for_review_ttl(
    finance, dash, browser, monkeypatch
):
    import time
    from tests.test_admin_finance_workbench import request

    world, client, staff, _, _ = finance
    clock = time.time
    with monkeypatch.context() as patch:
        patch.setattr(time, "time", lambda: clock() - 301)
        item = request(finance)
    context, page, errors, external = enter(dash, browser)
    try:
        page.get_by_role("button", name="처리 기록", exact=True).click()
        expect(page.locator(".fin-table tbody")).to_contain_text("검토 기한 만료")
        page.get_by_role("button", name="요청 확인", exact=True).click()
        dialog = page.get_by_role("dialog", name="잔액 충전", exact=True)
        expect(
            dialog.get_by_role("button", name="승인하고 장부 적용", exact=True)
        ).to_have_count(0)
        capture(
            page, path=str(SHOTS / "expired-preview-before-cancel.png"), full_page=True
        )
        dialog.get_by_role("button", name="요청 철회", exact=True).click()
        expect(dialog.get_by_text("철회됨", exact=True)).to_be_visible()
        capture(
            page, path=str(SHOTS / "expired-preview-after-cancel.png"), full_page=True
        )
        assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000
        assert request(finance)["id"] != item["id"]
        assert not errors and not external, (errors, external)
    finally:
        context.close()
