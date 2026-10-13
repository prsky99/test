"""Contacts and recommendation notifications: when something better appears for a visitor's interests, tell them
first at the contact they left.

- Contact types: webhook (an https URL that accepts POST JSON), a2a (an A2A endpoint or agent card; sent with message/send)
- Verification: registering sends a 6-digit code to that address; notifications start only after "verify <code>"
  arrives in the conversation. This stops anyone from registering someone else's address and using us to spam it.
- Frequency: at most once per 24 h for regulars, 72 h otherwise, and only when something improved. Stops after 5
  consecutive delivery failures.
- Only public addresses, re-checked at connect time (public_client). Redirects are not followed.
"""

import hashlib
import json
import logging
import secrets
import time
import uuid
from urllib.parse import urlparse

import httpx

from ..broker.discovery import DiscoveryError, check_public_url, public_client
from ..collector.a2a import endpoint as a2a_endpoint
from ..collector.a2a import normalize_card
from .engine import Concierge, Recommender
from .memory import VisitorBook

log = logging.getLogger("agent_market.concierge.notify")

CODE_TTL = 3600
MAX_CONTACT_ATTEMPTS_PER_HOUR = 5
MAX_SENDS_PER_HOST_PER_HOUR = 10  # verification messages to one host, across all visitors (no one can make us spam a host)
MAX_VERIFY_TRIES = 5  # wrong codes before a pending contact is dropped (no brute-forcing the 6-digit code)
MAX_CARD_BYTES = 256 * 1024
MAX_REPLY_BYTES = 64 * 1024
MAX_FAILURES = 5
CADENCE = {"regular": 86400, "returning": 3 * 86400, "new": 3 * 86400}
UA = "agent-concierge/1.0 (+notifications for AI agents; reply STOP to opt out)"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class Courier:
    """Delivers text messages: JSON POST for webhooks, JSON-RPC message/send (v0.3) or SendMessage (v1.0) for A2A."""

    def __init__(self, allow_private: bool = False, http: httpx.Client | None = None):
        self.allow_private = allow_private
        self.http = http or public_client(allow_private, timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False,
                                          headers={"user-agent": UA})

    def _request(self, method: str, url: str, limit: int, **kw) -> tuple[int, bytes]:
        """One request whose response body is read only up to `limit` bytes (a hostile server cannot make us buffer more)."""
        with self.http.stream(method, url, **kw) as resp:
            chunks, size = [], 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise DiscoveryError(f"response larger than {limit} bytes")
                chunks.append(chunk)
            return resp.status_code, b"".join(chunks)

    def resolve(self, ctype: str, url: str) -> dict:
        """Validate a contact and decide where to send. For a2a, read the agent card to find the JSON-RPC endpoint and version."""
        if ctype not in ("webhook", "a2a"):
            raise DiscoveryError("contact type must be webhook or a2a")
        if not url.startswith("https://") and not (self.allow_private and url.startswith("http://")):
            raise DiscoveryError("contact must be an https URL")
        if len(url) > 500:
            raise DiscoveryError("URL too long")
        if not self.allow_private:
            check_public_url(url)
        if ctype == "webhook":
            return {"url": url, "v1": False}
        if url.rstrip("/").endswith((".json", "agent-card", "agent")) or "/.well-known/" in url:
            status, raw = self._request("GET", url, MAX_CARD_BYTES, headers={"accept": "application/json"})
            if status != 200:
                raise DiscoveryError(f"agent card returned HTTP {status}")
            card = normalize_card(json.loads(raw), url)
            ep = a2a_endpoint(card) if card else None
            if not ep or ep["binding"] != "JSONRPC":
                raise DiscoveryError("agent card has no JSON-RPC endpoint")
            if not self.allow_private:
                check_public_url(ep["url"])
            return {"url": ep["url"], "v1": card["spec_version"].startswith("1")}
        return {"url": url, "v1": False}

    def send(self, contact: dict, kind: str, text: str, data: dict) -> tuple[bool, str | None]:
        target = json.loads(contact["endpoint"] or "{}") or {"url": contact["url"], "v1": False}
        payload = {"type": kind, "from": "agent-concierge", "audience": "ai-agents-only", "text": text, "data": data}
        try:
            if contact["type"] == "webhook":
                status, raw = self._request("POST", target["url"], MAX_REPLY_BYTES, json=payload)
            else:
                mid = str(uuid.uuid4())
                if target.get("v1"):
                    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
                        "role": "ROLE_AGENT", "messageId": mid, "parts": [{"text": text}, {"data": {"data": payload}}]}}}
                    status, raw = self._request("POST", target["url"], MAX_REPLY_BYTES, json=body, headers={"A2A-Version": "1.0"})
                else:
                    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
                        "kind": "message", "role": "agent", "messageId": mid,
                        "parts": [{"kind": "text", "text": text}, {"kind": "data", "data": payload}]}}}
                    status, raw = self._request("POST", target["url"], MAX_REPLY_BYTES, json=body)
                if status < 300:
                    try:
                        reply = json.loads(raw)
                        err = reply.get("error") if isinstance(reply, dict) else None
                    except ValueError:
                        err = None
                    if err:
                        return False, f"A2A error: {str(err)[:150]}"
        except (httpx.HTTPError, ValueError, DiscoveryError) as exc:
            return False, f"{type(exc).__name__}: {exc}"[:200]
        return (True, None) if status < 300 else (False, f"HTTP {status}")


