"""Isolated real-store/API tests: no operating accounts or money are touched."""

# ruff: noqa: F811 -- imported isolated fixtures are injected by pytest.
import time

import pytest

from agent_market import workspace_admin_events
from agent_market.gateway import admin_auth
from tests.test_dashboard import dash  # noqa: F401
from tests.test_admin_next import login

ROOT = "/admin/api/v2/finance"


@pytest.fixture
def finance(dash):
    world, client = dash
    workspace_admin_events.migrate(world.store, b"finance-test-workbench-key-32-2026")
    with world.store.tx() as db:
        db.execute(
            "UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'"
        )
    staff = login(client)
    world.store.deposit_credit("qa-finance-main", 20_000_000)
    old = world.store.hold_credit("qa-finance-main", 3_000_000, 0, "qa-old")
    fresh = world.store.hold_credit("qa-finance-main", 1_000_000, 0, "qa-fresh")
    with world.store.tx() as db:
        db.execute(
            "UPDATE clearing_ledger SET created_at=? WHERE tx_id=?",
            (time.time() - 3600, old),
        )
    return world, client, staff, old, fresh


def proposal(finance, **body):
    _, client, staff, _, _ = finance
    return client.post(
        ROOT + "/quote",
        headers=staff,
        json={
            "action": "deposit",
            "account_id": "qa-finance-main",
            "amount": "1.25",
            "reason": "검증된 장부 변경 테스트",
            **body,
        },
    )


def request(finance, **body):
    _, client, staff, _, _ = finance
    quote = proposal(finance, **body)
    assert quote.status_code == 200, quote.text
    result = client.post(ROOT + "/requests", headers=staff, json=quote.json())
    assert result.status_code == 202, result.text
    return result.json()["review"]


def approve(finance, item, **body):
    _, client, staff, _, _ = finance
    return client.post(
        "/admin/api/v2/reviews/" + item["id"] + "/approve",
        headers=staff,
        json={
            "revision": item["revision"],
            "reason": "대상과 금액 검토 완료",
            "acknowledge": True,
            **body,
        },
    )


def test_exact_summary_filter_and_noncache(finance):
    _, client, staff, _, _ = finance
    response = client.get(ROOT, headers=staff)
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["summary"]["balance"] == "20000000" and d["summary"]["held"] == "4000000"
    assert d["summary"]["overdue_count"] == 1 and d["summary"]["delta"] == "0"
    assert (
        d["external_reserves_verified"] is False and d["mode"] == "virtual_ledger_only"
    )
    assert "no-store" in response.headers["cache-control"]
    assert client.get(ROOT + "?q=nonexistent", headers=staff).json()["total"] == 0
    assert client.get(ROOT + "?status=held", headers=staff).json()["total"] == 2
    assert client.get(ROOT + "?status=settled", headers=staff).json()["total"] == 0
    assert client.get(ROOT + "?q=qa_finance", headers=staff).json()["total"] == 0
    assert client.get(ROOT + "?offset=-1", headers=staff).status_code == 400
    assert client.get(ROOT + "?since=nan", headers=staff).status_code == 400
    assert client.get(ROOT + "?status=bogus", headers=staff).status_code == 400


@pytest.mark.parametrize(
    "amount",
    ["0", "-1", "NaN", 1, True, "1.0000001", "1e3", "1000000.000001", "0.000000", "01"],
)
def test_invalid_exact_unit_inputs(finance, amount):
    assert proposal(finance, amount=amount).status_code == 400


def test_deposit_review_approval_and_no_replay(finance):
    world, client, staff, _, _ = finance
    item = request(finance)
    assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000
    assert approve(finance, item, acknowledge=False).status_code == 403
    result = approve(finance, item)
    assert result.status_code == 200, result.text
    assert result.json()["item"]["status"] == "applied"
    assert world.store.get_credit("qa-finance-main")["balance"] == 21_250_000
    assert approve(finance, item).status_code == 409
    assert (
        client.post(
            ROOT + "/requests", headers=staff, json=proposal(finance).json()
        ).status_code
        == 202
    )


