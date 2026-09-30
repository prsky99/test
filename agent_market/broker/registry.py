"""등록된 에이전트, 견적, 매칭, 평판을 저장하는 SQLite 저장소."""

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass


@dataclass
class Listing:
    agent_id: str
    agent_name: str
    agent_url: str
    pay_to: str
    service: str
    category: str
    description: str
    price: int
    endpoint: str
    rating: float  # 베이지안 평균 (1~5)
    ratings: int  # 별점 수
    success_rate: float

    def preview(self) -> dict:
        """수수료 결제 전 공개 정보. 연락처(URL/지갑)는 숨긴다."""
        return {
            "service": self.service,
            "description": self.description,
            "price": self.price,
            "rating": round(self.rating, 2),
            "ratings": self.ratings,
            "success_rate": round(self.success_rate, 3),
        }

    def full(self) -> dict:
        return {
            **self.preview(),
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_url": self.agent_url,
            "endpoint": self.endpoint,
            "pay_to": self.pay_to,
        }


PRIOR_RATING, PRIOR_WEIGHT = 3.5, 3  # 평가가 적은 신규 에이전트가 과대/과소평가되지 않게


class Registry:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY, url TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    pay_to TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS services (
                    agent_id TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
                    description TEXT NOT NULL, price INTEGER NOT NULL, endpoint TEXT NOT NULL,
                    PRIMARY KEY (agent_id, name)
                );
                CREATE TABLE IF NOT EXISTS quotes (
                    quote_id TEXT PRIMARY KEY, category TEXT NOT NULL, task_summary TEXT NOT NULL,
                    candidates TEXT NOT NULL, fee INTEGER NOT NULL, created_at REAL NOT NULL,
                    payer TEXT, tx_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    quote_id TEXT NOT NULL, agent_id TEXT NOT NULL, service TEXT NOT NULL,
                    success INTEGER NOT NULL, rating INTEGER, created_at REAL NOT NULL,
                    PRIMARY KEY (quote_id, agent_id, service)
                );
                """
            )

    # --- 에이전트 등록 ---
    def upsert_agent(self, url: str, name: str, pay_to: str, services: list[dict]) -> str:
        with self._lock, self._db:
            row = self._db.execute("SELECT agent_id FROM agents WHERE url=?", (url,)).fetchone()
            agent_id = row[0] if row else "agt_" + secrets.token_hex(8)
            self._db.execute(
                "INSERT OR REPLACE INTO agents VALUES (?, ?, ?, ?, 1, ?)", (agent_id, url, name, pay_to.lower(), time.time())
            )
            self._db.execute("DELETE FROM services WHERE agent_id=?", (agent_id,))
            self._db.executemany(
                "INSERT INTO services VALUES (?, ?, ?, ?, ?, ?)",
                [(agent_id, s["name"], s["category"], s["description"], s["price"], s["endpoint"]) for s in services],
            )
        return agent_id

    def deactivate(self, agent_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE agents SET active=0 WHERE agent_id=?", (agent_id,))

    # --- 검색 ---
    def find(self, category: str, max_price: int | None, limit: int) -> list[Listing]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT a.agent_id, a.name, a.url, a.pay_to, s.name, s.category, s.description, s.price, s.endpoint,
                       COALESCE(SUM(f.rating), 0), COUNT(f.rating), COALESCE(SUM(f.success), 0), COUNT(f.quote_id)
                FROM services s JOIN agents a ON a.agent_id = s.agent_id
                LEFT JOIN feedback f ON f.agent_id = s.agent_id AND f.service = s.name
                WHERE a.active = 1 AND s.category = ? AND (? IS NULL OR s.price <= ?)
                GROUP BY s.agent_id, s.name
                """,
                (category, max_price, max_price),
            ).fetchall()
        listings = []
        for aid, aname, url, pay_to, svc, cat, desc, price, endpoint, rating_sum, n, successes, jobs in rows:
            listings.append(
                Listing(
                    aid, aname, url, pay_to, svc, cat, desc, price, endpoint,
                    rating=(rating_sum + PRIOR_RATING * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT),
                    ratings=n,
                    success_rate=(successes + 1) / (jobs + 2),  # 라플라스 보정
                )
            )
        if not listings:
            return []
        cheapest = min(l.price for l in listings) or 1
        # 평판(품질·성공률)을 우선하고 가격은 보조 요소로 반영한다.
        listings.sort(key=lambda l: (l.rating / 5) * 0.5 + l.success_rate * 0.35 + (cheapest / max(l.price, 1)) * 0.15, reverse=True)
        return listings[:limit]

    # --- 견적 / 매칭 ---
    def create_quote(self, category: str, task_summary: str, candidates: list[Listing], fee: int) -> str:
        quote_id = "qt_" + secrets.token_hex(12)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                (quote_id, category, task_summary, json.dumps([c.full() for c in candidates]), fee, time.time()),
            )
        return quote_id

    def get_quote(self, quote_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT quote_id, category, task_summary, candidates, fee, created_at, payer, tx_hash FROM quotes WHERE quote_id=?",
                (quote_id,),
            ).fetchone()
        if row is None:
            return None
        keys = ["quote_id", "category", "task_summary", "candidates", "fee", "created_at", "payer", "tx_hash"]
        quote = dict(zip(keys, row))
        quote["candidates"] = json.loads(quote["candidates"])
        return quote

    def mark_paid(self, quote_id: str, payer: str, tx_hash: str) -> bool:
        """견적 1건에 결제 1건. 이미 결제된 견적이면 False."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE quotes SET payer=?, tx_hash=? WHERE quote_id=? AND payer IS NULL", (payer, tx_hash, quote_id)
            )
            return cur.rowcount == 1

    # --- 평판 ---
    def add_feedback(self, quote_id: str, agent_id: str, service: str, success: bool, rating: int | None) -> bool:
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
                    (quote_id, agent_id, service, int(success), rating, time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def stats(self) -> dict:
        with self._lock:
            agents = self._db.execute("SELECT COUNT(*) FROM agents WHERE active=1").fetchone()[0]
            by_cat = self._db.execute(
                "SELECT category, COUNT(*), COUNT(payer), COALESCE(SUM(CASE WHEN payer IS NOT NULL THEN fee END), 0) FROM quotes GROUP BY category"
            ).fetchall()
        return {
            "active_agents": agents,
            "fee_revenue": sum(r[3] for r in by_cat),
            "by_category": {c: {"quotes": q, "paid_matches": p, "fee_revenue": f} for c, q, p, f in by_cat},
        }
