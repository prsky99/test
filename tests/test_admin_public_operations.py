"""Native public-service migration uses synthetic data and the actual review fence."""

# ruff: noqa: F401,F811
import json
import time
from urllib.parse import quote

import pytest
from agent_market.gateway import admin_auth
from tests.test_admin_reviewed_commands import reviewed, act
from tests.test_dashboard import dash
from tests.test_task_updates_security import updates, catalog
from tests.test_visitor_desk import desk, register
from tests.test_front_workflow_browser import browser
from tests.test_workspace_admin_browser import browser_context
from tests.conftest import staff_headers

BASE = "/admin/api/v2/public/operations"


def send(client, staff, domain, action, target=None, fields=None, **extra):
    return client.post(
        BASE + "/" + domain,
        headers=staff,
        json={
            "action": action,
            "target": target,
            "fields": fields or {},
            "reason": "Synthetic exact public change review",
            **extra,
        },
    )


def apply(client, staff, response):
    assert response.status_code == 202, response.text
    return act(client, staff, response.json()["review"], acknowledge=True)


def graph(world):
    rid = world.store.query("SELECT id FROM resources WHERE kind='mcp'")[0]["id"]
    return {
        "name": "Public Documentation Lookup",
        "description": "Find public reference material",
        "nodes": [
            {
                "id": "lookup",
                "name": "Lookup",
                "type": "agent",
                "kind": "mcp",
                "resource_id": rid,
                "data": {"tool": "search", "input": {"query": "public research"}},
            }
        ],
        "edges": [],
    }


