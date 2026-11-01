"""Index status must not report progress merely because the worker thread lives."""

# ruff: noqa: F401,F811 -- isolated fixtures
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_dashboard import dash
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console, sign_in, ORIGIN


@pytest.mark.parametrize(
    "name,status,message",
    [
        (
            "disabled",
            {
                "state": "disabled",
                "enabled": False,
                "last_count": 0,
                "reason": "embedding_provider_disabled",
            },
            "임베딩 생성이 꺼져 있어 자동 색인이 중지되었습니다.",
        ),
        (
            "error",
            {
                "state": "error",
                "enabled": True,
                "last_count": 0,
                "reason": "index_step_error",
            },
            "최근 색인 처리에 오류가 있습니다.",
        ),
        (
            "unconfirmed",
            {},
            "대기 데이터가 있지만 실제 색인 진행은 아직 확인되지 않았습니다.",
        ),
        (
            "completed",
            {
                "state": "outbox",
                "enabled": True,
                "last_count": 2,
                "last_success_at": 1700000000,
            },
            "최근 2건의 색인을 완료했습니다.",
        ),
    ],
)
def test_index_worker_actual_status_is_visible(dash, browser, name, status, message):
    world, client = dash
    world.app.state.collector.rag_status = status
    context, page, errors, external = open_console(dash, browser)
    try:
        sign_in(page)
        page.goto(ORIGIN + "/admin/next#/collection/c05")
        expect(page.get_by_text(message, exact=False)).to_be_visible()
        expect(
            page.get_by_text(
                "변경된 에이전트 정보를 검색에 반영하고 있습니다.", exact=True
            )
        ).to_have_count(0)
        output = Path(__file__).resolve().parents[1] / "reports/pgvector-backlog-2026-10-24/screenshots"
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / ("index-" + name + ".png")), full_page=True)
        assert not errors and not external, (errors, external)
    finally:
        context.close()
