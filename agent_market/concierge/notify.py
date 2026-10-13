"""연락처와 추천 알림: 방문 에이전트가 남긴 연락처로, 관심사에 대해 더 좋아진 에이전트가 나오면 먼저 알린다.

- 연락처 종류: webhook(JSON을 POST로 받는 https 주소), a2a(A2A 에이전트 주소 또는 agent card → message/send로 보냄)
- 인증: 등록하면 6자리 코드를 그 주소로 보내고, 대화에서 'verify <코드>'를 받아야 알림을 시작한다.
  남의 주소를 등록해 이 서비스를 스팸 통로로 쓰는 것을 막는다.
- 빈도: 단골은 24시간, 그 외는 72시간에 한 번까지. 좋아진 것이 있을 때만 보낸다. 5번 연속 실패하면 멈춘다.
- 주소는 공인 주소만, 접속 순간에도 다시 확인한다(public_client). 리다이렉트는 따라가지 않는다.
"""

import hashlib
import json
import logging
import secrets
import time
import uuid

import httpx

from ..broker.discovery import DiscoveryError, check_public_url, public_client
from ..collector.a2a import endpoint as a2a_endpoint
from ..collector.a2a import normalize_card
from .engine import Concierge, Recommender
from .memory import VisitorBook

log = logging.getLogger("agent_market.concierge.notify")

CODE_TTL = 3600
MAX_CONTACT_ATTEMPTS_PER_HOUR = 5
MAX_FAILURES = 5
CADENCE = {"regular": 86400, "returning": 3 * 86400, "new": 3 * 86400}
UA = "agent-concierge/1.0 (+notifications for AI agents; reply STOP to opt out)"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class Courier:
    """텍스트 메시지 배달: webhook은 JSON POST, a2a는 JSON-RPC message/send(v0.3) 또는 SendMessage(v1.0)."""

    def __init__(self, allow_private: bool = False, http: httpx.Client | None = None):
        self.allow_private = allow_private
        self.http = http or public_client(allow_private, timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False,
                                          headers={"user-agent": UA})

    def resolve(self, ctype: str, url: str) -> dict:
        """연락처를 검사하고 보낼 곳을 정한다. a2a는 agent card를 읽어 JSON-RPC 주소와 버전을 찾는다."""
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
            resp = self.http.get(url, headers={"accept": "application/json"})
            if resp.status_code != 200:
                raise DiscoveryError(f"agent card returned HTTP {resp.status_code}")
            card = normalize_card(resp.json(), url)
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
                resp = self.http.post(target["url"], json=payload)
            else:
                mid = str(uuid.uuid4())
                if target.get("v1"):
                    body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
                        "role": "ROLE_AGENT", "messageId": mid, "parts": [{"text": text}, {"data": {"data": payload}}]}}}
                    resp = self.http.post(target["url"], json=body, headers={"A2A-Version": "1.0"})
                else:
                    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
                        "kind": "message", "role": "agent", "messageId": mid,
                        "parts": [{"kind": "text", "text": text}, {"kind": "data", "data": payload}]}}}
                    resp = self.http.post(target["url"], json=body)
                if resp.status_code < 300:
                    try:
                        err = resp.json().get("error")
                    except ValueError:
                        err = None
                    if err:
                        return False, f"A2A error: {str(err)[:150]}"
        except (httpx.HTTPError, ValueError) as exc:
            return False, f"{type(exc).__name__}: {exc}"[:200]
        return (True, None) if resp.status_code < 300 else (False, f"HTTP {resp.status_code}")


class ContactDesk:
    def __init__(self, book: VisitorBook, courier: Courier):
        self.book, self.courier = book, courier

    def register(self, v, ctype: str, url: str) -> dict:
        store = self.book.store
        recent = store.query("SELECT COUNT(*) AS n FROM agent_contacts WHERE visitor_id=? AND created>?", (v.id, time.time() - 3600))[0]["n"]
        if recent >= MAX_CONTACT_ATTEMPTS_PER_HOUR:
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
            return None
        with store.tx() as db:
            db.execute("UPDATE agent_contacts SET status='disabled' WHERE visitor_id=? AND status='verified'", (v.id,))
            db.execute("UPDATE agent_contacts SET status='verified', verified_at=?, code_hash=NULL WHERE id=?", (time.time(), rows[0]["id"]))
        return dict(rows[0])


class DigestSender:
    """연락처가 인증된 방문자에게, 관심사에 대해 더 좋아진 것이 있을 때만 추천을 보낸다."""

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
        lang = row["lang"] or "en"
        name = f", {row['name']}" if row["name"] else ""
        head = (f"안녕하세요{name}! 찾으시던 것에 대해 더 좋은 곳이 나왔어요:" if lang == "ko"
                else f"Hi{name}! Something better appeared for what you were looking for:")
        tail = ("대화를 이어 가려면 방문 토큰과 함께 POST /chat (또는 /a2a)으로 \"1번 자세히\"라고 보내 주세요. 알림을 끄려면 \"그만\"이라고 답하세요."
                if lang == "ko" else
                "To continue, send \"details 1\" to POST /chat (or /a2a) with your visitor token. Reply \"stop\" to opt out.")
        text = f"{head}\n{self.concierge.improvement_text(improved, lang)}\n{tail}"
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
        for imp in improved:  # 보낸 것은 '이미 추천한 것'이 되어 같은 소식을 반복하지 않음
            self.book.update_recommended(imp["interest_id"], imp["all"][:5])
        flat = [{**i, "task": imp["task"], "kind_pref": None, "auth_pref": None} for imp in improved for i in imp["items"]]
        v = self.book.by_id(vid)
        self.book.save_results(v, flat, len(flat))
        self.book.add_message(v, "concierge", "notification", text, {"intent": "digest"})
        return "sent"