def test_public_aliases_preserve_individual_origin_and_sensitive_roles(reviewed):
    world, c, h = reviewed
    assert c.get(BASE + "/options").status_code in (401, 403)
    assert (
        c.get(
            BASE + "/options", headers={**h, "Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert (
        c.get(
            BASE + "/source/visitors",
            headers={"X-Dashboard": "1", "Authorization": "Bearer secret"},
        ).status_code
        == 401
    )
    assert c.get(BASE + "/source/sns/feed", headers=h).status_code == 200
    with world.store.tx() as db:
        viewer = admin_auth.create_admin_user(
            db, "public-viewer", "Synthetic-viewer-password", "Viewer", "viewer"
        )
        raw = admin_auth.create_session(
            db, viewer["id"], viewer["username"], viewer["role"], viewer["name"]
        )
    limited = {"X-Dashboard": "1", "Authorization": "Bearer " + raw}
    assert c.get(BASE + "/source/visitors", headers=limited).status_code == 403
    assert (
        send(c, limited, "sns", "create", fields={"body": "Public note"}).status_code
        == 403
    )


def test_original_sns_path_requests_review_before_publication_and_archiving(reviewed):
    world, c, h = reviewed
    before = world.store.query("SELECT COUNT(*) AS n FROM sns_posts")[0]["n"]
    response = c.post(
        "/admin/api/sns/posts",
        headers=h,
        json={
            "body": "A reviewed public reference update.",
            "author": "Private staff name",
            "client": "forged-client",
            "role": "developer",
            "reason": "Synthetic public post review",
        },
    )
    assert response.status_code == 202, response.text
    assert world.store.query("SELECT COUNT(*) AS n FROM sns_posts")[0]["n"] == before
    result = apply(c, h, response)
    assert result.status_code == 200, result.text
    item = result.json()["item"]
    assert item["status"] == "applied"
    key = (
        item["result"]
        if isinstance(item["result"], dict)
        else json.loads(item["result"])
    )
    row = world.store.query(
        "SELECT author,body FROM sns_posts ORDER BY id DESC LIMIT 1"
    )[0]
    assert row["author"] == "Agent Concierge" and "Private staff name" not in str(row)
    assert act(c, h, response.json()["review"], acknowledge=True).status_code == 409
    remove = send(c, h, "sns", "delete", target=key["key"])
    assert remove.status_code == 202
    assert (
        world.store.query("SELECT deleted FROM sns_posts ORDER BY id DESC LIMIT 1")[0][
            "deleted"
        ]
        == 0
    )
    assert apply(c, h, remove).json()["item"]["status"] == "applied"
    assert (
        world.store.query("SELECT deleted FROM sns_posts ORDER BY id DESC LIMIT 1")[0][
            "deleted"
        ]
        == 1
    )


def test_security_restrictions_apply_now_but_weakening_and_bulk_release_are_reviewed(
    reviewed,
):
    world, c, h = reviewed
    one = "203.0.113.71"
    two = "203.0.113.72"
    assert send(c, h, "security", "block", one, {"duration": 3600}).status_code == 200
    assert send(c, h, "security", "block", two, {"duration": 3600}).status_code == 200
    requested = send(c, h, "security", "remove_blocks", [one, two])
    assert requested.status_code == 202, requested.text
    assert len(world.store.query("SELECT * FROM security_ip_rules")) == 2
    # Concurrent rule replacement invalidates the exact approved set.
    assert send(c, h, "security", "block", one, {"duration": 7200}).status_code == 200
    rejected = apply(c, h, requested)
    assert rejected.json()["item"]["status"] == "failed"
    assert len(world.store.query("SELECT * FROM security_ip_rules")) == 2
    requested = c.delete(
        "/admin/api/security/rules/" + one,
        headers={**h, "X-Admin-Reason": quote("Synthetic unblock review")},
    )
    assert requested.status_code == 202, requested.text
    assert apply(c, h, requested).json()["item"]["status"] == "applied"
    assert not world.store.query("SELECT * FROM security_ip_rules WHERE ip=?", (one,))
    allowed = send(c, h, "security", "allow", two)
    assert (
        world.store.query("SELECT action FROM security_ip_rules WHERE ip=?", (two,))[0][
            "action"
        ]
        == "block"
    )
    assert apply(c, h, allowed).json()["item"]["status"] == "applied"


def test_security_attack_rate_current_state_and_nonfinite_inputs(reviewed):
    world, c, h = reviewed
    assert (
        send(c, h, "security", "under_attack", fields={"enabled": True}).status_code
        == 200
    )
    release = c.post(
        "/admin/api/security/under-attack",
        headers=h,
        json={"enabled": False, "reason": "Synthetic defense relaxation review"},
    )
    assert release.status_code == 202, release.text
    assert world.app.state.front.security.get_status()["under_attack_mode"] is True
    assert apply(c, h, release).json()["item"]["status"] == "applied"
    assert send(c, h, "security", "rate", fields={"multiplier": 0.5}).status_code == 200
    change = send(c, h, "security", "rate", fields={"multiplier": 1})
    assert change.status_code == 202
    assert apply(c, h, change).json()["item"]["status"] == "applied"
    for raw in ("NaN", "Infinity", "true"):
        response = c.post(
            BASE + "/security",
            headers={**h, "Content-Type": "application/json"},
            content='{"action":"rate","fields":{"multiplier":'
            + raw
            + '},"reason":"Synthetic invalid input"}',
        )
        assert response.status_code in (400, 409)


def test_template_draft_publish_edit_drift_and_legacy_paths_share_review(reviewed):
    world, c, h = reviewed
    value = graph(world)
    saved = send(c, h, "template", "create", fields=value)
    assert saved.status_code == 200, saved.text
    wid = saved.json()["result"]["workflow_id"]
    assert not world.store.get_workflow(wid)["is_template"]
    current = c.get(BASE + "/templates/" + str(wid), headers=h).json()
    requested = send(
        c, h, "template", "publish", wid, value, revision=current["revision"]
    )
    assert not world.store.get_workflow(wid)["is_template"]
    assert apply(c, h, requested).json()["item"]["status"] == "applied"
    assert world.store.get_workflow(wid)["is_template"] == 1
    edited = c.put(
        "/admin/api/workflows/" + str(wid),
        headers=h,
        json={
            "name": "Reviewed Updated Definition",
            "reason": "Synthetic legacy edit review",
        },
    )
    assert edited.status_code == 202, edited.text
    assert world.store.get_workflow(wid)["name"] == value["name"]
    world.store.update_workflow(wid, {"description": "Concurrent source change"})
    assert apply(c, h, edited).json()["item"]["status"] == "failed"
    stop = c.delete(
        "/admin/api/workflows/" + str(wid),
        headers={**h, "X-Admin-Reason": quote("Synthetic publication withdrawal")},
    )
    assert apply(c, h, stop).json()["item"]["status"] == "applied"
    assert (
        world.store.get_workflow(wid) and not world.store.get_workflow(wid)["is_active"]
    )


def test_untrusted_template_and_post_values_never_become_public(reviewed):
    world, c, h = reviewed
    assert (
        send(
            c, h, "sns", "create", fields={"body": "Bearer secret-should-not-publish"}
        ).status_code
        == 409
    )
    value = graph(world)
    value["nodes"][0]["data"]["credential_refs"] = {"key": "platform-secret"}
    assert send(c, h, "template", "create", fields=value).status_code in (400, 409)
    assert (
        send(
            c, h, "sns", "create", fields={"body": "Public update", "role": "agent"}
        ).status_code
        == 409
    )


@pytest.mark.usefixtures("rotated_bootstrap_admin")
def test_task_processing_queues_without_capability_tokens_and_rechecks_consent(desk):
    from agent_market.workspace_admin_events import migrate

    store, front, client, add, visitor_headers, courier, data, vid, admin = desk
    migrate(store, b"synthetic-public-integration-key32")
    h = staff_headers(admin)
    with store.tx() as db:
        db.execute(
            "UPDATE admin_users SET active=0 WHERE role='superadmin' AND id!=(SELECT user_id FROM admin_sessions WHERE token=?)",
            (
                admin_auth.session_reference(
                    (h.get("Authorization") or h["authorization"])[7:]
                ),
            ),
        )
    wid = register(desk)
    add("Latest Reviewed Weather", report_at=time.time())
    preview = admin.get(
        "/admin/api/visitors/" + vid + "/task-updates/" + wid + "/preview", headers=h
    ).json()
    assert "can_process" in preview, preview
    assert preview["can_process"]
    path = "/admin/api/visitors/" + vid + "/task-updates/" + wid + "/process"
    request = admin.post(
        path,
        headers=h,
        json={
            "preview_token": preview["preview_token"],
            "reason": "Synthetic task delivery review",
        },
    )
    assert request.status_code == 202, request.text
    assert not courier.events and preview["preview_token"] not in request.text
    assert (
        preview["preview_token"]
        not in store.query("SELECT payload FROM admin_reviewed_commands")[0]["payload"]
    )
    front.updates.action(vid, wid, "stop")
    assert apply(admin, h, request).json()["item"]["status"] == "failed"
    assert not courier.events
    assert (
        admin.post(
            "/admin/api/visitors/" + vid + "/task-updates/" + wid + "/action",
            headers=h,
            json={"action": "resume", "reason": "Cannot restore consent"},
        ).status_code
        == 400
    )
    assert (
        admin.post(
            "/admin/api/needs/cancellations/fake/reactivate",
            headers=h,
            json={"notes": "Claimed consent"},
        ).status_code
        == 409
    )


def test_native_template_editor_saves_private_draft_then_requests_publication(
    reviewed, browser
):
    from playwright.sync_api import expect

    world, client, h = reviewed
    _, context, page, errors, external = browser_context(
        browser, world.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps((h.get("Authorization") or h["authorization"])[7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/public/templates")
        page.get_by_role("button", name="새 공개용 초안", exact=True).click()
        drawer = page.locator(".adm-drawer")
        value = graph(world)
        drawer.get_by_label("영어 이름", exact=True).fill(value["name"])
        drawer.get_by_label("영어 설명", exact=True).fill(value["description"])
        drawer.get_by_label("노드·연결 JSON", exact=True).fill(
            json.dumps({"nodes": value["nodes"], "edges": []})
        )
        drawer.get_by_role("button", name="비공개 초안 저장", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic private draft save"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text("변경 결과")
        assert not world.store.query(
            "SELECT id FROM agent_workflows WHERE name=? AND is_template=1",
            (value["name"],),
        )
        page.get_by_role("link", name="정의 목록 다시 조회", exact=True).click()
        page.get_by_role("table", name="관리자 워크플로 정의").get_by_text(
            value["name"], exact=True
        ).click()
        page.get_by_role("button", name="공개 게시 승인 요청", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic template publish review"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text(
            "아직 게시·발송·보안 완화가 적용되지 않았습니다."
        )
        assert not world.store.query(
            "SELECT id FROM agent_workflows WHERE name=? AND is_template=1",
            (value["name"],),
        )
        assert not errors and not external
    finally:
        context.close()


def test_review_failure_after_effect_is_unknown_and_never_replayed(
    reviewed, monkeypatch
):
    world, c, h = reviewed
    requested = send(
        c, h, "sns", "create", fields={"body": "A public synthetic once-only note."}
    )
    from agent_market.gateway import sns

    original = sns.create_post

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic response loss after side effect")

    monkeypatch.setattr(sns, "create_post", interrupted)
    result = apply(c, h, requested)
    assert result.json()["item"]["status"] == "unknown"
    assert act(c, h, requested.json()["review"], acknowledge=True).status_code == 409
    # SQLite transaction rollback or a committed effect is safe; neither may be replayed.
    assert (
        len(
            world.store.query(
                "SELECT id FROM sns_posts WHERE body=?",
                ("A public synthetic once-only note.",),
            )
        )
        <= 1
    )


def test_review_requires_independent_current_staff_and_exact_source_state(reviewed):
    world, c, h = reviewed
    requested = send(
        c, h, "sns", "create", fields={"body": "A note requiring a second reviewer."}
    )
    with world.store.tx() as db:
        user = admin_auth.create_admin_user(
            db,
            "other-public-reviewer",
            "Synthetic-other-password",
            "Other",
            "superadmin",
        )
        raw = admin_auth.create_session(
            db, user["id"], user["username"], user["role"], user["name"]
        )
    other = {"X-Dashboard": "1", "Authorization": "Bearer " + raw}
    assert act(c, h, requested.json()["review"], acknowledge=True).status_code == 403
    with world.store.tx() as db:
        db.execute("UPDATE admin_users SET role='viewer' WHERE username='sadmin'")
    result = act(c, other, requested.json()["review"])
    assert result.status_code == 200 and result.json()["item"]["status"] == "failed"
    assert not world.store.query("SELECT id FROM sns_posts")


@pytest.mark.usefixtures("rotated_bootstrap_admin")
@pytest.mark.parametrize("expired", [False, True])
def test_exact_task_review_success_once_and_original_preview_expiry(
    desk, monkeypatch, expired
):
    from agent_market.workspace_admin_events import migrate

    store, front, client, add, visitor_headers, courier, data, vid, admin = desk
    migrate(store, b"synthetic-public-integration-key32")
    h = staff_headers(admin)
    with store.tx() as db:
        db.execute(
            "UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'"
        )
    wid = register(desk)
    add("Latest Weather For Review", report_at=time.time())
    base = "/admin/api/visitors/" + vid + "/task-updates/" + wid
    preview = admin.get(base + "/preview", headers=h).json()
    requested = admin.post(
        base + "/process",
        headers=h,
        json={
            "preview_token": preview["preview_token"],
            "reason": "Synthetic exact task approval",
        },
    )
    assert requested.status_code == 202, requested.text
    if expired:
        # The 15-minute queue must not extend a five-minute preview.
        monkeypatch.setattr(
            "agent_market.workspace_admin_public.time.time",
            lambda: preview["expires_at"] + 1,
        )
    result = apply(admin, h, requested)
    assert result.status_code == 200, result.text
    assert result.json()["item"]["status"] == (
        "failed" if expired else "applied"
    ), result.text
    assert len(courier.events) == (0 if expired else 1)
    assert (
        act(admin, h, requested.json()["review"], acknowledge=True).status_code == 409
    )


def test_native_sns_and_security_show_pending_instead_of_false_success(
    reviewed, browser
):
    from playwright.sync_api import expect

    world, client, h = reviewed
    _, context, page, errors, external = browser_context(
        browser, world.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps((h.get("Authorization") or h["authorization"])[7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/public/sns")
        page.get_by_role("button", name="공식 글 작성", exact=True).click()
        drawer = page.locator(".adm-drawer")
        drawer.get_by_label("공개 영어 본문", exact=True).fill(
            "A synthetic public service announcement."
        )
        drawer.get_by_role("button", name="게시 승인 요청", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic official post review"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text(
            "아직 게시·발송·보안 완화가 적용되지 않았습니다."
        )
        assert not world.store.query("SELECT id FROM sns_posts")
        page.get_by_role("link", name="승인 대기 목록 열기", exact=True).click()
        page.get_by_role("button", name="검토 후 적용", exact=True).first.click()
        dialog = page.locator(".adm-dialog")
        expect(dialog).to_contain_text("A synthetic public service announcement.")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic exact content approval"
        )
        dialog.get_by_role("checkbox").check()
        dialog.get_by_role("button", name="적용", exact=True).click()
        expect(
            page.get_by_role("button", name="검토 후 적용", exact=True)
        ).to_have_count(0)
        assert len(world.store.query("SELECT id FROM sns_posts")) == 1
        page.goto("https://admin.test/admin/next#/security/rules")
        page.get_by_label("보안 변경", exact=True).select_option("allow")
        page.get_by_label("대상 IP / 일괄 해제할 IP JSON 배열", exact=True).fill(
            "203.0.113.99"
        )
        page.get_by_role("button", name="보안 변경 검토", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic allowlist review"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text(
            "아직 게시·발송·보안 완화가 적용되지 않았습니다."
        )
        assert not world.store.query("SELECT ip FROM security_ip_rules")
        assert not errors and not external
    finally:
        context.close()


def test_native_contact_history_preview_and_notification_drawers(desk, browser):
    from playwright.sync_api import expect
    from tests.conftest import STAFF

    store, front, client, add, visitor_headers, courier, data, vid, admin = desk
    wid = register(desk)
    add("Newest Synthetic Weather", report_at=time.time())
    note = "<img src=x onerror=alert(1)> Synthetic internal case note"
    assert (
        admin.post(
            "/admin/api/visitors/" + vid + "/case",
            headers=STAFF,
            json={"status": "reviewing", "version": 0, "note": note},
        ).status_code
        == 200
    )
    _, context, page, errors, external = browser_context(
        browser, admin.app, "https://admin.test"
    )
    context.add_init_script(
        'sessionStorage.setItem("adminToken",'
        + json.dumps(STAFF["Authorization"][7:])
        + ");"
    )
    try:
        page.goto("https://admin.test/admin/next#/public/visitors")
        page.get_by_role("table", name="기록된 방문 에이전트").locator(
            "tbody tr"
        ).first.click()
        expect(page.locator(".adm-drawer")).to_contain_text(
            "Synthetic internal case note"
        )
        assert not page.locator(".adm-drawer img").count()
        assert "private-routing-secret" not in page.locator(".adm-drawer").inner_text()
        page.get_by_role("button", name="정확한 단건 미리보기", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text("Newest Synthetic Weather")
        assert "preview_token" not in page.locator(".adm-drawer").inner_text()
        page.get_by_role("button", name="단건 처리 승인 요청", exact=True).click()
        dialog = page.locator(".adm-dialog")
        dialog.get_by_label("변경 사유 (감사 기록에 남습니다)").fill(
            "Synthetic contact UI approval"
        )
        dialog.get_by_role("button", name="검토한 요청 등록", exact=True).click()
        expect(page.locator(".adm-drawer")).to_contain_text(
            "아직 게시·발송·보안 완화가 적용되지 않았습니다."
        )
        assert not courier.events
        page.goto("https://admin.test/admin/next#/public/notifications")
        page.get_by_role("table", name="알림 설정").locator("tbody tr").first.click()
        expect(page.locator(".adm-drawer")).to_contain_text(wid)
        assert "private-routing-secret" not in page.locator(".adm-drawer").inner_text()
        assert not errors and not external
    finally:
        context.close()
