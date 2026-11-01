"""Reviewed, exact-unit virtual-ledger operations for the administrator workbench.

No external payout is performed here. Fixed SQL only; financial effects, snapshot
checks and audit evidence share one application-store transaction. Approval is
handled by the existing signed reviewed-command service, never by this module.
"""

import hashlib
import re
import time
import uuid
from decimal import Decimal

from .workspace_admin_events import (
    audit,
    canonical,
    execute,
    register,
    rows,
    transaction,
)

MAX = 2**63 - 1
ACCOUNT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,159}")
register(
    {
        "finance_application_audit": "SELECT actor,action,object_id,created FROM workspace_admin_audit WHERE object_id=? AND action=? ORDER BY created DESC LIMIT 1",
        "finance_account": "SELECT * FROM agent_credits WHERE account_id=?",
        "finance_tx": "SELECT * FROM clearing_ledger WHERE tx_id=?",
        "finance_invariants": "SELECT COALESCE(SUM(CASE WHEN status='held' THEN amount ELSE 0 END),0) AS held, SUM(CASE WHEN amount<=0 OR status NOT IN ('held','settled','refunded','withdrawn') THEN 1 ELSE 0 END) AS invalid FROM clearing_ledger WHERE account_id=?",
        "finance_summary": "SELECT COUNT(*) AS accounts,COALESCE(SUM(balance),0) AS balance,COALESCE(SUM(held),0) AS held,COALESCE(SUM(total_deposited),0) AS deposited,COALESCE(SUM(total_spent),0) AS spent FROM agent_credits",
        "finance_overdue": "SELECT COUNT(*) AS n,COALESCE(SUM(amount),0) AS amount FROM clearing_ledger WHERE status='held' AND created_at<?",
        "finance_account_list": "SELECT * FROM agent_credits WHERE LOWER(account_id) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC,account_id LIMIT ? OFFSET ?",
        "finance_account_count": "SELECT COUNT(*) AS n FROM agent_credits WHERE LOWER(account_id) LIKE ? ESCAPE '\\'",
        "finance_tx_list": "SELECT * FROM clearing_ledger WHERE (status=? OR ?='') AND LOWER(account_id) LIKE ? ESCAPE '\\' AND created_at>=? AND created_at<=? ORDER BY created_at DESC,tx_id DESC LIMIT ? OFFSET ?",
        "finance_tx_count": "SELECT COUNT(*) AS n FROM clearing_ledger WHERE (status=? OR ?='') AND LOWER(account_id) LIKE ? ESCAPE '\\' AND created_at>=? AND created_at<=?",
        "finance_candidates": "SELECT * FROM clearing_ledger WHERE status='held' AND created_at<? ORDER BY created_at,tx_id LIMIT 21",
        "finance_create": "INSERT INTO agent_credits(account_id,balance,held,total_deposited,total_spent,updated_at) VALUES(?,0,0,0,0,?) ON CONFLICT(account_id) DO NOTHING",
        "finance_deposit": "UPDATE agent_credits SET balance=balance+?,total_deposited=total_deposited+?,updated_at=? WHERE account_id=?",
        "finance_withdraw": "UPDATE agent_credits SET balance=balance-?,total_spent=total_spent+?,updated_at=? WHERE account_id=?",
        "finance_release": "UPDATE agent_credits SET held=held-?,updated_at=? WHERE account_id=?",
        "finance_refund": "UPDATE clearing_ledger SET status='refunded',receipt=?,settled_at=? WHERE tx_id=? AND status='held'",
        "finance_withdraw_tx": "INSERT INTO clearing_ledger(tx_id,account_id,resource_id,tool_name,amount,status,sla_verified,receipt,created_at,settled_at) VALUES(?,?,0,'admin_recall',?,'withdrawn',0,?,?,?)",
    }
)


def money(value):
    if type(value) is not str or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,6})?", value
    ):
        raise ValueError("금액은 USDC 단위로 소수점 6자리까지 입력하세요.")
    result = int(Decimal(value) * 1000000)
    if not 1 <= result <= 10**12:
        raise ValueError("금액은 0보다 크고 1,000,000 USDC 이하여야 합니다.")
    return result


def project(row):
    return {
        key: str(value)
        if key in ("balance", "held", "total_deposited", "total_spent", "amount")
        else value
        for key, value in row.items()
        if key != "receipt"
    }


