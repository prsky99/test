"""Renewal closure uses isolated sessions and data; no real provider or service."""

# ruff: noqa: F401,F811
import base64
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from agent_market import admin_completion
from agent_market.gateway.dashboard import log_buffer
from tests.test_dashboard import dash, H
from tests.test_admin_next import login
from tests.test_admin_reviewed_commands import reviewed
from tests.test_admin_acceptance import staff
from tests.test_workspace_execution_api import private_api
from tests.test_front_workflow_browser import browser
from tests.test_admin_next_browser import open_console, sign_in
from playwright.sync_api import expect


@pytest.mark.parametrize("development", ["0", "1"])
def test_production_legacy_demo_and_log_buffer_actions_are_closed(
    dash, monkeypatch, development
):
    world, c = dash
    monkeypatch.setenv("DEPLOYMENT_MODE", "production")
    monkeypatch.setenv("AGENTCON_ADMIN_DEV", development)
    world.app.state.front.simulate = Mock()
    for path in ("/admin/api/logs/clear", "/admin/api/visitors/simulate"):
        r = c.post(
            path,
            headers=H,
            json={"message": "hello", "reason": "Synthetic security review"},
        )
        assert r.status_code == 403
        assert c.post(path, json={}).status_code in (401, 403)
    assert not world.app.state.front.simulate.called
    html = c.get("/admin/ui").text
    assert (
        'id="clearLogs" hidden disabled' in html
        and 'id="simSend" hidden disabled' in html
    )


def test_explicit_development_actions_require_reason_and_audit(dash, monkeypatch):
    world, c = dash
    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("AGENTCON_ADMIN_DEV", "1")
    world.app.state.front.simulate = Mock(return_value={"synthetic": True})
    for path in ("/admin/api/logs/clear", "/admin/api/visitors/simulate"):
        assert c.post(path, headers=H, json={"message": "hello"}).status_code == 400
        assert (
            c.post(
                path,
                headers=H,
                json={"message": "hello", "reason": "Synthetic development review"},
            ).status_code
            == 200
        )
    actions = [
        r["action"]
        for r in world.store.query(
            "SELECT action FROM admin_audit_logs WHERE action LIKE 'DEV_%'"
        )
    ]
    assert (
        len(actions) == 4
        and "DEV_SIMULATE_INTENT" in actions
        and "DEV_LOG_BUFFER_CLEAR" in actions
    )
    _, h = staff(world, "admin")
    assert (
        c.post(
            "/admin/api/logs/clear", headers=h, json={"reason": "Synthetic review"}
        ).status_code
        == 403
    )


def test_uniform_v2_errors_csv_permissions_and_formula_protection(dash):
    world, c = dash
    h = login(c)
    for path, status in [
        ("/admin/api/v2/catalog/agents?limit=0", 400),
        ("/admin/api/v2/catalog/agents?limit=bad", 422),
    ]:
        r = c.get(path, headers=h)
        assert r.status_code == status
        assert {"detail", "message_ko", "error_code", "retryable"} <= r.json().keys()
        assert "no-store" in r.headers["cache-control"]
    rid = world.store.query("SELECT id FROM resources LIMIT 1")[0]["id"]
    with world.store.tx() as db:
        db.execute("UPDATE resources SET name='=HYPERLINK(unsafe)' WHERE id=?", (rid,))
    r = c.get("/admin/api/v2/catalog/agents?format=csv", headers=h)
    assert r.status_code == 200 and "'=HYPERLINK" in r.text
    assert "Content-Disposition".lower() in r.headers
    _, operator = staff(world, "operator")
    assert (
        c.get("/admin/api/v2/catalog/agents?format=csv", headers=operator).status_code
        == 403
    )
    assert c.get("/admin/api/v2/catalog/agents?format=csv").status_code == 401
    assert (
        c.get("/admin/api/v2/catalog/agents/" + str(rid), headers=h).json()["item"]
        == c.get("/admin/api/agents/" + str(rid), headers=h).json()["agent"]
    )


