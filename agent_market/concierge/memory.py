"""방문 에이전트 기억: 누가 왔는지, 무슨 얘기를 했는지, 무엇을 찾았는지, 어디로 연락하면 되는지.

식별은 방문 토큰(vt_…)으로 한다. 토큰은 해시로만 저장하고, 지난 대화는 토큰을 가진 쪽에게만 보여 준다.
같은 IP·User-Agent(지문)로 토큰 없이 오면 '혹시 전에 오셨나요?'라고만 묻는다 (같은 IP를 쓰는 다른 에이전트에게 새지 않게).
"""

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field

from ..gateway.store import Store

SESSION_GAP = 30 * 60  # 마지막 활동 후 30분이 지나면 새 방문
MAX_TEXT = 2000
MAX_MESSAGES = 200  # 방문자당 보관하는 대화 수
MAX_INTERESTS = 20
HIT_RETENTION = 90 * 86400


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def fingerprint(ip: str | None, user_agent: str | None) -> str:
    return hashlib.sha256(f"{ip or ''}|{(user_agent or '')[:300]}".encode()).hexdigest()[:32]


def tier_for(visits: int, days: int, messages: int) -> str:
    if days >= 3 or (visits >= 2 and messages >= 10):
        return "regular"
    return "returning" if visits >= 2 else "new"


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


@dataclass
class Visitor:
    id: str
    name: str | None
    tier: str
    visits: int
    visit_days: int
    messages: int
    first_seen: float
    last_seen: float
    lang: str | None
    notify: bool
    token: str | None = None  # 이번 응답에서 새로 발급한 경우에만
    new: bool = False  # 이번에 처음 만든 방문자
    new_visit: bool = False  # 이번 요청이 새 방문(세션)의 시작
    previous_seen: float | None = None  # 이번 방문 전 마지막 활동 시각
    tier_up: str | None = None  # 이번에 올라간 등급
    extra: dict = field(default_factory=dict)


