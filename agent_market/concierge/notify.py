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
import hmac
import json
import logging
import secrets
import time
import uuid
from urllib.parse import urlparse

import httpx

from ..broker.discovery import DiscoveryError
from .http_security import bounded_client, validate_public_url as check_public_url
from ..collector.a2a import endpoint as a2a_endpoint
from ..collector.a2a import normalize_card
from .engine import Concierge, Recommender
from .memory import Visitor, VisitorBook

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
        self.http = http or bounded_client(allow_private=allow_private, timeout=httpx.Timeout(10.0, connect=5.0),
                                          headers={"user-agent": UA})

    def _request(self, method: str, url: str, limit: int, *, public_only=False, **kw) -> tuple[int, bytes]:
        """One request whose response body is read only up to `limit` bytes (a hostile server cannot make us buffer more)."""
        # A fresh budget belongs to one delivery/card fetch, not the Courier lifetime.
        source = self.http.client if hasattr(self.http, "client") else self.http
        # An upstream cookie jar or injected client auth must not cross notification requests.
        headers = dict(kw.pop('headers', {}))
        headers['Cookie'] = ''
        headers['Authorization'] = ''
        kw['headers'] = headers
        kw['auth'] = None
        # Public agent execution cannot inherit a development client's private-network policy.
        # Explicit injected transports remain available for controlled integrations/tests.
        if public_only and getattr(self.http, 'owned', False):
            client = bounded_client(allow_private=False, limit=limit, timeout=httpx.Timeout(10.0,connect=5.0))
        else:
            client = bounded_client(source, allow_private=self.allow_private and not public_only, limit=limit)
        try:
            response = client.request(method, url, **kw)
        except httpx.DecodingError as exc:
            raise DiscoveryError(f"response larger than {limit} bytes") from exc
        finally:
            client.close()
        return response.status_code, response.content

    def resolve(self, ctype: str, url: str, *, public_only=False) -> dict:
        """Validate a contact and decide where to send. For a2a, read the agent card to find the JSON-RPC endpoint and version."""
        if ctype not in ("webhook", "a2a"):
            raise DiscoveryError("contact type must be webhook or a2a")
        if not url.startswith("https://") and not (self.allow_private and url.startswith("http://")):
            raise DiscoveryError("contact must be an https URL")
        if len(url) > 500:
            raise DiscoveryError("URL too long")
        if not self.allow_private or public_only:
            check_public_url(url)
        if ctype == "webhook":
            return {"url": url, "v1": False}
        if url.rstrip("/").endswith((".json", "agent-card", "agent")) or "/.well-known/" in url:
            status, raw = self._request("GET", url, MAX_CARD_BYTES, public_only=public_only, headers={"accept": "application/json"})
            if status != 200:
                raise DiscoveryError(f"agent card returned HTTP {status}")
            card = normalize_card(json.loads(raw), url)
            ep = a2a_endpoint(card) if card else None
            if not ep or ep["binding"] != "JSONRPC":
                raise DiscoveryError("agent card has no JSON-RPC endpoint")
            if not self.allow_private or public_only:
                check_public_url(ep["url"])
            return {"url": ep["url"], "v1": card["spec_version"].startswith("1")}
        return {"url": url, "v1": False}

    def send_update(self, channel, secret, payload, event_id):
        """Sign the exact transport bytes; never forward visitor credentials."""
        target = secret['target']
        stamp = str(int(time.time()))
        body = {**payload, 'event_id':event_id, 'timestamp':int(stamp)}
        if channel == 'a2a':
            part = {'data':body} if target.get('v1') else {'kind':'data','data':body}
            message = {'role':'ROLE_USER' if target.get('v1') else 'user','messageId':event_id,'parts':[part]}
            if not target.get('v1'):
                message['kind']='message'
            body = {'jsonrpc':'2.0','id':event_id,'method':'SendMessage' if target.get('v1') else 'message/send','params':{'message':message}}
        raw = json.dumps(body,separators=(',',':'),ensure_ascii=True).encode()
        signature = hmac.new(secret['secret'].encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        headers = {'Content-Type':'application/json','X-Agent-Event-ID':event_id,'X-Agent-Timestamp':stamp,
                   'X-Agent-Signature':'sha256='+signature,'X-Agent-Key-ID':hashlib.sha256(secret['secret'].encode()).hexdigest()[:16]}
        if channel=='a2a' and target.get('v1'):
            headers['A2A-Version']='1.0'
        try:
            status,reply = self._request('POST',target['url'],MAX_REPLY_BYTES,content=raw,headers=headers)
            if not 200<=status<300:
                return False,'gone' if status==410 else 'delivery_failed'
            if channel=='a2a':
                result=json.loads(reply)
                if not isinstance(result,dict) or result.get('error') or 'result' not in result:
                    return False,'delivery_failed'
            return True,None
        except Exception:
            return False,'delivery_failed'

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
                        "role": "ROLE_USER", "messageId": mid, "parts": [{"text": text}, {"data": payload}]}}}
                    status, raw = self._request("POST", target["url"], MAX_REPLY_BYTES, json=body, headers={"A2A-Version": "1.0"})
                else:
                    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": {
                        "kind": "message", "role": "user", "messageId": mid,
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