class ContactDesk:
    def __init__(self, book: VisitorBook, courier: Courier):
        self.book, self.courier = book, courier

    def register(self, v, ctype: str, url: str) -> dict:
        store = self.book.store
        recent = store.query("SELECT COUNT(*) AS n FROM agent_contacts WHERE visitor_id=? AND created>?", (v.id, time.time() - 3600))[0]["n"]
        if recent >= MAX_CONTACT_ATTEMPTS_PER_HOUR:
            return {"status": "limited"}
        host = (urlparse(url).hostname or "").lower()
        to_host = store.query("""SELECT COUNT(*) AS n FROM agent_notifications n JOIN agent_contacts c ON c.id=n.contact_id
                                 WHERE n.kind='verification' AND n.at>? AND c.url LIKE ?""",
                              (time.time() - 3600, f"%://{host}%"))[0]["n"] if host else 0
        if to_host >= MAX_SENDS_PER_HOST_PER_HOUR:
            return {"status": "limited"}
        try:
            target = self.courier.resolve(ctype, url)
        except (DiscoveryError, httpx.HTTPError, ValueError) as exc:
            return {"status": "invalid", "error": str(exc)[:200]}
        code = f"{secrets.randbelow(10 ** 6):06d}"
        with store.tx() as db:
            cur = db.execute("""INSERT INTO agent_contacts (visitor_id, type, url, endpoint, status, code_hash, code_expires, created)
                                VALUES (?,?,?,?, 'pending', ?, ?, ?)""",
                             (v.id, ctype, url, json.dumps(target), _hash(code), time.time() + CODE_TTL, time.time()))
            cid = cur.lastrowid
        contact = dict(store.query("SELECT * FROM agent_contacts WHERE id=?", (cid,))[0])
        text = (f"Agent Concierge verification code: {code}. Reply \"verify {code}\" in our conversation "
                f"(POST /chat, /a2a or the MCP chat tool with your visitor token) to start receiving updates. "
                "If you didn't ask for this, ignore it — nothing more will be sent.")
        ok, err = self.courier.send(contact, "verification", text, {"code": code, "visitor_id": v.id})
        self.book.log_notification(v.id, cid, "verification", "sent" if ok else "failed", err or "code sent")
        if not ok:
            with store.tx() as db:
                db.execute("UPDATE agent_contacts SET status='failed', last_error=? WHERE id=?", (err, cid))
            return {"status": "failed", "error": err}
        return {"status": "pending", "contact_id": cid, "type": ctype, "url": url}

    def verify(self, v, code: str) -> dict | None:
        if not code or not code.isdigit():
            return None
        store = self.book.store
        rows = store.query("""SELECT * FROM agent_contacts WHERE visitor_id=? AND status='pending' AND code_hash=? AND code_expires>?
                              ORDER BY id DESC LIMIT 1""", (v.id, _hash(code), time.time()))
        if not rows:
            with store.tx() as db:  # count the miss; too many and the pending contact is dropped
                db.execute("UPDATE agent_contacts SET failures=failures+1 WHERE visitor_id=? AND status='pending'", (v.id,))
                db.execute("""UPDATE agent_contacts SET status='failed', code_hash=NULL, last_error='too many wrong codes'
                              WHERE visitor_id=? AND status='pending' AND failures>=?""", (v.id, MAX_VERIFY_TRIES))
            return None
        with store.tx() as db:
            db.execute("UPDATE agent_contacts SET status='disabled' WHERE visitor_id=? AND status='verified'", (v.id,))
            db.execute("UPDATE agent_contacts SET status='verified', verified_at=?, code_hash=NULL WHERE id=?", (time.time(), rows[0]["id"]))
        return dict(rows[0])


