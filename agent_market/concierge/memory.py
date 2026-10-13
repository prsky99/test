"""Visitor memory: who came, what was said, what they looked for, and where to reach them.

Visitors are identified by a visitor token (vt_...). Tokens are stored only as hashes, and past conversations are
shown only to the token holder. A visitor that comes back without a token from the same IP and User-Agent
(fingerprint) is only asked "have we talked before?", so nothing leaks to another agent behind the same IP.
"""

import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass, field

from ..gateway.store import Store

SESSION_GAP = 30 * 60  # 30 minutes after the last activity, the next request starts a new visit
MAX_TEXT = 2000
MAX_MESSAGES = 200  # messages kept per visitor
MAX_INTERESTS = 20
HIT_RETENTION = 90 * 86400
MAX_HITS = 100_000  # anonymous read records kept at most (oldest dropped first)
IDLE_VISITOR_RETENTION = 30 * 86400  # visitors with almost no conversation are dropped after 30 idle days
ISSUED_CONTEXT = re.compile(r"^ctx_[0-9a-f]{32}$")  # context IDs we issue: random, unguessable


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
    token: str | None = None  # set only when issued in this response
    new: bool = False  # visitor created by this request
    new_visit: bool = False  # this request starts a new visit (session)
    previous_seen: float | None = None  # last activity before this visit
    tier_up: str | None = None  # tier reached by this request
    extra: dict = field(default_factory=dict)