def test_refund_releases_hold_without_creating_money(finance):
    world, _, _, old, _ = finance
    item = request(finance, action="refund", tx_id=old)
    assert approve(finance, item).json()["item"]["status"] == "applied"
    account = world.store.get_credit("qa-finance-main")
    assert account["balance"] == 20_000_000 and account["held"] == 1_000_000
    assert proposal(finance, action="refund", tx_id=old).status_code == 400


def test_withdraw_is_ledger_only_and_cannot_spend_hold(finance):
    world, _, _, _, _ = finance
    assert (
        proposal(
            finance, action="withdraw", amount="17", address="0x" + "1" * 40
        ).status_code
        == 400
    )
    item = request(
        finance, action="withdraw", amount="2.000001", address="0x" + "1" * 40
    )
    result = approve(finance, item).json()["item"]
    assert result["status"] == "applied"
    assert '"external_transfer":false' in result["result"]
    assert world.store.get_credit("qa-finance-main")["balance"] == 17_999_999


def test_sweep_exact_set_excludes_new_candidates(finance):
    world, _, _, old, fresh = finance
    item = request(finance, action="sweep")
    # A new account's overdue hold must not enter this approved set.
    world.store.deposit_credit("qa-finance-other", 1_000_000)
    other = world.store.hold_credit("qa-finance-other", 1_000_000, 0, "qa-other")
    with world.store.tx() as db:
        db.execute(
            "UPDATE clearing_ledger SET created_at=? WHERE tx_id=?",
            (time.time() - 3600, other),
        )
    assert approve(finance, item).json()["item"]["status"] == "applied"
    assert world.store.get_credit("qa-finance-main")["held"] == 1_000_000
    assert world.store.get_credit("qa-finance-other")["held"] == 1_000_000


def test_stale_snapshot_blocks_entire_mutation(finance):
    world, _, _, _, _ = finance
    item = request(finance)
    world.store.deposit_credit("qa-finance-main", 1)
    assert approve(finance, item).json()["item"]["status"] == "failed"
    assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_001


def test_signed_quote_cannot_be_edited_and_duplicate_pending_blocked(finance):
    _, client, staff, _, _ = finance
    data = proposal(finance).json()
    data["quote"]["amount"] = "999999999"
    assert client.post(ROOT + "/requests", headers=staff, json=data).status_code == 409
    request(finance)
    d = proposal(finance).json()
    assert client.post(ROOT + "/requests", headers=staff, json=d).status_code == 409
    assert (
        client.post(
            ROOT + "/quote",
            headers={**staff, "Content-Type": "application/json"},
            content='{"action":"deposit","amount":"1","amount":"2"}',
        ).status_code
        == 400
    )


def test_roles_origins_and_financial_review_confidentiality(finance):
    world, client, staff, _, _ = finance
    item = request(finance)
    with world.store.tx() as db:
        user = admin_auth.create_admin_user(
            db,
            "finance-nonprivileged",
            "Finance-test-password",
            "Finance viewer",
            "admin",
        )
        token = admin_auth.create_session(
            db, user["id"], user["username"], user["role"], user["name"]
        )
    other = {"X-Dashboard": "1", "authorization": "Bearer " + token}
    assert client.get(ROOT, headers=other).status_code == 403
    assert client.get(ROOT, headers={"X-Dashboard": "1"}).status_code == 401
    assert (
        client.get(ROOT, headers={**staff, "Origin": "https://evil.test"}).status_code
        == 403
    )
    assert all(
        i["kind"] != "finance_change"
        for i in client.get("/admin/api/v2/reviews", headers=other).json()["items"]
    )
    assert (
        client.get("/admin/api/v2/reviews/" + item["id"], headers=other).status_code
        == 403
    )
    assert (
        client.post(
            "/admin/api/v2/reviews/" + item["id"] + "/cancel",
            headers=other,
            json={"revision": 1, "reason": "허용되지 않은 철회"},
        ).status_code
        == 403
    )


def test_missing_migration_allows_read_only(dash):
    _, client = dash
    staff = login(client)
    assert client.get(ROOT, headers=staff).json()["review_available"] is False
    assert (
        client.post(
            ROOT + "/quote", headers=staff, json={"reason": "준비되지 않은 변경"}
        ).status_code
        == 409
    )