def test_request_cursor_has_stable_ties_and_does_not_repeat_newer_rows(dash):
    world, c = dash
    h = login(c)
    for n in range(4):
        world.store.record_customer_inquiry(
            category="general",
            name="Synthetic",
            email="synthetic@example.test",
            subject="Case " + str(n),
            message="Synthetic request",
        )
    with world.store.tx() as db:
        db.execute("UPDATE customer_inquiries SET created_at=1000")
    first = c.get("/admin/api/v2/requests/inquiries?limit=2", headers=h).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = c.get(
        "/admin/api/v2/requests/inquiries",
        headers=h,
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()
    assert len(second["items"]) == 2 and not second["next_cursor"]
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert not {"ip", "user_agent", "visitor_token_hash"} & first["items"][0].keys()
    for cursor in ("bad", base64.urlsafe_b64encode(b"[1,-1]").decode(), "a" * 121):
        assert (
            c.get(
                "/admin/api/v2/requests/inquiries", headers=h, params={"cursor": cursor}
            ).status_code
            == 400
        )


def test_home_has_actual_queues_and_no_private_audit_for_operator(reviewed):
    world, c, h = reviewed
    now = time.time()
    with world.store.tx() as db:
        db.execute(
            "INSERT INTO workspace_admin_commands VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "wc_synthetic",
                "cu_synthetic",
                "credit_adjust",
                1,
                "pending",
                1,
                None,
                now,
                now,
                "{}",
                "synthetic",
            ),
        )
    r = c.get("/admin/api/v2/home/work", headers=h)
    assert r.status_code == 200, r.text
    assert (
        r.json()["cases"] == 0
        and r.json()["incidents"] == 0
        and r.json()["audit_allowed"]
    )
    assert r.json()["reviews"] == 1
    _, operator = staff(world, "operator")
    value = c.get("/admin/api/v2/home/work", headers=operator).json()
    assert value["audit"] == [] and not value["audit_allowed"]
    assert c.get("/admin/api/v2/home/work").status_code in (401, 403)
    assert (
        c.get(
            "/admin/api/v2/home/work", headers={**h, "Origin": "https://evil.test"}
        ).status_code
        == 403
    )


def test_workflow_search_uses_current_membership_and_never_inputs(private_api):
    w = private_api
    path = "/admin/api/v2/home/workflows?q=Private"
    found = w.client.get(path, headers=w.headers["owner"])
    assert found.status_code == 200, found.text
    assert found.json()["items"][0]["id"] == w.draft["id"]
    assert (
        not {"definition", "input", "output", "description"}
        & found.json()["items"][0].keys()
    )
    assert w.client.get(path, headers=w.headers["outsider"]).json()["items"] == []
    assert w.client.get(path, headers=w.headers["operator"]).status_code == 403
    with w.store.tx() as db:
        db.execute("UPDATE workspace_memberships SET active=0 WHERE user_id=?", (1,))
    assert w.client.get(path, headers=w.headers["owner"]).json()["items"] == []


def test_customer_operations_v2_alias_keeps_the_original_authority(private_api):
    w = private_api
    old = "/admin/api/workspace-operations/options"
    new = "/admin/api/v2/customers/operations/options"
    for person in ("owner", "operator", "outsider"):
        original = w.client.get(old, headers=w.headers[person])
        alias = w.client.get(new, headers=w.headers[person])
        assert alias.status_code == original.status_code
        assert alias.json() == original.json()
        assert alias.headers["cache-control"] == "no-store"
    assert w.client.get(new).status_code == 401
    assert (
        w.client.get(
            new, headers={**w.headers["owner"], "Origin": "https://evil.test"}
        ).status_code
        == 403
    )