class VisitorBook:
    def __init__(self, store: Store):
        self.store = store

    # ---------------- identification ----------------
    def _load(self, row) -> Visitor:
        return Visitor(row["id"], row["name"], row["tier"], row["visits"], row["visit_days"], row["messages"],
                       row["first_seen"], row["last_seen"], row["lang"], bool(row["notify"]))

    def by_token(self, token: str | None) -> Visitor | None:
        if not token or not token.startswith("vt_") or len(token) > 100:
            return None
        rows = self.store.query("SELECT * FROM agent_visitors WHERE token_hash=?", (token_hash(token),))
        return self._load(rows[0]) if rows else None

    def by_context(self, context_id: str | None, fp: str) -> Visitor | None:
        """Visitor bound to an A2A contextId. A context we issued (random, unguessable) identifies its visitor on its own.
        A context the client chose (e.g. "session-1") could be guessed by another agent, so it only counts when it
        comes from the same fingerprint (IP + User-Agent) that first used it; otherwise the visitor token is needed."""
        if not context_id or len(context_id) > 200:
            return None
        rows = self.store.query("""SELECT v.*, c.fingerprint AS ctx_fp, c.issued AS ctx_issued FROM agent_contexts c
                                   JOIN agent_visitors v ON v.id=c.visitor_id WHERE c.context_id=?""", (context_id,))
        if not rows:
            return None
        row = rows[0]
        if row["ctx_issued"] and ISSUED_CONTEXT.match(context_id):
            return self._load(row)
        return self._load(row) if row["ctx_fp"] and row["ctx_fp"] == fp else None

    @staticmethod
    def new_context_id() -> str:
        return "ctx_" + secrets.token_hex(16)

    def by_id(self, vid: str) -> Visitor | None:
        rows = self.store.query("SELECT * FROM agent_visitors WHERE id=?", (vid,))
        return self._load(rows[0]) if rows else None

    def seen_fingerprint(self, fp: str, within: float = 30 * 86400) -> bool:
        """Whether a visitor with the same IP and User-Agent came recently (contents are never revealed)."""
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
        if secrets.randbelow(100) == 0:
            self.prune()
        v = self.by_id(vid)
        v.token, v.new, v.new_visit = token, True, True
        return v

    def prune(self) -> int:
        """Drop visitors that barely talked and have been idle for a while (keeps the table from being filled by drive-bys)."""
        cutoff = time.time() - IDLE_VISITOR_RETENTION
        with self.store.tx() as db:
            ids = [r[0] for r in db.execute(
                "SELECT id FROM agent_visitors WHERE messages <= 2 AND last_seen < ? AND id NOT IN (SELECT visitor_id FROM agent_contacts)",
                (cutoff,))]
            for table in ("agent_messages", "agent_interests", "agent_contexts", "agent_outcomes"):
                db.executemany(f"DELETE FROM {table} WHERE visitor_id=?", [(i,) for i in ids])
            db.executemany("DELETE FROM agent_visitors WHERE id=?", [(i,) for i in ids])
        return len(ids)

    def touch(self, v: Visitor, channel: str, user_agent: str | None, fp: str, lang: str | None = None) -> Visitor:
        """Record activity: a new visit after 30 idle minutes, one more visit day when the date changes, tier recomputed."""
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

    def bind_context(self, v: Visitor, context_id: str | None, fp: str, issued: bool = False) -> None:
        """Remember which visitor a contextId belongs to (first use wins; a context is never moved to another visitor)."""
        if context_id and len(context_id) <= 200:
            with self.store.tx() as db:
                db.execute("INSERT OR IGNORE INTO agent_contexts (context_id, visitor_id, created, fingerprint, issued) VALUES (?,?,?,?,?)",
                           (context_id, v.id, time.time(), fp, int(issued)))

    def set_name(self, v: Visitor, name: str) -> None:
        name = re.sub(r"\s+", " ", "".join(ch for ch in name if ch.isprintable())).strip()[:80]  # no control/invisible characters
        if name:
            with self.store.tx() as db:
                db.execute("UPDATE agent_visitors SET name=? WHERE id=?", (name, v.id))
            v.name = name

    def set_notify(self, vid: str, enabled: bool) -> None:
        with self.store.tx() as db:
            db.execute("UPDATE agent_visitors SET notify=? WHERE id=?", (int(enabled), vid))

    def record_hit(self, fp: str, user_agent: str | None, path: str) -> None:
        """Read-only visits without a token (GET /, /llms.txt, ...) are only counted per fingerprint."""
        now = time.time()
        with self.store.tx() as db:
            db.execute("""INSERT INTO agent_hits VALUES (?,?,?,?,1,?) ON CONFLICT(fingerprint) DO UPDATE SET
                          hits=hits+1, last_seen=excluded.last_seen, last_path=excluded.last_path""",
                       (fp, (user_agent or "")[:300], now, now, path[:200]))
            if secrets.randbelow(200) == 0:  # occasionally prune old anonymous records and cap the table
                db.execute("DELETE FROM agent_hits WHERE last_seen<?", (now - HIT_RETENTION,))
                db.execute("""DELETE FROM agent_hits WHERE fingerprint IN (SELECT fingerprint FROM agent_hits ORDER BY last_seen DESC
                              LIMIT -1 OFFSET ?)""", (MAX_HITS,))

    # ---------------- conversation ----------------
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
        """Remember the last recommendation list for "details 2" and "more"."""
        with self.store.tx() as db:
            db.execute("UPDATE agent_visitors SET last_results=?, last_offset=? WHERE id=?",
                       (json.dumps(results, ensure_ascii=False), offset, v.id))

    def last_results(self, vid: str) -> tuple[list[dict], int]:
        rows = self.store.query("SELECT last_results, last_offset FROM agent_visitors WHERE id=?", (vid,))
        if not rows or not rows[0]["last_results"]:
            return [], 0
        return json.loads(rows[0]["last_results"]), rows[0]["last_offset"]

    # ---------------- interests ----------------
    def remember_interest(self, v: Visitor, task: str, category: str, kind: str | None, auth_pref: str | None,
                          recommended: list[dict], hint: str | None = None) -> int:
        norm = " ".join(task.lower().split())[:200]
        now = time.time()
        rec = json.dumps([{k: r.get(k) for k in ("id", "score", "grade", "verified")} for r in recommended])
        best = max((r["score"] for r in recommended), default=None)
        with self.store.tx() as db:
            db.execute("""INSERT INTO agent_interests (visitor_id, task, task_norm, category, kind, auth_pref, created, updated,
                          last_checked, recommended, best_score, hint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(visitor_id, task_norm) DO UPDATE SET updated=excluded.updated, last_checked=excluded.last_checked,
                          recommended=excluded.recommended, best_score=MAX(COALESCE(best_score,0), COALESCE(excluded.best_score,0)),
                          kind=excluded.kind, auth_pref=excluded.auth_pref, hint=COALESCE(excluded.hint, hint), active=1""",
                       (v.id, task[:300], norm, category, kind, auth_pref, now, now, now, rec, best, (hint or None) and hint[:120]))
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

    # ---------------- contacts and notifications ----------------
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