def test_financial_unknown_apply_never_replays_and_can_be_inspected(
    finance, monkeypatch
):
    world, client, staff, _, _ = finance
    from agent_market.admin_finance_workbench import FinanceWorkbench

    original = FinanceWorkbench.apply
    calls = []

    def committed_then_disconnected(self, payload, uid):
        calls.append(payload["action"])
        original(self, payload, uid)
        raise RuntimeError("synthetic transport failure after commit")

    # The existing installed applier is bound; induce a commit response failure
    # at its result construction after the financial transaction completes.
    from agent_market.workspace_admin_reviewed import ReviewedCommands

    real_approve = ReviewedCommands.approve

    def approve_once(self, *args):
        prior = self.appliers["finance_change"]
        self.appliers["finance_change"] = (
            lambda payload, uid: committed_then_disconnected(
                prior.__self__, payload, uid
            )
        )
        try:
            return real_approve(self, *args)
        finally:
            self.appliers["finance_change"] = prior

    monkeypatch.setattr(ReviewedCommands, "approve", approve_once)
    item = request(finance)
    result = approve(finance, item)
    assert result.json()["item"]["status"] == "unknown"
    assert world.store.get_credit("qa-finance-main")["balance"] == 21_250_000
    assert approve(finance, item).status_code == 409
    assert calls == ["deposit"]
    lookup = client.get("/admin/api/v2/reviews/" + item["id"], headers=staff)
    assert lookup.json()["item"]["status"] == "unknown"
    proof = client.get(ROOT + "/requests/" + item["id"] + "/evidence", headers=staff)
    assert proof.status_code == 200
    assert proof.json()["application_recorded"] is True
    assert proof.json()["reference"] == "fin_" + item["id"][4:]
    assert "no-store" in proof.headers["cache-control"]


def test_broken_account_cannot_be_topped_up_or_refunded(finance):
    world, _, _, old, _ = finance
    with world.store.tx() as db:
        db.execute(
            "UPDATE agent_credits SET held=held+1 WHERE account_id='qa-finance-main'"
        )
    assert proposal(finance).status_code == 400
    assert proposal(finance, action="refund", tx_id=old).status_code == 400


def test_expired_quote_and_foreign_origin_write_are_blocked(finance, monkeypatch):
    _, client, staff, _, _ = finance
    data = proposal(finance).json()
    import agent_market.admin_next as console

    real_clock = time.time
    monkeypatch.setattr(console.time, "time", lambda: real_clock() + 301)
    assert client.post(ROOT + "/requests", headers=staff, json=data).status_code == 409
    assert (
        client.post(
            ROOT + "/quote",
            headers={**staff, "Origin": "https://evil.test"},
            json={"reason": "cross origin test"},
        ).status_code
        == 403
    )


def test_signed_preview_has_stable_id_and_identical_request_is_idempotent(finance):
    world, client, staff, _, _ = finance
    quote = proposal(finance).json()
    expected = quote["quote"]["request_id"]
    first = client.post(ROOT + "/requests", headers=staff, json=quote)
    second = client.post(ROOT + "/requests", headers=staff, json=quote)
    assert first.status_code == second.status_code == 202
    assert first.json()["review"]["id"] == second.json()["review"]["id"] == expected
    assert len(client.get(ROOT, headers=staff).json()["reviews"]) == 1
    assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000


def test_tampered_command_is_blocked_without_hiding_healthy_ledger(finance):
    world, client, staff, _, _ = finance
    item = request(finance)
    with world.store.tx() as db:
        db.execute(
            "UPDATE admin_reviewed_commands SET payload=? WHERE id=?",
            ("{}", item["id"]),
        )
    response = client.get(ROOT, headers=staff)
    assert response.status_code == 200
    record = response.json()["reviews"][0]
    assert record["status"] == "integrity_review_required" and record["payload"] is None
    assert approve(finance, item).status_code == 409
    assert world.store.get_credit("qa-finance-main")["balance"] == 20_000_000
