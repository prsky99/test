"""Financial mutations only in an isolated PostgreSQL 18 cluster, never production."""

from pathlib import Path
import time

import psycopg
import pytest

from agent_market.admin_finance_workbench import FinanceWorkbench
from agent_market.storage_adapter import open_store
from agent_market.workspace_admin_events import migrate
from scripts.rehearse_storage_adapter_postgres import (
    _private_cluster,
    PORT,
    RehearsalError,
)


def test_financial_workbench_on_postgresql18():
    tools = {
        name: "/opt/homebrew/opt/postgresql@18/bin/" + name
        for name in ("initdb", "pg_ctl")
    }
    if not all(Path(p).exists() for p in tools.values()):
        pytest.skip("PostgreSQL 18 test tools unavailable")
    cluster = _private_cluster(tools)
    try:
        ready = cluster.__enter__()
    except RehearsalError:
        pytest.skip(
            "Isolated PostgreSQL cluster unavailable; no production mutations attempted"
        )
    try:
        connection = psycopg.connect(
            host=ready["socket"],
            port=PORT,
            dbname="postgres",
            user="postgres",
            autocommit=True,
        )
        store = open_store(
            "postgresql", connection=connection, initialize=True, workflow_key=b"p" * 32
        )
        try:
            migrate(store, b"finance-isolated-postgres-test-key")
            store.deposit_credit("qa-native-finance", 20_000_000)
            held = store.hold_credit("qa-native-finance", 3_000_000, 0, "qa-native")
            with store.tx():
                store._execute(
                    "UPDATE clearing_ledger SET created_at=%s WHERE tx_id=%s",
                    (time.time() - 3600, held),
                )
            work = FinanceWorkbench(store)
            data = work.read(status="held", query="qa-native")
            assert data["total"] == 1 and data["summary"]["held"] == "3000000"
            quote = work.quote(
                {
                    "action": "deposit",
                    "account_id": "qa-native-finance",
                    "amount": "1.000001",
                    "reason": "isolated native verification",
                }
            )
            work.apply(quote, 1)
            assert store.get_credit("qa-native-finance")["balance"] == 21_000_001
            with pytest.raises(ValueError, match="변경"):
                work.apply(quote, 1)
            quote = work.quote({"action": "sweep", "reason": "isolated native sweep"})
            work.apply(quote, 1)
            assert store.get_credit("qa-native-finance")["held"] == 0
            quote = work.quote(
                {
                    "action": "withdraw",
                    "account_id": "qa-native-finance",
                    "amount": "1",
                    "address": "0x" + "1" * 40,
                    "reason": "isolated native recall",
                }
            )
            result = work.apply(quote, 1)
            assert (
                result["external_transfer"] is False
                and store.get_credit("qa-native-finance")["balance"] == 20_000_001
            )
            assert work.read(mode="accounts", query="qa_native")["total"] == 0
        finally:
            store.close()
    finally:
        cluster.__exit__(None, None, None)
