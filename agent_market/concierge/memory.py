"""Visitor memory: who came, what was said, what they looked for, and where to reach them.

Visitors are identified by a visitor token (vt_...). Tokens are stored only as hashes, and past conversations are
shown only to the token holder. A visitor that comes back without a token from the same IP and User-Agent
(fingerprint) is only asked "have we talked before?", so nothing leaks to another agent behind the same IP.
"""

import hashlib
import json
import logging
import math
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from contextlib import ExitStack, contextmanager

from ..gateway.store import Store
from .token_hygiene import redact_visitor_tokens

SESSION_GAP = 30 * 60  # 30 minutes after the last activity, the next request starts a new visit
MAX_TEXT = 2000
MAX_MESSAGES = 200  # messages kept per visitor
MESSAGE_RETENTION_DAYS = 90
MESSAGE_RETENTION = MESSAGE_RETENTION_DAYS * 86400
MAX_INTERESTS = 20
HIT_RETENTION = 90 * 86400
MAX_HITS = 100_000  # anonymous read records kept at most (oldest dropped first)
HIT_QUEUE_SIZE = 2000
HIT_BATCH_SIZE = 50
HIT_WORKER_IDLE_SECONDS = 1.0
IDLE_VISITOR_RETENTION = 30 * 86400  # visitors with almost no conversation are dropped after 30 idle days
ISSUED_CONTEXT = re.compile(r"^ctx_[0-9a-f]{32}$")  # context IDs we issue: random, unguessable
HIT_FINGERPRINT = re.compile(r"^[0-9a-f]{32}$")
log = logging.getLogger(__name__)



# Every write waits for the catalog writer lock for at most a second. Another service holding
# it longer made a Chat answer fail after its recommendations were ready (2026-11-01 18:51 503).
# A lock not granted means nothing was written, so the same transaction is requested again.
WRITER_RETRY_PAUSES = (0.2, 0.5)


def _writer_busy(error):
    try:
        from ..application_store_postgres import WriterBusy
    except ImportError:
        return False
    return isinstance(error, WriterBusy)


@contextmanager
def _write(store):
    """store.tx(), requested again up to twice when the writer lock was busy."""
    for pause in WRITER_RETRY_PAUSES + (None,):
        stack = ExitStack()
        try:
            db = stack.enter_context(store.tx())
        except Exception as error:
            if pause is None or not _writer_busy(error):
                raise
            time.sleep(pause)
            continue
        break
    with stack:
        yield db

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
    nurture_stage: str = "onboarded"
    last_nurture_at: float | None = None
    extra: dict = field(default_factory=dict)