def stamp(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class FinanceWorkbench:
    def __init__(self, store):
        self.store = store

    def _account(self, db, account):
        found = rows(db, "finance_account", (account,))
        value = (
            found[0]
            if found
            else dict(
                account_id=account,
                balance=0,
                held=0,
                total_deposited=0,
                total_spent=0,
                updated_at=0,
            )
        )
        if any(
            type(value[k]) is not int or not 0 <= value[k] <= MAX
            for k in ("balance", "held", "total_deposited", "total_spent")
        ):
            raise ValueError("장부 금액이 유효하지 않아 변경을 차단했습니다.")
        check = rows(db, "finance_invariants", (account,))[0]
        if (
            value["held"] > value["balance"]
            or value["total_deposited"] != value["balance"] + value["total_spent"]
            or value["held"] != check["held"]
            or check["invalid"]
        ):
            raise ValueError("계정 장부가 일치하지 않습니다. 대사 후 처리하세요.")
        return value, bool(found)

    def read(
        self, *, mode="transactions", status="", query="", offset=0, since=0, until=0
    ):
        if mode not in ("transactions", "accounts") or status not in (
            "",
            "held",
            "settled",
            "refunded",
            "withdrawn",
        ):
            raise ValueError("조회 조건을 확인하세요.")
        now = time.time()
        search = (
            "%"
            + query.lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        with transaction(self.store, True) as db:
            summary = rows(db, "finance_summary")[0]
            overdue = rows(db, "finance_overdue", (now - 900,))[0]
            if mode == "accounts":
                found = rows(db, "finance_account_list", (search, 50, offset))
                total = rows(db, "finance_account_count", (search,))[0]["n"]
            else:
                args = (status, status, search, since, until or now)
                found = rows(db, "finance_tx_list", (*args, 50, offset))
                total = rows(db, "finance_tx_count", args)[0]["n"]
        return dict(
            items=[project(row) for row in found],
            total=total,
            limit=50,
            offset=offset,
            captured_at=now,
            summary={
                **{key: str(value) for key, value in summary.items()},
                "overdue_count": overdue["n"],
                "overdue_amount": str(overdue["amount"]),
                "delta": str(
                    summary["deposited"] - summary["balance"] - summary["spent"]
                ),
            },
            mode="virtual_ledger_only",
            external_reserves_verified=False,
        )

    def quote(self, body):
        action = body.get("action")
        if action not in ("deposit", "withdraw", "refund", "sweep") or set(body) - {
            "action",
            "account_id",
            "amount",
            "tx_id",
            "address",
            "reason",
        }:
            raise ValueError("작업 입력을 확인하세요.")
        account = body.get("account_id", "")
        amount, selected = 0, []
        now = time.time()
        with transaction(self.store, True) as db:
            if action == "sweep":
                selected = rows(db, "finance_candidates", (now - 900,))[:20]
                if not selected:
                    raise ValueError("15분 이상 지난 보류 거래가 없습니다.")
                accounts = sorted({row["account_id"] for row in selected})
            else:
                if action == "refund":
                    identity = body.get("tx_id")
                    if type(identity) is not str or len(identity) > 256:
                        raise ValueError("거래를 선택하세요.")
                    selected = rows(db, "finance_tx", (identity,))
                    if not selected or selected[0]["status"] != "held":
                        raise ValueError("현재 보류 중인 거래만 해제할 수 있습니다.")
                    account = selected[0]["account_id"]
                if type(account) is not str or not ACCOUNT.fullmatch(account):
                    raise ValueError("유효한 계정 ID를 입력하세요.")
                accounts = [account]
                if action in ("deposit", "withdraw"):
                    amount = money(body.get("amount"))
                if action == "withdraw" and (
                    type(body.get("address")) is not str
                    or not re.fullmatch(r"0x[0-9a-fA-F]{40}", body["address"])
                    or int(body["address"][2:], 16) == 0
                ):
                    raise ValueError(
                        "기록할 0x 지갑 주소 42자를 입력하세요. 외부 송금은 실행되지 않습니다."
                    )
            snapshots, changes = {}, []
            for acc in accounts:
                current, exists = self._account(db, acc)
                if not exists and action != "deposit":
                    raise ValueError("계정을 찾을 수 없습니다.")
                delta = (
                    amount
                    if action == "deposit"
                    else -amount
                    if action == "withdraw"
                    else 0
                )
                release = sum(
                    row["amount"] for row in selected if row["account_id"] == acc
                )
                if (
                    current["balance"] + delta < current["held"]
                    or current["balance"] + delta > MAX
                    or current["total_deposited"]
                    + (amount if action == "deposit" else 0)
                    > MAX
                    or current["total_spent"] + (amount if action == "withdraw" else 0)
                    > MAX
                ):
                    raise ValueError("사용 가능 잔액 또는 장부 한도를 확인하세요.")
                snapshots[acc] = stamp(current)
                changes.append(
                    dict(
                        account_id=acc,
                        exists=exists,
                        before=project(current),
                        after={
                            "balance": str(current["balance"] + delta),
                            "held": str(current["held"] - release),
                            "available": str(
                                current["balance"] + delta - current["held"] + release
                            ),
                        },
                    )
                )
        return dict(
            version=1,
            request_id="arc_" + uuid.uuid4().hex,
            action=action,
            account_id=account,
            amount=str(amount),
            address=body.get("address", "") if action == "withdraw" else "",
            selected=[
                dict(
                    tx_id=r["tx_id"],
                    account_id=r["account_id"],
                    amount=str(r["amount"]),
                    created_at=r["created_at"],
                )
                for r in selected
            ],
            snapshots=snapshots,
            changes=changes,
            quoted_at=now,
            expires=now + 300,
            reason=body.get("reason", ""),
        )

    def evidence(self, payload):
        reference = "fin_" + payload["request_id"][4:]
        with transaction(self.store, True) as db:
            found = rows(
                db,
                "finance_application_audit",
                (reference, "finance.applied." + payload["action"]),
            )
            accounts = [
                project(row)
                for account in payload["snapshots"]
                for row in rows(db, "finance_account", (account,))
            ]
        return dict(
            reference=reference,
            application_recorded=bool(found),
            applied_at=found[0]["created"] if found else None,
            current_accounts=accounts,
            captured_at=time.time(),
            external_transfer=False,
        )

    def apply(self, payload, user_id):
        if payload.get("version") != 1 or time.time() > payload["expires"]:
            raise ValueError("검토 기한이 지났습니다. 최신 잔액으로 다시 검토하세요.")
        action, amount, now = payload["action"], int(payload["amount"]), time.time()
        receipt = "fin_" + payload["request_id"][4:]
        with transaction(self.store) as db:
            for acc, expected in payload["snapshots"].items():
                current, _ = self._account(db, acc)
                if stamp(current) != expected:
                    raise ValueError(
                        "검토 이후 장부가 변경되었습니다. 최신 상태로 다시 검토하세요."
                    )
            for selected in payload["selected"]:
                found = rows(db, "finance_tx", (selected["tx_id"],))
                if (
                    not found
                    or found[0]["status"] != "held"
                    or any(
                        str(found[0][k]) != str(selected[k])
                        for k in ("account_id", "amount", "created_at")
                    )
                ):
                    raise ValueError("검토한 거래가 변경되어 전체 작업을 중단했습니다.")
            if action == "deposit":
                execute(db, "finance_create", (payload["account_id"], now))
                execute(
                    db, "finance_deposit", (amount, amount, now, payload["account_id"])
                )
            elif action == "withdraw":
                execute(
                    db, "finance_withdraw", (amount, amount, now, payload["account_id"])
                )
                execute(
                    db,
                    "finance_withdraw_tx",
                    (
                        receipt,
                        payload["account_id"],
                        amount,
                        canonical(
                            {
                                "reference": receipt,
                                "address": payload["address"],
                                "external_transfer": False,
                            }
                        ),
                        now,
                        now,
                    ),
                )
            elif action in ("refund", "sweep"):
                for selected in payload["selected"]:
                    amount_selected = int(selected["amount"])
                    execute(
                        db,
                        "finance_release",
                        (amount_selected, now, selected["account_id"]),
                    )
                    if (
                        execute(
                            db,
                            "finance_refund",
                            (
                                canonical(
                                    {"reference": receipt, "reason": payload["reason"]}
                                ),
                                now,
                                selected["tx_id"],
                            ),
                        ).rowcount
                        != 1
                    ):
                        raise ValueError("다른 작업이 거래를 변경했습니다.")
            else:
                raise ValueError("지원하지 않는 작업입니다.")
            audit(db, user_id, "finance.applied." + action, receipt, payload["reason"])
            after = [project(self._account(db, acc)[0]) for acc in payload["snapshots"]]
        return dict(
            reference=receipt,
            action=action,
            external_transfer=False,
            affected=len(payload["selected"]) or 1,
            accounts=after,
        )
