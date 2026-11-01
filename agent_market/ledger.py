"""결제 장부. 같은 결제 트랜잭션이 두 번 쓰이지 않도록 막고 수익을 기록한다."""

import sqlite3
import threading
import time
from contextlib import contextmanager

from .storage_security import private_sqlite_file


class Ledger:
    def __init__(self, path: str = ":memory:", *, store=None):
        self._store = store
        if store is None:
            private_sqlite_file(path)
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._lock = threading.Lock()
        else:
            from .gateway.store import Store
            from .application_store_postgres import PostgresApplicationStore
            if type(store) not in (Store, PostgresApplicationStore):
                raise ValueError('explicit_application_store_required')
            self._db, self._lock = store._db, store._lock
        with self._transaction():
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS payments (
                    tx_hash TEXT PRIMARY KEY,
                    payer TEXT NOT NULL,
                    service TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT NOT NULL,          -- pending | settled
                    created_at REAL NOT NULL
                )"""
            )

    @contextmanager
    def _transaction(self, *, readonly=False):
        if self._store is not None:
            transaction = (self._store.tx(readonly=readonly)
                if getattr(self._store, 'backend', 'sqlite') == 'postgresql' else self._store.tx())
            with transaction as db:
                yield db
        elif readonly:
            with self._lock:
                yield self._db
        else:
            with self._lock, self._db:
                yield self._db

    def close(self):
        """Detach only an owned connection; shared application storage is retained."""
        if self._store is None:
            with self._lock:
                self._db.close()

    def claim(self, tx_hash: str, payer: str, service: str, amount: int) -> bool:
        """결제를 선점한다. 이미 쓰였거나 처리 중이면 False."""
        with self._transaction():
            changed = self._db.execute(
                "INSERT INTO payments VALUES (?, ?, ?, ?, 'pending', ?) ON CONFLICT(tx_hash) DO NOTHING",
                (tx_hash.lower(), payer, service, amount, time.time()),
            )
            return changed.rowcount == 1

    def settle(self, tx_hash: str) -> None:
        with self._transaction():
            self._db.execute("UPDATE payments SET status='settled' WHERE tx_hash=?", (tx_hash.lower(),))

    def release(self, tx_hash: str) -> None:
        """서비스 실행이 실패하면 선점을 풀어 구매자가 같은 결제로 재시도할 수 있게 한다."""
        with self._transaction():
            self._db.execute("DELETE FROM payments WHERE tx_hash=? AND status='pending'", (tx_hash.lower(),))

    def sweep_orphaned_pending(self, ttl_seconds: float = 900) -> int:
        """Sweeps abandoned pending claims older than TTL to prevent permanent locks."""
        cutoff = time.time() - ttl_seconds
        with self._transaction():
            cursor = self._db.execute("DELETE FROM payments WHERE status='pending' AND created_at < ?", (cutoff,))
            return cursor.rowcount

    def get_payment(self, tx_hash: str) -> dict | None:
        with self._transaction(readonly=True):
            row = self._db.execute(
                "SELECT tx_hash, payer, service, amount, status, created_at FROM payments WHERE tx_hash=?",
                (tx_hash.lower(),)
            ).fetchone()
            if not row:
                return None
            return {
                "tx_hash": row[0],
                "payer": row[1],
                "service": row[2],
                "amount": row[3],
                "status": row[4],
                "created_at": row[5],
            }

    def list_payments(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        service: str | None = None,
    ) -> tuple[list[dict], int]:
        pattern = f"%{service}%" if service else None
        values = (status or None, status or None, pattern, pattern)
        with self._transaction(readonly=True):
            total = self._db.execute(
                "SELECT COUNT(*) FROM payments WHERE (? IS NULL OR status=?) AND (? IS NULL OR service LIKE ?)",
                values).fetchone()[0]
            rows = self._db.execute(
                "SELECT tx_hash, payer, service, amount, status, created_at FROM payments WHERE (? IS NULL OR status=?) AND (? IS NULL OR service LIKE ?) ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*values, limit, offset)).fetchall()

        items = [
            {
                "tx_hash": r[0],
                "payer": r[1],
                "service": r[2],
                "amount": r[3],
                "status": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
        return items, total

    def stats(self) -> dict:
        with self._transaction(readonly=True):
            rows = self._db.execute(
                "SELECT service, COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status='settled' GROUP BY service"
            ).fetchall()
            pending_count = self._db.execute(
                "SELECT COUNT(*) FROM payments WHERE status='pending'"
            ).fetchone()[0]
        by_service = {s: {"calls": n, "revenue": amt} for s, n, amt in rows}
        return {
            "total_revenue": sum(v["revenue"] for v in by_service.values()),
            "total_settled_tx": sum(v["calls"] for v in by_service.values()),
            "pending_tx": pending_count,
            "by_service": by_service,
        }