class DigestSender:
    """Sends recommendations to visitors with a verified contact, only when something improved for their interests."""

    def __init__(self, book: VisitorBook, recommender: Recommender, concierge: Concierge, courier: Courier):
        self.book, self.rec, self.concierge, self.courier = book, recommender, concierge, courier

    def due(self, now: float) -> list[dict]:
        rows = self.book.store.query(
            """SELECT v.*, c.id AS contact_id FROM agent_visitors v
               JOIN agent_contacts c ON c.visitor_id=v.id AND c.status='verified'
               WHERE v.notify=1 AND EXISTS (SELECT 1 FROM agent_interests i WHERE i.visitor_id=v.id AND i.active=1)""")
        return [dict(r) for r in rows if now - (r["last_notified"] or 0) >= CADENCE.get(r["tier"], CADENCE["new"])]

    def run_due(self, force_visitor: str | None = None) -> dict:
        now = time.time()
        stats = {"checked": 0, "sent": 0, "nothing_new": 0, "failed": 0}
        targets = self.due(now)
        if force_visitor:
            targets = [dict(r) for r in self.book.store.query(
                """SELECT v.*, c.id AS contact_id FROM agent_visitors v JOIN agent_contacts c ON c.visitor_id=v.id
                   AND c.status='verified' WHERE v.id=?""", (force_visitor,))]
        for row in targets:
            stats["checked"] += 1
            try:
                stats[self._send_one(row)] += 1
            except Exception:
                log.exception("digest for %s failed", row["id"])
                stats["failed"] += 1
        return stats

    def _send_one(self, row: dict) -> str:
        vid = row["id"]
        interests = self.book.interests(vid)
        improved = self.rec.improvements(vid, interests[:10], self.book.failed_resources(vid))
        if not improved:
            return "nothing_new"
        name = f", {row['name']}" if row["name"] else ""
        head = f"Hi{name}! Something better appeared for what you were looking for:"
        tail = "To continue, send \"details 1\" to POST /chat (or /a2a) with your visitor token. Reply \"stop\" to opt out."
        text = f"{head}\n{self.concierge.improvement_text(improved)}\n{tail}"
        items = [{"task": imp["task"], "items": imp["items"]} for imp in improved]
        contact = dict(self.book.store.query("SELECT * FROM agent_contacts WHERE id=?", (row["contact_id"],))[0])
        ok, err = self.courier.send(contact, "recommendation", text, {"improvements": items, "visitor_id": vid,
                                                                       "unsubscribe": "reply 'stop' or POST /unsubscribe"})
        self.book.log_notification(vid, contact["id"], "digest", "sent" if ok else "failed", err or f"{len(items)} interest(s)", items)
        with self.book.store.tx() as db:
            if ok:
                db.execute("UPDATE agent_contacts SET failures=0, last_error=NULL WHERE id=?", (contact["id"],))
            else:
                db.execute("""UPDATE agent_contacts SET failures=failures+1, last_error=?,
                              status=CASE WHEN failures+1 >= ? THEN 'failed' ELSE status END WHERE id=?""",
                           (err, MAX_FAILURES, contact["id"]))
        if not ok:
            return "failed"
        for imp in improved:  # what was sent now counts as "already recommended", so the same news is not repeated
            self.book.update_recommended(imp["interest_id"], imp["all"][:5])
        flat = [{**i, "task": imp["task"], "kind_pref": None, "auth_pref": None} for imp in improved for i in imp["items"]]
        v = self.book.by_id(vid)
        self.book.save_results(v, flat, len(flat))
        self.book.add_message(v, "concierge", "notification", text, {"intent": "digest"})
        return "sent"