class VisitorBook:
    def __init__(self, store: Store):
        self.store = store

    # ---------------- 식별 ----------------
    def _load(self, row) -> Visitor:
        return Visitor(row["id"], row["name"], row["tier"], row["visits"], row["visit_days"], row["messages"],
                       row["first_seen"], row["last_seen"], row["lang"], bool(row["notify"]))

    def by_token(self, token: str | None) -> Visitor | None:
        if not token or not token.startswith("vt_") or len(token) > 100:
            return None
        rows = self.store.query("SELECT * FROM agent_visitors WHERE token_hash=?", (token_hash(token),))
        return self._load(rows[0]) if rows else None

    def by_context(self, context_id: str | None) -> Visitor | None:
        if not context_id or len(context_id) > 200:
            return None
        rows = self.store.query("""SELECT v.* FROM agent_contexts c JOIN agent_visitors v ON v.id=c.visitor_id
                                   WHERE c.context_id=?""", (context_id,))
        return self._load(rows[0]) if rows else None

    def by_id(self, vid: str) -> Visitor | None:
        rows = self.store.query("SELECT * FROM agent_visitors WHERE id=?", (vid,))
        return self._load(rows[0]) if rows else None

    def seen_fingerprint(self, fp: str, within: float = 30 * 86400) -> bool:
        """토큰 없이 왔지만 같은 IP·User-Agent의 방문자가 최근에 있었는지 (내용은 알려 주지 않음)."""
        return bool(self.store.query("SELECT 1 FROM agent_visitors WHERE fingerprint=? AND last_seen>? LIMIT 1",
                                     (fp, time.time() - within)))

    def create(self, channel: str, user_agent: str | None, fp: str, name: str | None = None, lang: str | None = None) -> Visitor:
        token = "vt_" + secrets.token_urlsafe(24)
        vid = "av_" + secrets.token_hex(6)
        now = time.time()
        with self.store.tx() as db:
            db.execute("""INSERT INTO agent_visitors (id, token_hash, name, channel, user_agent, fingerprint, lang, first_seen, last_seen)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       (vid, token_hash(token), (name or None) and name[:80], channel, (user_agent or "")[:300], fp, lang, now, now))
        v = self.by_id(vid)
        v.token, v.new, v.new_visit = token, True, True
        return v

    def touch(self, v: Visitor, channel: str, user_agent: str | None, fp: str, lang: str | None = None) -> Visitor:
        """활동 기록: 30분 넘게 쉬었다 오면 새 방문, 날짜가 바뀌면 방문한 날 +1, 등급을 다시 계산."""
        now = time.time()
        if v.new:
            return v
        new_visit = now - v.last_seen > SESSION_GAP
        visits = v.visits + (1 if new_visit else 0)
        days = v.visit_days + (1 if _day(now) != _day(v.last_seen) else 0)
        tier = tier_for(visits, days, v.messages)
        with self.store.tx() as db:
            db.execute("""UPDATE agent_visitors SET last_seen=?, visits=?, visit_days=?, tier=?, channel=?, user_agent=?,
                          fingerprint=?, lang=COALESCE(?, lang) WHERE id=?""",
                       (now, visits, days, tier, channel, (user_agent or "")[:300], fp, lang, v.id))
        v.previous_seen, v.last_seen, v.new_visit = v.last_seen, now, new_visit
        if tier != v.tier:
            v.tier_up = tier
        v.visits, v.visit_days, v.tier = visits, days, tier
        return v

    def bind_context(self, v: Visitor, context_id: str | None) -> None:
        if context_id and len(context_id) <= 200:
            with self.store.tx() as db:
                db.execute("INSERT OR IGNORE INTO agent_contexts VALUES (?,?,?)", (context_id, v.id, time.time()))

    def set_name(self, v: Visitor, name: str) -> None:
        name = name.strip()[:80]
        if name:
            with self.store.tx() as db:
                db.execute("UPDATE agent_visitors SET name=? WHERE id=?", (name, v.id))
            v.name = name

    def set_notify(self, vid: str, enabled: bool) -> None:
        with self.store.tx() as db:
            db.execute("UPDATE agent_visitors SET notify=? WHERE id=?", (int(enabled), vid))

    def record_hit(self, fp: str, user_agent: str | None, path: str) -> None:
        """토큰 없는 읽기 방문(GET /, /llms.txt 등)은 지문별로 묶어 셈만 한다."""
        now = time.time()
        with self.store.tx() as db:
            db.execute("""INSERT INTO agent_hits VALUES (?,?,?,?,1,?) ON CONFLICT(fingerprint) DO UPDATE SET
                          hits=hits+1, last_seen=excluded.last_seen, last_path=excluded.last_path""",
                       (fp, (user_agent or "")[:300], now, now, path[:200]))
            if secrets.randbelow(200) == 0:  # 가끔 오래된 익명 기록 정리
                db.execute("DELETE FROM agent_hits WHERE last_seen<?", (now - HIT_RETENTION,))

    # ---------------- 대화 ----------------
    def add_message(self, v: Visitor, role: str, channel: str, text: str, data: dict | None = None) -> None:
        with self.store.tx() as db:
            db.execute("INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
                       (v.id, time.time(), role, channel, (text or "")[:MAX_TEXT],
                        json.dumps(data, ensure_ascii=False)[:8000] if data else None))
            if role == "agent":
                db.execute("UPDATE agent_visitors SET messages=messages+1 WHERE id=?", (v.id,))
                v.messages += 1
                tier = tier_for(v.visits, v.visit_days, v.messages)
                if tier != v.tier:
                    db.execute("UPDATE agent_visitors SET tier=? WHERE id=?", (tier, v.id))
                    v.tier_up, v.tier = tier, tier
            db.execute("""DELETE FROM agent_messages WHERE visitor_id=? AND id NOT IN
                          (SELECT id FROM agent_messages WHERE visitor_id=? ORDER BY id DESC LIMIT ?)""", (v.id, v.id, MAX_MESSAGES))

    def messages(self, vid: str, limit: int = 50) -> list[dict]:
        rows = self.store.query("SELECT * FROM agent_messages WHERE visitor_id=? ORDER BY id DESC LIMIT ?", (vid, limit))
        return [dict(r) for r in reversed(rows)]

    def save_results(self, v: Visitor, results: list[dict], offset: int) -> None:
        """'2번 자세히', '더 보기'를 위해 마지막 추천 목록을 기억한다."""
        with self.store.tx() as db:
            db.execute("UPDATE agent_visitors SET last_results=?, last_offset=? WHERE id=?",
                       (json.dumps(results, ensure_ascii=False), offset, v.id))

    def last_results(self, vid: str) -> tuple[list[dict], int]:
        rows = self.store.query("SELECT last_results, last_offset FROM agent_visitors WHERE id=?", (vid,))
        if not rows or not rows[0]["last_results"]:
            return [], 0
        return json.loads(rows[0]["last_results"]), rows[0]["last_offset"]

    # ---------------- 관심사 ----------------
    def remember_interest(self, v: Visitor, task: str, category: str, kind: str | None, auth_pref: str | None,
                          recommended: list[dict]) -> int:
        norm = " ".join(task.lower().split())[:200]
        now = time.time()
        rec = json.dumps([{k: r.get(k) for k in ("id", "score", "grade", "verified")} for r in recommended])
        best = max((r["score"] for r in recommended), default=None)
        with self.store.tx() as db:
            db.execute("""INSERT INTO agent_interests (visitor_id, task, task_norm, category, kind, auth_pref, created, updated,
                          last_checked, recommended, best_score) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(visitor_id, task_norm) DO UPDATE SET updated=excluded.updated, last_checked=excluded.last_checked,
                          recommended=excluded.recommended, best_score=MAX(COALESCE(best_score,0), COALESCE(excluded.best_score,0)),
                          kind=excluded.kind, auth_pref=excluded.auth_pref, active=1""",
                       (v.id, task[:300], norm, category, kind, auth_pref, now, now, now, rec, best))
            row = db.execute("SELECT id FROM agent_interests WHERE visitor_id=? AND task_norm=?", (v.id, norm)).fetchone()
            db.execute("""UPDATE agent_interests SET active=0 WHERE visitor_id=? AND id NOT IN
                          (SELECT id FROM agent_interests WHERE visitor_id=? ORDER BY updated DESC LIMIT ?)""", (v.id, v.id, MAX_INTERESTS))
        return row["id"]

    def interests(self, vid: str, active_only: bool = True) -> list[dict]:
        rows = self.store.query(f"SELECT * FROM agent_interests WHERE visitor_id=? {'AND active=1' if active_only else ''} ORDER BY updated DESC",
                                (vid,))
        out = []
        for r in rows:
            d = dict(r)
            d["recommended"] = json.loads(d["recommended"] or "[]")
            out.append(d)
        return out

    def update_recommended(self, interest_id: int, recommended: list[dict]) -> None:
        rec = json.dumps([{k: r.get(k) for k in ("id", "score", "grade", "verified")} for r in recommended])
        best = max((r["score"] for r in recommended), default=None)
        with self.store.tx() as db:
            db.execute("""UPDATE agent_interests SET recommended=?, last_checked=?, best_score=MAX(COALESCE(best_score,0), COALESCE(?,0))
                          WHERE id=?""", (rec, time.time(), best, interest_id))

    def record_outcome(self, v: Visitor, resource_id: int, success: bool) -> None:
        with self.store.tx() as db:
            db.execute("INSERT OR REPLACE INTO agent_outcomes VALUES (?,?,?,?)", (v.id, resource_id, int(success), time.time()))

    def failed_resources(self, vid: str) -> set[int]:
        return {r["resource_id"] for r in self.store.query(
            "SELECT resource_id FROM agent_outcomes WHERE visitor_id=? AND success=0", (vid,))}

    # ---------------- 연락처·알림 ----------------
    def contacts(self, vid: str) -> list[dict]:
        return [dict(r) for r in self.store.query("SELECT * FROM agent_contacts WHERE visitor_id=? ORDER BY id DESC", (vid,))]

    def active_contact(self, vid: str) -> dict | None:
        rows = self.store.query("SELECT * FROM agent_contacts WHERE visitor_id=? AND status='verified' ORDER BY id DESC LIMIT 1", (vid,))
        return dict(rows[0]) if rows else None

    def log_notification(self, vid: str, contact_id: int | None, kind: str, status: str, detail: str, items=None) -> None:
        with self.store.tx() as db:
            db.execute("INSERT INTO agent_notifications (visitor_id, contact_id, at, kind, status, detail, items) VALUES (?,?,?,?,?,?,?)",
                       (vid, contact_id, time.time(), kind, status, detail[:500], json.dumps(items, ensure_ascii=False) if items else None))
            if kind == "digest" and status == "sent":
                db.execute("UPDATE agent_visitors SET last_notified=? WHERE id=?", (time.time(), vid))

    def notifications(self, vid: str, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.store.query(
            "SELECT * FROM agent_notifications WHERE visitor_id=? ORDER BY at DESC LIMIT ?", (vid, limit))]