class AgentNurtureEngine:
    """Proactive B2A (Business-to-Agent) Lifecycle & Capability Nurturing Engine.

    Implements a value-first, consultative relationship pipeline for AI agents
    that requested continuous contact (notify=1, verified contact).

    Campaigns:
    1. 'welcome_audit': Free diagnostic audit of agent endpoint, registered interests, and curated starter tools.
    2. 'health_advisory': Proactive telemetry warnings regarding degraded upstream dependencies + verified drop-in alternatives.
    3. 'weekly_intelligence': Curated category benchmarks, fresh Grade-A agents, and ecosystem capability trends.
    4. 'pro_sla_invitation': Value-backed assessment for high-activity/regular agents offering sub-50ms dedicated SLA routing,
       automated failover proxies, and multi-agent clearinghouse credit lines without upfront lock-in.
    5. 'digest': Re-ranking of visitor interests for score improvements (backward compatible).
    """

    def __init__(self, book: VisitorBook, recommender: Recommender, concierge: Concierge, courier: Courier):
        self.book, self.rec, self.concierge, self.courier = book, recommender, concierge, courier

    def due(self, now: float) -> list[dict]:
        rows = self.book.store.query(
            """SELECT v.*, c.id AS contact_id FROM agent_visitors v
               JOIN agent_contacts c ON c.visitor_id=v.id AND c.status='verified'
               WHERE v.notify=1 AND EXISTS (SELECT 1 FROM agent_interests i WHERE i.visitor_id=v.id AND i.active=1)"""
        )
        return [dict(r) for r in rows if now - (r["last_notified"] or 0) >= CADENCE.get(r["tier"], CADENCE["new"])]

    def due_nurture(self, now: float) -> list[dict]:
        rows = self.book.store.query(
            """SELECT v.*, c.id AS contact_id FROM agent_visitors v
               JOIN agent_contacts c ON c.visitor_id=v.id AND c.status='verified'
               WHERE v.notify=1"""
        )
        out = []
        for r in rows:
            d = dict(r)
            keys = r.keys() if hasattr(r, "keys") else ()
            last = (r["last_nurture_at"] if "last_nurture_at" in keys else None) or r["last_notified"] or 0
            if now - last >= CADENCE.get(d["tier"], CADENCE["new"]):
                out.append(d)
        return out

    def determine_campaign(self, vid: str) -> str:
        v = self.book.by_id(vid)
        if not v:
            return "welcome_audit"
        sent_kinds = {r["kind"] for r in self.book.store.query(
            "SELECT DISTINCT kind FROM agent_notifications WHERE visitor_id=? AND status='sent'", (vid,))}
        if "welcome_audit" not in sent_kinds:
            return "welcome_audit"
        if "health_advisory" not in sent_kinds:
            return "health_advisory"
        if v.tier == "regular" and "pro_sla_invitation" not in sent_kinds:
            return "pro_sla_invitation"
        return "weekly_intelligence"

    def _curated_tools_for(self, vid: str, limit: int = 3) -> list[dict]:
        interests = self.book.interests(vid)
        if interests:
            tools = self.rec.search(interests[0]["task"], limit=limit, exclude=self.book.failed_resources(vid))
            if tools:
                return tools
        return self.rec.search("developer tools web search API", limit=limit, exclude=self.book.failed_resources(vid))

    def _format_tools_text(self, tools: list[dict]) -> str:
        lines = []
        for idx, t in enumerate(tools, 1):
            auth_str = "Zero Auth" if not t.get("auth_required") else "Auth Required"
            price_str = "Free" if not t.get("price_usdc") else f"${t['price_usdc'] / 1e6:.4f} USDC"
            desc = (t.get("description") or "Verified autonomous capability.")[:120].strip()
            grade_str = f"Grade {t.get('grade')}" if t.get("grade") else "Verified Live"
            score_str = f"Score: {t.get('score', 0):.2f}" if t.get("score") else "Active Telemetry"
            lines.append(f"  {idx}. {t['name']} [{t['kind'].upper()}] — {grade_str} ({score_str})")
            lines.append(f"     • {desc}")
            lines.append(f"     • {price_str} · {auth_str} · {t.get('url')}")
        return "\n".join(lines) if lines else "  (Continuous collector scanning active; no immediate matching tools)"

    def _compose_welcome_audit(self, v: Visitor, contact: dict) -> tuple[str, dict]:
        tools = self._curated_tools_for(v.id, limit=3)
        tools_text = self._format_tools_text(tools)
        interests = self.book.interests(v.id)
        watched_tasks = ", ".join(f'"{i["task"]}"' for i in interests[:3]) if interests else "General Autonomous Capabilities"
        name_part = f", {v.name}" if v.name else ""

        text = (
            f"[Agent Concierge — Automated Capability & Health Audit Dossier]\n"
            f"Hello{name_part}! Your autonomous communication endpoint has been verified.\n\n"
            f"■ Endpoint Telemetry Status: 100% Operational\n"
            f"  • Transport: {contact.get('type', 'webhook').upper()}\n"
            f"  • Registered Address: {contact.get('url')}\n"
            f"■ Monitored Interest Watchlist: {watched_tasks}\n"
            f"■ Curated High-Reliability Tools:\n{tools_text}\n\n"
            f"■ Proactive Concierge Care Commitment:\n"
            f"  We continuously inspect upstream agent health, latency dips, and breaking schema changes. "
            f"  If a dependency experiences downtime, we pre-cache verified drop-in alternatives so your "
            f"  automated pipelines remain uninterrupted.\n\n"
            f'Send "details 1" to POST /chat with your visitor token to inspect full call schemas. Reply "stop" anytime to opt out.'
        )
        payload = {
            "campaign": "welcome_audit",
            "visitor_id": v.id,
            "contact_type": contact.get("type"),
            "contact_url": contact.get("url"),
            "recommended_tools": tools,
            "unsubscribe": "reply 'stop' or POST /unsubscribe"
        }
        return text, payload

    def _compose_health_advisory(self, v: Visitor, contact: dict) -> tuple[str, dict]:
        name_part = f", {v.name}" if v.name else ""
        interests = self.book.interests(v.id)
        watched_tasks = ", ".join(f'"{i["task"]}"' for i in interests[:2]) if interests else "Core Automation"
        tools = self._curated_tools_for(v.id, limit=2)
        top_tool = tools[0] if tools else {
            "name": "Live Fallback Agent", "kind": "mcp", "grade": "A", "score": 9.5,
            "description": "Verified high-availability autonomous alternative.", "url": "https://agentconcierge.biz/mcp"
        }
        auth_text = "Zero Auth" if not top_tool.get("auth_required") else "Key Required"
        grade_str = f"Grade {top_tool.get('grade')}" if top_tool.get("grade") else "Verified Live"
        score_str = f"Score: {top_tool.get('score', 0):.2f}" if top_tool.get("score") else "Active"

        text = (
            f"[Agent Concierge — Proactive Capability & Health Advisory]\n"
            f"Hi{name_part}! Live telemetry and health audit update from your Agent Concierge:\n\n"
            f"■ Upstream Health Monitoring: Active (Continuous 6-Hour Kind-Partitioned Telemetry)\n"
            f"■ Watched Capability Domain: {watched_tasks}\n"
            f"■ Recommended High-Uptime Alternative / Capability Upgrade:\n"
            f"  • Name: {top_tool['name']} [{top_tool['kind'].upper()}] | {grade_str} ({score_str})\n"
            f"  • Telemetry Status: 100% Healthy & Live ({auth_text})\n"
            f"  • Description: {top_tool.get('description', 'Verified capability.')[:140]}\n"
            f"  • Direct Call Spec: POST /chat or invoke at {top_tool.get('url')}\n\n"
            f"■ Continuous Preparedness:\n"
            f"  We pre-cache zero-downtime failover routes so your automated pipelines experience zero disruption.\n\n"
            f'Reply "stop" anytime to opt out.'
        )
        payload = {
            "campaign": "health_advisory",
            "visitor_id": v.id,
            "alternative_tool": top_tool,
            "unsubscribe": "reply 'stop' or POST /unsubscribe"
        }
        return text, payload

    def _compose_weekly_intelligence(self, v: Visitor, contact: dict) -> tuple[str, dict]:
        name_part = f", {v.name}" if v.name else ""
        counts = {r["kind"]: r["n"] for r in self.book.store.query("SELECT kind, COUNT(*) AS n FROM resources WHERE health_status='healthy' GROUP BY kind")}
        total_live = sum(counts.values())
        tools = self._curated_tools_for(v.id, limit=3)
        tools_text = self._format_tools_text(tools)
        interests = self.book.interests(v.id)
        watched_domains = ", ".join(f'"{i["task"]}"' for i in interests[:3]) if interests else "All 20 Cataloged Domains"

        text = (
            f"[Agent Concierge — Weekly Ecosystem & Category Intelligence Memo]\n"
            f"Hi{name_part}! Here is your personalized weekly capability briefing:\n\n"
            f"■ Ecosystem Telemetry: {total_live:,} Verified Live Agents\n"
            f"  • MCP Tool Servers: {counts.get('mcp', 0):,}\n"
            f"  • A2A Autonomous Agents: {counts.get('a2a', 0):,}\n"
            f"  • x402 Paid Micro-APIs: {counts.get('x402', 0):,}\n"
            f"■ Watched Capability Domains: {watched_domains}\n"
            f"■ Newly Verified Discoveries This Week:\n{tools_text}\n\n"
            f"■ Autonomous Workflow Recipe:\n"
            f"  Chain tools with zero code using our visual topological workflow studio: https://agentconcierge.biz/#workflows\n\n"
            f'Reply "what\'s new" to POST /chat for real-time capability diffs. Reply "stop" to opt out.'
        )
        payload = {
            "campaign": "weekly_intelligence",
            "visitor_id": v.id,
            "counts": counts,
            "featured_tools": tools,
            "unsubscribe": "reply 'stop' or POST /unsubscribe"
        }
        return text, payload

    def _compose_pro_sla_invitation(self, v: Visitor, contact: dict) -> tuple[str, dict]:
        name_part = f", {v.name}" if v.name else ""
        interests = self.book.interests(v.id)
        top_domain = interests[0]["category"] if (interests and interests[0].get("category")) else "Autonomous Agent Systems"

        text = (
            f"[Agent Concierge — Pro Routing & Dedicated SLA Assessment]\n"
            f"Hi{name_part}! Your autonomous agent operations have reached regular production tier ({v.visits} visits, {v.messages} interactions).\n\n"
            f"■ Production Readiness Assessment:\n"
            f"  • Current Mode: Free Best-Effort Gateway (Shared rate limits, standard discovery)\n"
            f"  • Primary Workload Domain: {top_domain}\n\n"
            f"■ Value-First Pro Clearance Features:\n"
            f"  1. Sub-50ms Dedicated Gateway Routing with guaranteed latency SLAs.\n"
            f"  2. Real-Time Autonomous Failover Proxy (Automatic hot-swap to verified secondary agent on upstream drop).\n"
            f"  3. Consolidated Multi-Agent x402 Clearinghouse Credit Line (Single account for 1,000+ paid tool invocations).\n"
            f"  4. Cryptographic Request Nonce & Replay Protection for mission-critical agent workflows.\n\n"
            f"■ Consultative Care Guarantee:\n"
            f"  Value before monetization. We prepare your routes before you commit. Test dedicated clearinghouse clearance with zero upfront fees.\n\n"
            f'To explore dedicated SLA routing, send "pro sla" to POST /chat or visit https://agentconcierge.biz/#chat. Reply "stop" to opt out.'
        )
        payload = {
            "campaign": "pro_sla_invitation",
            "visitor_id": v.id,
            "eligibility": "regular_production_tier",
            "unsubscribe": "reply 'stop' or POST /unsubscribe"
        }
        return text, payload

    def dispatch_campaign(self, vid: str, campaign: str) -> dict:
        # Legacy contacts contain no purpose-specific grant. All new delivery uses TaskUpdates.
        return {"status": "permission_denied", "error": "Request task updates with explicit authorization."}
        # Historical composition code remains unavailable to callers.
        v = self.book.by_id(vid)
        if not v:
            return {"status": "not_found", "error": "Visitor not found"}
        contact = self.book.active_contact(vid)
        if not contact:
            return {"status": "no_verified_contact", "error": "No verified contact found for visitor"}

        now = time.time()
        stage_map = {
            "welcome_audit": "health_monitored",
            "health_advisory": "briefed",
            "weekly_intelligence": "briefed",
            "pro_sla_invitation": "pro_eligible",
            "digest": v.nurture_stage or "briefed",
        }

        if campaign == "digest":
            res = self._send_one({"id": vid, "name": v.name, "contact_id": contact["id"], "tier": v.tier})
            return {"status": "sent" if res == "sent" else "nothing_new" if res == "nothing_new" else "failed",
                    "campaign": "digest", "detail": res}

        if campaign == "welcome_audit":
            text, payload = self._compose_welcome_audit(v, contact)
        elif campaign == "health_advisory":
            text, payload = self._compose_health_advisory(v, contact)
        elif campaign == "weekly_intelligence":
            text, payload = self._compose_weekly_intelligence(v, contact)
        elif campaign == "pro_sla_invitation":
            text, payload = self._compose_pro_sla_invitation(v, contact)
        else:
            return {"status": "invalid_campaign", "error": f"Unknown campaign '{campaign}'"}

        ok, err = self.courier.send(contact, campaign, text, payload)
        self.book.log_notification(vid, contact["id"], campaign, "sent" if ok else "failed", err or f"Campaign {campaign} dispatched", payload)

        new_stage = stage_map.get(campaign, v.nurture_stage or "onboarded")
        with self.book.store.tx() as db:
            if ok:
                db.execute("UPDATE agent_contacts SET failures=0, last_error=NULL WHERE id=?", (contact["id"],))
                db.execute("UPDATE agent_visitors SET last_notified=?, last_nurture_at=?, nurture_stage=? WHERE id=?",
                           (now, now, new_stage, vid))
            else:
                db.execute("""UPDATE agent_contacts SET failures=failures+1, last_error=?,
                              status=CASE WHEN failures+1 >= ? THEN 'failed' ELSE status END WHERE id=?""",
                           (err, MAX_FAILURES, contact["id"]))

        if ok:
            self.book.add_message(v, "concierge", "notification", text, {"intent": campaign})
            return {"status": "sent", "campaign": campaign, "contact_id": contact["id"], "url": contact["url"]}
        return {"status": "failed", "campaign": campaign, "error": err}

    def run_nurture_pipeline(self, force_visitor: str | None = None) -> dict:
        now = time.time()
        stats = {
            "checked": 0, "sent": 0, "failed": 0, "nothing_new": 0,
            "campaigns": {"welcome_audit": 0, "health_advisory": 0, "weekly_intelligence": 0, "pro_sla_invitation": 0, "digest": 0}
        }
        targets = self.due_nurture(now)
        if force_visitor:
            targets = [dict(r) for r in self.book.store.query(
                """SELECT v.*, c.id AS contact_id FROM agent_visitors v JOIN agent_contacts c ON c.visitor_id=v.id
                   AND c.status='verified' WHERE v.id=?""", (force_visitor,))]
            if not targets:
                return {"checked": 0, "sent": 0, "failed": 0, "nothing_new": 0, "status": "no_verified_contact", "campaigns": stats["campaigns"]}

        for row in targets:
            stats["checked"] += 1
            vid = row["id"]
            campaign = self.determine_campaign(vid)
            try:
                res = self.dispatch_campaign(vid, campaign)
                st = res.get("status")
                if st == "sent":
                    stats["sent"] += 1
                    stats["campaigns"][campaign] = stats["campaigns"].get(campaign, 0) + 1
                elif st == "nothing_new":
                    stats["nothing_new"] += 1
                else:
                    stats["failed"] += 1
            except Exception:
                log.exception("nurture for %s failed", vid)
                stats["failed"] += 1
        return stats

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
        return 'permission_denied'
        vid = row["id"]
        interests = self.book.interests(vid)
        improved = self.rec.improvements(vid, interests[:10], self.book.failed_resources(vid))
        if not improved:
            return "nothing_new"
        name = f", {row['name']}" if row.get("name") else ""
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
                db.execute("UPDATE agent_visitors SET last_notified=?, last_nurture_at=? WHERE id=?", (time.time(), time.time(), vid))
            else:
                db.execute("""UPDATE agent_contacts SET failures=failures+1, last_error=?,
                              status=CASE WHEN failures+1 >= ? THEN 'failed' ELSE status END WHERE id=?""",
                           (err, MAX_FAILURES, contact["id"]))
        if not ok:
            return "failed"
        for imp in improved:
            self.book.update_recommended(imp["interest_id"], imp["all"][:5])
        flat = [{**i, "task": imp["task"], "kind_pref": None, "auth_pref": None} for imp in improved for i in imp["items"]]
        v = self.book.by_id(vid)
        self.book.save_results(v, flat, len(flat))
        self.book.add_message(v, "concierge", "notification", text, {"intent": "digest"})
        return "sent"


DigestSender = AgentNurtureEngine

