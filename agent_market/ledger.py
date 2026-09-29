"""결제 장부. 같은 결제 트랜잭션이 두 번 쓰이지 않도록 막고 수익을 기록한다."""

import sqlite3
import threading
import time


class Ledger:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._db:
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

    def claim(self, tx_hash: str, payer: str, service: str, amount: int) -> bool:
        """결제를 선점한다. 이미 쓰였거나 처리 중이면 False."""
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO payments VALUES (?, ?, ?, ?, 'pending', ?)",
                    (tx_hash.lower(), payer, service, amount, time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def settle(self, tx_hash: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE payments SET status='settled' WHERE tx_hash=?", (tx_hash.lower(),))

    def release(self, tx_hash: str) -> None:
        """서비스 실행이 실패하면 선점을 풀어 구매자가 같은 결제로 재시도할 수 있게 한다."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM payments WHERE tx_hash=? AND status='pending'", (tx_hash.lower(),))

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT service, COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status='settled' GROUP BY service"
            ).fetchall()
        by_service = {s: {"calls": n, "revenue": amt} for s, n, amt in rows}
        return {"total_revenue": sum(v["revenue"] for v in by_service.values()), "by_service": by_service}
