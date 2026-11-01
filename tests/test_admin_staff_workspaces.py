"""Native staff workspace CRUD reuses exact private handlers with pre-action audit."""

# ruff: noqa: F401,F811
import json
from pathlib import Path
from urllib.parse import quote
import pytest
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_admin_browser import browser_context
from tests.test_front_workflow_browser import browser

BASE = "/admin/api/v2/staff-workspaces"


def test_staff_core_aliases_preserve_membership_raw_json_and_audited_writes(
    private_api,
):
    w = private_api
    c = w.client
    headers = w.headers["owner"]
    reason = {**headers, "X-Admin-Reason": quote("Synthetic staff workspace review")}
    for suffix in (
        "",
        "/options",
        "/" + w.ws["id"],
        "/" + w.ws["id"] + "/members",
        "/" + w.ws["id"] + "/drafts",
    ):
        r = c.get(BASE + suffix, headers=headers)
        assert r.status_code == 200, r.text
        assert (
            r.headers["cache-control"] == "no-store"
            and c.get(BASE + suffix).status_code == 401
        )
    assert (
        c.post(
            BASE, headers=headers, json={"name": "Review", "owner_id": 1}
        ).status_code
        == 400
    )
    r = c.post(
        BASE, headers=reason, json={"name": "Reviewed staff workspace", "owner_id": 1}
    )
    assert r.status_code == 200, r.text
    assert (
        c.get(BASE + "/" + w.ws["id"], headers=w.headers["outsider"]).status_code == 404
    )
    assert (
        c.post(
            BASE + "/" + w.ws["id"] + "/drafts",
            headers=reason,
            content='{"name":"a","name":"b","description":"","definition":{"nodes":[],"edges":[]}}',
        ).status_code
        == 400
    )
    prefix = (
        BASE
        + "/"
        + w.ws["id"]
        + "/drafts/"
        + w.draft["id"]
        + "/snapshots/"
        + w.snapshot["id"]
    )
    r = c.get(prefix + "/artifact", headers=headers)
    assert r.status_code == 200 and r.json()["executable"] is False
    ticket = c.post(
        prefix + "/execution/prepare",
        headers=reason,
        json={"snapshot_revision": w.snapshot["revision"]},
    )
    assert ticket.status_code == 200, ticket.text
    r = c.post(
        prefix + "/execution/runs",
        headers=reason,
        json={
            "ticket_id": ticket.json()["ticket_id"],
            "authorized": True,
            "notice": "workspace-private-run-v1",
        },
    )
    assert r.status_code == 200 and r.json()["run"]["status"] == "succeeded", r.text
    assert w.calls.count("tools/call") == 1


def test_staff_native_members_draft_snapshot_download_and_one_call(
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
        page.goto("https://admin.test/admin/next#/customers/staff")
        expect(page.locator("#workspaceSelect")).to_be_enabled()
        page.locator("#workspaceSelect").select_option(w.ws["id"])
        expect(page.locator("#workspaceSummary")).to_contain_text(
            "Private execution team"
        )
        page.locator("#workspaceMembers").click()
        d = page.locator("#workspaceMemberDialog")
        d.locator("#workspaceMemberUser").fill(str(w.users["editor"]))
        d.locator("#workspaceMemberRole").select_option("viewer")
        d.locator("#workspaceMemberSave").click()
        expect(d.get_by_label("이번 작업 변경 사유")).to_be_focused()
        d.get_by_label("이번 작업 변경 사유").fill(
            "Synthetic current membership change"
        )
        # Select the current row to use its real revision, rather than overwrite it.
        d.locator("#workspaceMemberList").get_by_role("button", name="수정").nth(
            1
        ).click()
        d.locator("#workspaceMemberRole").select_option("viewer")
        d.locator("#workspaceMemberSave").click()
        expect(d).not_to_be_visible()
        expect(page.locator("#workspaceStatus")).to_contain_text(
            "구성원을 저장했습니다."
        )
        page.get_by_role("button", name="저장본 보기", exact=True).first.click()
        d = page.locator("#workspaceSnapshotDialog")
        expect(d).to_be_visible()
        d.locator("#workspaceSnapshotList").get_by_role(
            "button", name="저장본 열기", exact=True
        ).first.click()
        with page.expect_download() as download:
            d.locator("#workspaceSnapshotDownload").click()
        payload = json.loads(Path(download.value.path()).read_text())
        assert payload["saved_snapshot"] and not payload["executable"]
        d.get_by_label("이번 작업 변경 사유").fill(
            "Synthetic exact private run authorization"
        )
        d.locator("#workspaceRunPrepare").click()
        expect(d.locator("#workspaceRunAuthority")).to_be_enabled()
        expect(d.locator("#workspaceRunAuthority")).not_to_be_checked()
        d.locator("#workspaceRunAuthority").check()
        d.locator("#workspaceRunExecute").click()
        expect(d.locator("#workspaceRunStatus")).to_contain_text("완료")
        assert w.calls.count("tools/call") == 1
        page.evaluate("location.hash='#/home'")
        expect(page.locator("dialog[open]")).to_have_count(0)
        assert not errors and not external
    finally:
        context.close()
        client.close()