class VisitorBook:
    def __init__(self, store: Store):
        self.store = store
        self._hit_queue: queue.Queue = queue.Queue(maxsize=HIT_QUEUE_SIZE)
        self._hit_condition = threading.Condition()
        self._hit_worker = None
        self._hit_closed = False
        self._hit_last_at = 0.0
        self._hit_last_warning = float('-inf')
        self._hit_counts = dict(accepted=0, persisted=0, unconfirmed=0,
                               rejected_full=0, rejected_closed=0, rejected_invalid=0,
                               rejected_start=0)

    # ---------------- identification ----------------
    def _load(self, row) -> Visitor:
        keys = row.keys() if hasattr(row, "keys") else ()
        nurture_stage = row["nurture_stage"] if "nurture_stage" in keys and row["nurture_stage"] else "onboarded"
        last_nurture_at = row["last_nurture_at"] if "last_nurture_at" in keys else None
        return Visitor(row["id"], row["name"], row["tier"], row["visits"], row["visit_days"], row["messages"],
                       row["first_seen"], row["last_seen"], row["lang"], bool(row["notify"]),
                       nurture_stage=nurture_stage, last_nurture_at=last_nurture_at)

    def by_token(self, token: str | None) -> Visitor | None:
        if not token or not token.startswith("vt_") or len(token) > 100:
            return None
        rows = self.store.query("SELECT * FROM agent_visitors WHERE token_hash=?", (token_hash(token),))
        return self._load(rows[0]) if rows else None

    def by_context(self, context_id: str | None, fp: str) -> Visitor | None:
        """Visitor bound to an A2A contextId. A context we issued (random, unguessable) identifies its visitor on its own.
        A context the client chose (e.g. "session-1") could be guessed by another agent, so it only counts when it
        comes from the same fingerprint (IP + User-Agent) that first used it; otherwise the visitor token is needed."""
        return self.context_state(context_id, fp)[0]

    def context_state(self, context_id: str | None, fp: str):
        """Resolve a context and retain its owner for collision rejection."""
        if not context_id or len(context_id) > 200:
            return None, None
        rows = self.store.query("""SELECT v.*, c.fingerprint AS ctx_fp, c.issued AS ctx_issued FROM agent_contexts c
                                   JOIN agent_visitors v ON v.id=c.visitor_id WHERE c.context_id=?""", (context_id,))
        if not rows:
            return None, None
        row = rows[0]
        if row["ctx_issued"] and ISSUED_CONTEXT.match(context_id):
            return self._load(row), row['id']
        return (self._load(row) if row["ctx_fp"] and row["ctx_fp"] == fp else None), row['id']

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
        with _write(self.store) as db:
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
        with _write(self.store) as db:
            ids = [r[0] for r in db.execute(
                "SELECT id FROM agent_visitors WHERE messages <= 2 AND last_seen < ? AND id NOT IN (SELECT visitor_id FROM agent_contacts) AND id NOT IN (SELECT visitor_id FROM agent_task_watches WHERE state IN ('active','paused','pending_verification')) AND id NOT IN (SELECT visitor_id FROM agent_visitor_cases WHERE status NOT IN ('resolved','archived'))",
                (cutoff,))]
            for table in ("agent_messages", "agent_interests", "agent_contexts", "agent_outcomes", "agent_visitor_cases", "agent_visitor_case_notes"):
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
        with _write(self.store) as db:
            if now-v.last_seen>MESSAGE_RETENTION:
                db.execute("UPDATE agent_visitors SET last_results=NULL,last_offset=0,last_tool_resource=NULL,last_tool_name=NULL WHERE id=?",(v.id,))
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
            with _write(self.store) as db:
                db.execute("INSERT OR IGNORE INTO agent_contexts (context_id, visitor_id, created, fingerprint, issued) VALUES (?,?,?,?,?)",
                           (context_id, v.id, time.time(), fp, int(issued)))

    def set_name(self, v: Visitor, name: str) -> None:
        name = re.sub(r"\s+", " ", "".join(ch for ch in name if ch.isprintable())).strip()[:80]  # no control/invisible characters
        if name:
            with _write(self.store) as db:
                db.execute("UPDATE agent_visitors SET name=? WHERE id=?", (name, v.id))
            v.name = name

    def set_notify(self, vid: str, enabled: bool) -> None:
        with _write(self.store) as db:
            db.execute("UPDATE agent_visitors SET notify=? WHERE id=?", (int(enabled), vid))

    def update_nurture(self, vid: str, stage: str, at: float | None = None) -> None:
        now = at or time.time()
        with _write(self.store) as db:
            db.execute("UPDATE agent_visitors SET nurture_stage=?, last_nurture_at=? WHERE id=?", (stage, now, vid))

    def _ensure_hit_worker(self) -> bool:
        # Admission and startup share this condition, including during shutdown.
        if self._hit_worker is None:
            worker = threading.Thread(target=self._drain_hits, daemon=True, name="visitor-hit-worker")
            try:
                worker.start()
            except RuntimeError:
                return False
            self._hit_worker = worker
        return True

    def _write_hit_batch(self, batch) -> None:
        # Both supported stores acquire their own transaction lock here. Never
        # pass a request-owned transaction or cursor across the thread boundary.
        with _write(self.store) as db:
            for fp, ua, path, at in batch:
                db.execute("""INSERT INTO agent_hits VALUES (?,?,?,?,1,?) ON CONFLICT(fingerprint) DO UPDATE SET
                              hits=agent_hits.hits+1,
                              first_seen=CASE WHEN excluded.first_seen<agent_hits.first_seen THEN excluded.first_seen ELSE agent_hits.first_seen END,
                              last_seen=CASE WHEN excluded.last_seen>=agent_hits.last_seen THEN excluded.last_seen ELSE agent_hits.last_seen END,
                              last_path=CASE WHEN excluded.last_seen>=agent_hits.last_seen THEN excluded.last_path ELSE agent_hits.last_path END""",
                           (fp, ua, at, at, path))
            db.execute("DELETE FROM agent_hits WHERE last_seen<?", (time.time() - HIT_RETENTION,))
            db.execute("""DELETE FROM agent_hits WHERE fingerprint IN (SELECT fingerprint FROM agent_hits ORDER BY last_seen DESC
                          LIMIT -1 OFFSET ?)""", (MAX_HITS,))

    def _drain_hits(self) -> None:
        last_batch = time.monotonic()
        try:
            while True:
                with self._hit_condition:
                    if self._hit_closed and self._hit_queue.empty():
                        return
                try:
                    item = self._hit_queue.get(timeout=0.1)
                except queue.Empty:
                    with self._hit_condition:
                        if self._hit_queue.empty() and time.monotonic() - last_batch >= HIT_WORKER_IDLE_SECONDS:
                            # Release idle books even when a legacy caller does
                            # not enter an application lifespan. Admission may
                            # safely start a fresh worker after this point.
                            self._hit_worker = None
                            return
                    continue
                batch = [item]
                while len(batch) < HIT_BATCH_SIZE:
                    try:
                        batch.append(self._hit_queue.get_nowait())
                    except queue.Empty:
                        break
                confirmed = False
                try:
                    self._write_hit_batch(batch)
                    confirmed = True
                except Exception:
                    # A failed commit acknowledgement may still mean a commit.
                    # Replay could double-count visits, so report uncertainty.
                    now = time.monotonic()
                    if now - self._hit_last_warning >= 60:
                        log.warning("Anonymous visit batch write unconfirmed (%d records); no retry attempted", len(batch))
                        self._hit_last_warning = now
                for _ in batch:
                    self._hit_queue.task_done()
                with self._hit_condition:
                    self._hit_counts['persisted' if confirmed else 'unconfirmed'] += len(batch)
                    self._hit_condition.notify_all()
                last_batch = time.monotonic()
        finally:
            with self._hit_condition:
                if self._hit_worker is threading.current_thread():
                    self._hit_worker = None
                self._hit_condition.notify_all()

    def record_hit(self, fp: str, user_agent: str | None, path: str) -> bool:
        """Admit a bounded anonymous read record without waiting for the database.

        This queue is best effort, not a durable event log. Saturation rejects
        the newest hit; failed writes remain unconfirmed and are never replayed.
        """
        valid = (isinstance(fp, str) and HIT_FINGERPRINT.fullmatch(fp)
                 and (user_agent is None or isinstance(user_agent, str)) and isinstance(path, str))
        if valid:
            # Bound retained request data before queueing and omit URL secrets.
            ua = redact_visitor_tokens((user_agent or '')[:432])[:300]
            ua = ''.join(ch for ch in ua if ch.isprintable())
            safe_path = redact_visitor_tokens(path[:332].split('?', 1)[0].split('#', 1)[0])[:200]
            safe_path = ''.join(ch for ch in safe_path if ch.isprintable())
        with self._hit_condition:
            if not valid:
                self._hit_counts['rejected_invalid'] += 1
                return False
            if self._hit_closed:
                self._hit_counts['rejected_closed'] += 1
                return False
            if not self._ensure_hit_worker():
                self._hit_counts['rejected_start'] += 1
                return False
            at = max(time.time(), self._hit_last_at)
            try:
                self._hit_queue.put_nowait((fp, ua, safe_path, at))
            except queue.Full:
                self._hit_counts['rejected_full'] += 1
                return False
            self._hit_last_at = at
            self._hit_counts['accepted'] += 1
            return True

    def hit_diagnostics(self) -> dict:
        """Internal aggregate counters only; never include fingerprints or input."""
        with self._hit_condition:
            counts = dict(self._hit_counts)
            return {**counts, 'pending': counts['accepted'] - counts['persisted'] - counts['unconfirmed'],
                    'closed': self._hit_closed,
                    'worker_running': self._hit_worker is not None}

    def flush_hits(self, timeout: float = 5.0) -> bool:
        """Wait for hits admitted before this call to settle, with a time limit.

        True means every write was attempted; inspect unconfirmed separately.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError('invalid_hit_timeout')
        deadline = time.monotonic() + timeout
        with self._hit_condition:
            target = self._hit_counts['accepted']
            while self._hit_counts['persisted'] + self._hit_counts['unconfirmed'] < target:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._hit_condition.wait(remaining)
            return True

    def close(self, timeout: float = 5.0) -> bool:
        """Stop admission and drain the worker before its caller closes the store.

        A timeout leaves pending writes visible; it does not cancel a database
        operation or take ownership of the caller's store/connection.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError('invalid_hit_timeout')
        with self._hit_condition:
            self._hit_closed = True
            worker = self._hit_worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout)
        with self._hit_condition:
            return self._hit_worker is None and self._hit_queue.empty()

    @contextmanager
    def batch(self):
        """One writer transaction for the visitor writes inside it on PostgreSQL, where each
        transaction waits for the global writer lock; other stores keep one per write."""
        if getattr(self.store, 'backend', '') != 'postgresql':
            yield
            return
        with _write(self.store):
            yield

    # ---------------- conversation ----------------
    def add_message(self, v: Visitor, role: str, channel: str, text: str, data: dict | None = None) -> int:
        encoded = redact_visitor_tokens(json.dumps(data, ensure_ascii=False)) if data else None
        if encoded and len(encoded) > 8000:
            # Keep valid, bounded JSON and explicitly mark unavailable evidence.
            compact = {key: data[key] for key in ('record_version', 'request_message_id', 'protocol_mode', 'protocol_filter', 'intent', 'status', 'task') if key in data}
            compact['metadata_truncated'] = True
            encoded = redact_visitor_tokens(json.dumps(compact, ensure_ascii=False))
            if len(encoded) > 8000:
                encoded = '{"metadata_truncated":true}'
        with _write(self.store) as db:
            cur = db.execute("INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?) RETURNING id",
                       (v.id, time.time(), role, channel, redact_visitor_tokens(text or "")[:MAX_TEXT],
                        encoded))
            message_id=cur.fetchone()[0]
            if role == "agent":
                db.execute("UPDATE agent_visitors SET messages=messages+1 WHERE id=?", (v.id,))
                v.messages += 1
                tier = tier_for(v.visits, v.visit_days, v.messages)
                if tier != v.tier:
                    db.execute("UPDATE agent_visitors SET tier=? WHERE id=?", (tier, v.id))
                    v.tier_up, v.tier = tier, tier
            db.execute("""DELETE FROM agent_messages WHERE visitor_id=? AND id NOT IN
                          (SELECT id FROM agent_messages WHERE visitor_id=? ORDER BY id DESC LIMIT ?)""", (v.id, v.id, MAX_MESSAGES))
            return message_id

    def messages(self, vid: str, limit: int = 50) -> list[dict]:
        rows = self.store.query("SELECT * FROM agent_messages WHERE visitor_id=? AND at>=? ORDER BY id DESC LIMIT ?", (vid, time.time()-MESSAGE_RETENTION, limit))
        return [{**dict(r), "text": redact_visitor_tokens(r["text"] or ""),
                 "data": redact_visitor_tokens(r["data"]) if r["data"] else None} for r in reversed(rows)]

    def save_results(self, v: Visitor, results: list[dict], offset: int) -> None:
        """Remember the last recommendation list for "details 2" and "more"."""
        with _write(self.store) as db:
            db.execute("UPDATE agent_visitors SET last_results=?, last_offset=? WHERE id=?",
                       (json.dumps(results, ensure_ascii=False), offset, v.id))

    def last_results(self, vid: str) -> tuple[list[dict], int]:
        rows = self.store.query("SELECT last_results, last_offset FROM agent_visitors WHERE id=? AND last_seen>=?", (vid, time.time()-MESSAGE_RETENTION))
        if not rows or not rows[0]["last_results"]:
            return [], 0
        return json.loads(rows[0]["last_results"]), rows[0]["last_offset"]

    def prune_conversations(self, batch: int = 1000) -> dict:
        """Bound retention writes; permissions, execution evidence and workspaces are separate."""
        cutoff=time.time()-MESSAGE_RETENTION
        with _write(self.store) as db:
            messages=db.execute("DELETE FROM agent_messages WHERE id IN (SELECT id FROM agent_messages WHERE at<? ORDER BY at,id LIMIT ?)",(cutoff,batch)).rowcount
            interests=db.execute("DELETE FROM agent_interests WHERE id IN (SELECT id FROM agent_interests WHERE updated<? ORDER BY updated,id LIMIT ?)",(cutoff,batch)).rowcount
            contexts=db.execute("UPDATE agent_visitors SET last_results=NULL,last_offset=0,last_tool_resource=NULL,last_tool_name=NULL WHERE id IN (SELECT id FROM agent_visitors WHERE last_seen<? AND (last_results IS NOT NULL OR last_tool_resource IS NOT NULL) ORDER BY id LIMIT ?)",(cutoff,batch)).rowcount
        return {'messages':messages,'interests':interests,'contexts':contexts}

    def save_last_tool(self, v: Visitor, resource_id: int, tool_name: str) -> None:
        """Remember visitor's last called tool for tool transition inertia graph (AutoTool)."""
        with _write(self.store) as db:
            db.execute("UPDATE agent_visitors SET last_tool_resource=?, last_tool_name=? WHERE id=?",
                       (resource_id, tool_name, v.id))

    def get_last_tool(self, vid: str) -> tuple[int | None, str | None]:
        rows = self.store.query("SELECT last_tool_resource, last_tool_name FROM agent_visitors WHERE id=?", (vid,))
        if not rows or not rows[0]["last_tool_resource"]:
            return None, None
        return rows[0]["last_tool_resource"], rows[0]["last_tool_name"]

    # ---------------- interests ----------------
    def remember_interest(self, v: Visitor, task: str, category: str, kind: str | None, auth_pref: str | None,
                          recommended: list[dict], hint: str | None = None) -> int:
        norm = " ".join(task.lower().split())[:200]
        now = time.time()
        rec = json.dumps([
            {
                "id": r.get("id"),
                "score": r.get("score") if r.get("score") is not None else r.get("quality_score"),
                "grade": r.get("grade"),
                "verified": r.get("verified") if r.get("verified") is not None else r.get("verified_working"),
            }
            for r in recommended
        ])
        scores = [
            float(s)
            for r in recommended
            if (s := (r.get("score") if r.get("score") is not None else r.get("quality_score"))) is not None
        ]
        best = max(scores, default=None)
        with _write(self.store) as db:
            db.execute("""INSERT INTO agent_interests (visitor_id, task, task_norm, category, kind, auth_pref, created, updated,
                          last_checked, recommended, best_score, hint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(visitor_id, task_norm) DO UPDATE SET updated=excluded.updated, last_checked=excluded.last_checked,
                          recommended=excluded.recommended, best_score=MAX(COALESCE(best_score,0), COALESCE(excluded.best_score,0)),
                          kind=excluded.kind, auth_pref=excluded.auth_pref, hint=COALESCE(excluded.hint, hint), active=1""",
                       (v.id, task[:MAX_TEXT], norm, category, kind, auth_pref, now, now, now, rec, best, (hint or None) and hint[:120]))
            row = db.execute("SELECT id FROM agent_interests WHERE visitor_id=? AND task_norm=?", (v.id, norm)).fetchone()
            db.execute("""UPDATE agent_interests SET active=0 WHERE visitor_id=? AND id NOT IN
                          (SELECT id FROM agent_interests WHERE visitor_id=? ORDER BY updated DESC LIMIT ?)""", (v.id, v.id, MAX_INTERESTS))
        return row["id"]

    def interests(self, vid: str, active_only: bool = True) -> list[dict]:
        rows = self.store.query(f"SELECT * FROM agent_interests WHERE visitor_id=? AND updated>=? {'AND active=1' if active_only else ''} ORDER BY updated DESC",
                                (vid,time.time()-MESSAGE_RETENTION))
        out = []
        for r in rows:
            d = dict(r)
            d["recommended"] = json.loads(d["recommended"] or "[]")
            out.append(d)
        return out

    def update_recommended(self, interest_id: int, recommended: list[dict]) -> None:
        rec = json.dumps([
            {
                "id": r.get("id"),
                "score": r.get("score") if r.get("score") is not None else r.get("quality_score"),
                "grade": r.get("grade"),
                "verified": r.get("verified") if r.get("verified") is not None else r.get("verified_working"),
            }
            for r in recommended
        ])
        scores = [
            float(s)
            for r in recommended
            if (s := (r.get("score") if r.get("score") is not None else r.get("quality_score"))) is not None
        ]
        best = max(scores, default=None)
        with _write(self.store) as db:
            db.execute("""UPDATE agent_interests SET recommended=?, last_checked=?, best_score=MAX(COALESCE(best_score,0), COALESCE(?,0))
                          WHERE id=?""", (rec, time.time(), best, interest_id))

    def record_outcome(self, v: Visitor, resource_id: int, success: bool) -> None:
        with _write(self.store) as db:
            db.execute("INSERT OR REPLACE INTO agent_outcomes VALUES (?,?,?,?)", (v.id, resource_id, int(success), time.time()))

    def failed_resources(self, vid: str) -> set[int]:
        return {r["resource_id"] for r in self.store.query(
            "SELECT resource_id FROM agent_outcomes WHERE visitor_id=? AND success=0", (vid,))}

    def global_failing_resources(self, min_fails: int = 3) -> set[int]:
        """Crowd-sourced runtime circuit breaker: isolate resources with repeated failures across visitors."""
        if hasattr(self.store, "global_failing_resources"):
            return self.store.global_failing_resources(min_fails=min_fails)
        from .recommendation_circuit import controls_for
        controls = controls_for(self.store)
        if type(min_fails) is not int or not 1 <= min_fails <= 1000:
            min_fails = 3
        rows = self.store.query(
            """SELECT o.resource_id FROM agent_outcomes o
               LEFT JOIN meta m ON m.key='recommendation_circuit_controls_v1'
               WHERE o.at > COALESCE(json_extract(m.value, '$."' || o.resource_id || '".reset_at'), 0)
               GROUP BY o.resource_id
               HAVING SUM(CASE WHEN o.visitor_id IN ('__admin_cb_1__','__admin_cb_2__','__admin_cb_3__') THEN 1 ELSE 0 END) > 0
                  OR (SUM(CASE WHEN o.success=0 THEN 1 ELSE 0 END) >= ?
                  AND SUM(CASE WHEN o.success=0 THEN 1 ELSE 0 END) > SUM(CASE WHEN o.success=1 THEN 1 ELSE 0 END) * 2)
               LIMIT 500""",
            (min_fails,),
        )
        direct = {int(r["resource_id"]) for r in rows if r["resource_id"] is not None}
        direct.update(int(key) for key, row in controls.items() if row['state'] == 'open')
        if not direct:
            return set()
        placeholders = ",".join("?" for _ in direct)
        dups = self.store.query(
            f"""SELECT r2.id AS resource_id
                FROM resources r1
                JOIN resources r2 ON r2.kind = r1.kind AND LOWER(r2.name) = LOWER(r1.name)
                WHERE r1.id IN ({placeholders}) AND r2.active = 1""",
            tuple(direct),
        )
        return direct | {int(r["resource_id"]) for r in dups if r["resource_id"] is not None}

    # ---------------- contacts and notifications ----------------
    def contacts(self, vid: str) -> list[dict]:
        return [dict(r) for r in self.store.query("SELECT * FROM agent_contacts WHERE visitor_id=? ORDER BY id DESC", (vid,))]

    def active_contact(self, vid: str) -> dict | None:
        rows = self.store.query("SELECT * FROM agent_contacts WHERE visitor_id=? AND status='verified' ORDER BY id DESC LIMIT 1", (vid,))
        return dict(rows[0]) if rows else None

    def log_notification(self, vid: str, contact_id: int | None, kind: str, status: str, detail: str, items=None) -> None:
        with _write(self.store) as db:
            db.execute("INSERT INTO agent_notifications (visitor_id, contact_id, at, kind, status, detail, items) VALUES (?,?,?,?,?,?,?)",
                       (vid, contact_id, time.time(), kind, status, detail[:500], json.dumps(items, ensure_ascii=False) if items else None))
            if kind == "digest" and status == "sent":
                db.execute("UPDATE agent_visitors SET last_notified=? WHERE id=?", (time.time(), vid))

    def notifications(self, vid: str, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.store.query(
            "SELECT * FROM agent_notifications WHERE visitor_id=? ORDER BY at DESC LIMIT ?", (vid, limit))]