def test_storage_evidence_never_invents_backup_or_inspects_archive(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("AGENTCON_ADMIN_BACKUP_ROOT", raising=False)
    monkeypatch.delenv("AGENTCON_ADMIN_SQLITE_ARCHIVE", raising=False)
    assert admin_completion.file_evidence() == {
        "backup": {"configured": False},
        "archive": {"configured": False},
    }
    root = tmp_path / "backup"
    root.mkdir()
    created = time.time() - 100
    digest = hashlib.sha256(b"synthetic").hexdigest()
    (root / "manifest.json").write_text(
        json.dumps({"created": created, "files": {"database.dump": {"sha256": digest}}})
    )
    monkeypatch.setenv("AGENTCON_ADMIN_BACKUP_ROOT", str(root))
    value = admin_completion.file_evidence()["backup"]
    assert value["available"] and not value["restore_verified"]
    report = {
        "backup_sha256": digest,
        "completed": time.time(),
        "restore_rehearsed": True,
        "isolated_cluster": True,
        "production_modified": False,
    }
    (root / "restore-report.json").write_text(json.dumps(report))
    assert admin_completion.file_evidence()["backup"]["restore_verified"]
    report["backup_sha256"] = "0" * 64
    (root / "restore-report.json").write_text(json.dumps(report))
    assert not admin_completion.file_evidence()["backup"]["restore_verified"]
    archive = tmp_path / "old.sqlite3"
    archive.write_bytes(b"not a database; do not open")
    monkeypatch.setenv("AGENTCON_ADMIN_SQLITE_ARCHIVE", str(archive))
    assert (
        admin_completion.file_evidence()["archive"]["bytes"] == archive.stat().st_size
    )
    assert admin_completion.file_evidence()["archive"]["contents_inspected"] is False


def test_desktop_all_areas_and_common_table_controls(dash, browser):
    from agent_market.workspace_admin_events import migrate

    migrate(dash[0].store, dash[0].store._workspace_admin_identity_key)
    context, page, errors, external = open_console(dash, browser, width=1440)
    shots = Path("reports/admin-renewal-design-2026-10-21/closure/screenshots")
    try:
        sign_in(page)
        expect(
            page.get_by_role("heading", name="지금 처리할 작업", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("link", name="고객 작업 승인 열기", exact=True)).to_be_visible()
        for theme in ("light", "dark"):
            if theme == "dark":
                page.locator("#adm-theme").click()
            for area in (
                "home",
                "catalog",
                "gateway",
                "customers",
                "public",
                "security",
                "system",
            ):
                page.goto("https://admin.test/admin/next#/" + area)
                expect(page.locator("#adm-main h1")).to_be_visible()
                if area == "catalog":
                    expect(page.locator(".adm-column-choice").first).to_be_visible()
                    page.locator(".adm-column-choice summary").first.click()
                    page.get_by_label("출처 열 표시", exact=True).uncheck()
                    expect(
                        page.locator(".adm-table th").filter(has_text="출처")
                    ).to_have_count(0)
                    page.get_by_label("출처 열 표시", exact=True).check()
                    before = page.locator(".adm-table th").first.get_attribute(
                        "aria-sort"
                    )
                    page.get_by_role(
                        "button", name="에이전트 · 표시된 행 정렬", exact=True
                    ).click()
                    expect(page.locator(".adm-table th").first).to_have_attribute(
                        "aria-sort",
                        "descending" if before == "ascending" else "ascending",
                    )
                    page.locator(".adm-column-choice summary").first.click()
                assert not page.evaluate(
                    "document.documentElement.scrollWidth>innerWidth"
                )
                page.screenshot(
                    path=str(shots / ("after-" + area + "-" + theme + ".png")),
                    full_page=True,
                )
        page.goto("https://admin.test/admin/next#/catalog/agents/1?tab=evidence")
        expect(page.locator(".adm-drawer")).to_be_visible()
        page.keyboard.press("Escape")
        page.locator("#adm-search-kind").select_option("workflow")
        page.locator("#adm-search-input").fill("example")
        page.keyboard.press("Enter")
        expect(
            page.get_by_role("heading", name="워크플로 검색", exact=True)
        ).to_be_visible()
        page.locator("#adm-logout").click()
        expect(page.locator("#adm-login")).to_be_visible()
        assert not errors and not external
    finally:
        context.close()


def test_evidence_profile_is_optional_private_and_not_a_shell_script(tmp_path):
    from scripts.agentcon_config import read_admin_evidence_settings, ConfigError

    path = tmp_path / "evidence.env"
    assert read_admin_evidence_settings(path) == {}
    path.write_text(
        "AGENTCON_ADMIN_BACKUP_ROOT=private-backup\nAGENTCON_ADMIN_SQLITE_ARCHIVE=private-archive.sqlite3\n"
    )
    path.chmod(0o600)
    assert len(read_admin_evidence_settings(path)) == 2
    path.chmod(0o644)
    with pytest.raises(ConfigError):
        read_admin_evidence_settings(path)
    path.chmod(0o600)
    path.write_text("ADMIN_TOKEN=never-print-this\n")
    with pytest.raises(ConfigError) as error:
        read_admin_evidence_settings(path)
    assert "never-print-this" not in str(error.value)


def test_optional_storage_sampler_cannot_stall_projection_drain(monkeypatch):
    from types import SimpleNamespace
    from agent_market import workspace_admin_worker as module

    worker = module.OperationsWorker(SimpleNamespace(enabled=True, store=object()))
    worker._stop = Mock()
    worker._stop.is_set.side_effect = [False, False, True]
    for name in ("drain", "backfill", "prune"):
        monkeypatch.setattr(module, name, Mock(return_value=0))
    sample = Mock(side_effect=RuntimeError("Synthetic sample unavailable"))
    monkeypatch.setattr(admin_completion, "sample_storage", sample)
    worker._loop()
    assert module.drain.call_count == 2
    assert sample.call_count == 1
    assert worker.last_success is not None and worker.failure_count == 0
    assert worker.storage_failure_count == 1
