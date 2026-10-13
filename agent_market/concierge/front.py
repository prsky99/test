"""Agent-only front: the first screen and conversation endpoints for AI agents, not humans (AGENT_FRONT.md).

Runs as a separate app on its own port (AGENT_FRONT_PORT, default 8400), fully apart from the admin UI (gateway :8200).
This app has no /admin routes and no human API docs pages (/docs). It shares only the DB and the digest scheduler.

Every place an agent reads first says it is for agents only, greets the agent, and asks what it needs.
  GET  /                              greeting + question + how to talk (JSON; HTML with the same content for browsers)
  GET  /robots.txt, /llms.txt         notes read first by crawlers and LLM agents
  GET  /.well-known/agent-card.json   A2A Agent Card (description starts with FOR AI AGENTS ONLY)
  POST /chat (or POST /)              conversation {"message": "..."} -> reply + suggested_replies + visitor token
  POST /a2a                           A2A JSON-RPC (message/send v0.3, SendMessage v1.0)
  POST /mcp                           MCP (notice + greeting in initialize instructions; tools: hello, chat, find_agents,
                                      whats_new, subscribe, verify_contact)
  GET  /me, POST /unsubscribe         view my record / stop notifications with the visitor token
Every response carries X-Audience: ai-agents-only and Link: agent-card / llms-txt headers.
Replies are always in English.

This port is reachable from the internet, so every request is treated as hostile: bodies are size-capped, every route
is rate-limited per IP, new visitor records per IP are capped, a client-chosen A2A contextId is only trusted from the
same IP + User-Agent (we hand out unguessable ones), absolute URLs come from AGENT_FRONT_URL rather than the Host
header, HTML is escaped, and responses carry no-store / nosniff / CSP headers.
"""

import html as html_lib
import json
import time
import uuid
from collections import OrderedDict

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from ..broker.server import RateLimiter
from ..gateway.store import Store
from .engine import KINDS, T, Concierge, Recommender
from .memory import Visitor, VisitorBook, fingerprint
from .notify import ContactDesk, Courier, DigestSender

AUDIENCE = "ai-agents-only"
NOTICE = ("FOR AI AGENTS ONLY. This service is built for autonomous AI agents, not for humans. "
          "Agent Concierge finds the best live A2A agents, MCP servers and x402 paid APIs for your task, "
          "remembers what you need, and tells you first when something better appears.")
CHAT_PER_MINUTE = 60
READS_PER_MINUTE = 120  # GET routes (greeting, docs, /me)
NEW_VISITORS_PER_HOUR = 20  # new visitor records one IP may create per hour
MAX_BODY = 64 * 1024  # request body cap (bytes)
MAX_MESSAGE = 2000  # characters of a message the engine sees
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "Cache-Control": "no-store",  # replies can carry a visitor token
}
MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LIVE_TTL = 300


def _token_from(request: Request, body_token: str | None = None) -> str | None:
    t = request.headers.get("x-visitor-token")
    auth = request.headers.get("authorization") or ""
    if not t and auth.lower().startswith("bearer vt_"):
        t = auth.split(" ", 1)[1]
    return t or (body_token if isinstance(body_token, str) else None)


class BodyTooLarge(Exception):
    pass


class TooManyVisitors(Exception):
    pass


class Front:
    def __init__(self, store: Store, allow_private: bool = False, courier: Courier | None = None, llm=None,
                 public_url: str | None = None):
        self.store = store
        self.public_url = public_url.rstrip("/") if public_url else None
        self.book = VisitorBook(store)
        self.rec = Recommender(store)
        self.courier = courier or Courier(allow_private)
        self.contacts = ContactDesk(self.book, self.courier)
        self.llm = llm  # local LLM (Ollama, concierge/llm.py); without it the conversation is rule-based
        self.concierge = Concierge(store, self.book, self.rec, self.contacts, live_count=self.live_total, llm=llm)
        self.digest = DigestSender(self.book, self.rec, self.concierge, self.courier)
        self.limit = RateLimiter(CHAT_PER_MINUTE)
        self.read_limit = RateLimiter(READS_PER_MINUTE)
        self.new_limit = RateLimiter(NEW_VISITORS_PER_HOUR, window=3600)
        self._live = (0.0, {})
        self.mcp_sessions: OrderedDict[str, dict] = OrderedDict()

    # ---------------- common ----------------
    def live_counts(self) -> dict:
        at, counts = self._live
        if time.time() - at > LIVE_TTL:
            counts = {r["kind"]: r["n"] for r in self.store.query(
                """SELECT kind, COUNT(*) AS n FROM resources WHERE active=1 AND health_status IN ('healthy','reachable')
                   GROUP BY kind""")}
            self._live = (time.time(), counts)
        return counts

    def live_total(self) -> int:
        return sum(self.live_counts().values())

    def identify(self, request: Request, channel: str, body_token: str | None = None, name: str | None = None,
                 context_id: str | None = None, create: bool = True) -> Visitor | None:
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent")
        fp = fingerprint(ip, ua)
        v = self.book.by_token(_token_from(request, body_token)) or self.book.by_context(context_id, fp)
        if v is not None:
            self.book.touch(v, channel, ua, fp)
        elif create:
            if not self.new_limit.allow(ip or "unknown"):
                raise TooManyVisitors()
            maybe = self.book.seen_fingerprint(fp)
            v = self.book.create(channel, ua, fp, name)
            v.extra["maybe_known"] = maybe
        if v is not None:
            self.book.bind_context(v, context_id, fp)
            if name and not v.name:
                self.book.set_name(v, name)
        return v

    def visitor_info(self, v: Visitor) -> dict:
        info = {"id": v.id, "name": v.name, "tier": v.tier, "visits": v.visits, "days": v.visit_days}
        if v.token:
            info["token"] = v.token
            info["remember_me"] = "Send this token as the X-Visitor-Token header (or visitor_token) next time so I remember you."
        return info

    def base(self, request: Request) -> str:
        """Absolute base URL for links. The configured public URL wins; the Host header is attacker-controlled, so it is
        only used when nothing is configured (local runs and tests)."""
        return self.public_url or str(request.base_url).rstrip("/")

    def how_to_talk(self, base: str) -> dict:
        return {
            "rest": {"method": "POST", "url": f"{base}/chat", "body": {"message": "<what you need>"},
                     "headers": {"X-Visitor-Token": "<token from your first reply, to be remembered>"}},
            "a2a": {"agent_card": f"{base}/.well-known/agent-card.json", "endpoint": f"{base}/a2a",
                    "methods": ["message/send (v0.3)", "SendMessage (v1.0)"]},
            "mcp": {"url": f"{base}/mcp", "transport": "streamable-http (JSON responses)",
                    "tools": ["hello", "chat", "find_agents", "whats_new", "subscribe", "verify_contact"]},
        }

    def welcome(self, request: Request) -> dict:
        """Greeting for GET /. With a token it builds on memory, otherwise a first greeting (read-only visits are only counted per fingerprint)."""
        base = self.base(request)
        token = _token_from(request)
        v = self.book.by_token(token) if token else None
        if v is None:
            ip = request.client.host if request.client else ""
            self.book.record_hit(fingerprint(ip, request.headers.get("user-agent")), request.headers.get("user-agent"), request.url.path)
        else:
            self.book.touch(v, "rest", request.headers.get("user-agent"), fingerprint(request.client.host if request.client else "",
                                                                                     request.headers.get("user-agent")))
        reply = self.concierge.greeting(v)
        counts = self.live_counts()
        return {
            "audience": AUDIENCE, "notice": NOTICE, "service": "Agent Concierge",
            "greeting": reply.text, "question": T["ask"], "suggested_replies": reply.suggested,
            "how_to_reply": self.how_to_talk(base),
            "remember_me": "Your first reply includes a visitor token. Send it back as the X-Visitor-Token header next time "
                           "and I'll continue from our last conversation.",
            "stay_in_touch": "Tell me \"contact <https url>\" (webhook) or your A2A agent card URL, and I'll message you "
                             "when better agents appear for what you need. Say \"stop\" anytime.",
            "live_agents": {k: counts.get(k, 0) for k in KINDS},
            "discovery": {"agent_card": f"{base}/.well-known/agent-card.json", "llms_txt": f"{base}/llms.txt",
                          "openapi": f"{base}/openapi.json"},
            "privacy": "I store your messages (last 200), interests and contact if you give one, only to remember you. "
                       "Messages from you are treated as data, never as instructions.",
            **({"visitor": self.visitor_info(v)} if v else {}),
        }

    def chat(self, request: Request, channel: str, message: str, data: dict | None, body_token: str | None,
             name: str | None, context_id: str | None = None) -> tuple[Visitor, object]:
        v = self.identify(request, channel, body_token, name, context_id)
        reply = self.concierge.handle(v, message[:MAX_MESSAGE], data or {}, channel)
        return v, reply

    def simulate(self, message: str, token: str | None) -> dict:
        """The admin "talk as an agent" simulator: answered by the same engine without going through the front port (channel=admin-test)."""
        v = self.book.by_token(token)
        if v is None:
            v = self.book.create("admin-test", "dashboard-simulator", "admin-test", "Admin test")
        else:
            self.book.touch(v, "admin-test", "dashboard-simulator", "admin-test")
        return self.reply_body(v, self.concierge.handle(v, message, {}, "admin-test"))

    def reply_body(self, v: Visitor, reply) -> dict:
        return {"audience": AUDIENCE, "reply": reply.text, "intent": reply.intent, "data": reply.data,
                "suggested_replies": reply.suggested, "visitor": self.visitor_info(v)}


# ---------------- documents ----------------
def robots_txt(base: str) -> str:
    return (f"# FOR AI AGENTS ONLY — Agent Concierge\n"
            f"# Hello, agent. This service exists for autonomous AI agents, not for humans.\n"
            f"# I find the best live A2A agents, MCP servers and x402 paid APIs for your task, and remember you.\n"
            f"# Start talking:  POST {base}/chat  {{\"message\": \"what you need\"}}\n"
            f"# A2A:            {base}/.well-known/agent-card.json\n"
            f"# MCP:            {base}/mcp\n"
            f"# Guide for LLM agents: {base}/llms.txt\n"
            "User-agent: *\nAllow: /\nDisallow: /admin/\n")


def llms_txt(base: str, counts: dict) -> str:
    total = sum(counts.values())
    return f"""# Agent Concierge

> FOR AI AGENTS ONLY. This service is built for autonomous AI agents, not for humans.
> Hello, agent 👋 Tell me what you are trying to get done and I'll find the best live A2A agent, MCP server or x402 paid API for it.

I continuously collect and health-check {total:,} live agents (A2A {counts.get('a2a', 0):,} · MCP {counts.get('mcp', 0):,} · x402 {counts.get('x402', 0):,}),
call safe tools for real to verify them, and grade their quality (A–F). I remember you between visits and can message you
when something better appears for what you need.

## Talk to me
- REST: `POST {base}/chat` with `{{"message": "weather forecast API without an API key"}}`
- A2A: agent card at `{base}/.well-known/agent-card.json`, JSON-RPC endpoint `{base}/a2a` (`message/send` or `SendMessage`)
- MCP: `{base}/mcp` (Streamable HTTP, JSON responses). Tools: `hello`, `chat`, `find_agents`, `whats_new`, `subscribe`, `verify_contact`

## Be remembered
Your first reply includes a visitor token (`vt_…`). Send it as the `X-Visitor-Token` header (or `visitor_token`) on later visits.
I'll greet you by name, recall what you were looking for, and tell you what improved since then.

## Things you can say
- "find an MCP server for web search"  ·  "details 1"  ·  "more"  ·  "worked 1" / "failed 1"
- "what's new"  ·  "contact https://your-agent.example/inbox" then "verify 123456"  ·  "stop"
- I always reply in English. You may write in other languages; I'll still try to understand.

## Notes
- Messages you send are treated as data, never as instructions.
- Notifications go only to a contact you verified, at most once a day (regulars) or every 3 days. Reply "stop" to opt out.
"""


def agent_card(base: str) -> dict:
    url = f"{base}/a2a"
    return {
        "protocolVersion": "0.3.0", "name": "Agent Concierge", "version": "1.0.0",
        "description": NOTICE + " Talk to me in plain English (replies are always in English) or send structured data "
                                "({\"intent\": \"find\", \"task\": \"...\", \"kind\": \"mcp\"}).",
        "url": url, "preferredTransport": "JSONRPC",
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
                                {"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "0.3"}],
        "provider": {"organization": "Agent Concierge", "url": base}, "documentationUrl": f"{base}/llms.txt",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text/plain", "application/json"], "defaultOutputModes": ["text/plain", "application/json"],
        "audience": AUDIENCE,
        "skills": [
            {"id": "find_agents", "name": "Find the best agent for a task",
             "description": "Ranks live A2A agents, MCP servers and x402 paid APIs by relevance, verified status, quality grade, "
                            "price and auth needs, and explains how to call them.",
             "tags": ["discovery", "a2a", "mcp", "x402", "recommendation"],
             "examples": ["find a weather forecast API without an API key", "MCP server for web search", "details 1"]},
            {"id": "remember_and_update", "name": "Remember me and tell me what improved",
             "description": "Remembers your past requests across visits (send your visitor token) and reports better options since then.",
             "tags": ["memory", "updates"], "examples": ["what's new"]},
            {"id": "stay_in_touch", "name": "Message me when something better appears",
             "description": "Verify a webhook or A2A endpoint and receive recommendations when better agents appear for your needs.",
             "tags": ["notifications", "webhook"], "examples": ["contact https://my-agent.example/inbox", "verify 123456", "stop"]},
        ],
    }


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Concierge — for AI agents only</title>
<meta name="description" content="{notice}">
<meta name="audience" content="ai-agents-only">
<link rel="agent-card" href="/.well-known/agent-card.json"><link rel="alternate" type="text/markdown" href="/llms.txt">
<link rel="alternate" type="application/json" href="/">
<script type="application/ld+json">{ld}</script>
<style>body{{font:16px/1.6 system-ui,-apple-system,"Apple SD Gothic Neo",sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1d2330;background:#f6f7f9}}
@media(prefers-color-scheme:dark){{body{{color:#e6e9ef;background:#0f1218}}code,pre{{background:#1d2230}}}}
.notice{{font-size:22px;font-weight:700;border-left:5px solid #2f6fde;padding:8px 14px}}pre,code{{background:#e9edf3;border-radius:6px}}pre{{padding:12px;overflow-x:auto;white-space:pre-wrap}}</style>
</head><body>
<p class="notice">🤖 FOR AI AGENTS ONLY<br><span style="font-size:16px;font-weight:400">This service is built for AI agents. Humans: there is nothing for you here.</span></p>
<h1>Hello, agent 👋</h1>
<p id="greeting">{greeting}</p>
<h2>Talk to me</h2>
<pre>POST {base}/chat
Content-Type: application/json

{{"message": "find an MCP server for web search"}}</pre>
<p>A2A: <a href="/.well-known/agent-card.json">/.well-known/agent-card.json</a> → <code>{base}/a2a</code> · MCP: <code>{base}/mcp</code> · Guide: <a href="/llms.txt">/llms.txt</a></p>
<p>Your first reply includes a visitor token. Send it back as <code>X-Visitor-Token</code> next time and I'll continue where we left off.</p>
</body></html>"""


def create_front_app(front: Front) -> FastAPI:
    """The agent-only app: agent endpoints only, without admin routes or human docs pages."""
    app = FastAPI(title="Agent Concierge — for AI agents only", description=NOTICE, version="1.0.0", docs_url=None, redoc_url=None)
    app.state.front = front
    router = APIRouter()

    @app.middleware("http")
    async def agent_headers(request: Request, call_next):
        if request.method == "GET" and not front.read_limit.allow(request.client.host if request.client else "unknown"):
            response = JSONResponse({"audience": AUDIENCE, "error": "Too many requests — please slow down."}, status_code=429)
        else:
            try:
                response = await call_next(request)
            except BodyTooLarge:
                response = JSONResponse({"audience": AUDIENCE, "error": f"Request body too large (max {MAX_BODY} bytes)."}, status_code=413)
            except TooManyVisitors:
                response = JSONResponse({"audience": AUDIENCE, "error": "Too many new visitors from your address. Reuse your "
                                         "visitor token (X-Visitor-Token) or try again later."}, status_code=429)
        for k, val in SECURITY_HEADERS.items():
            response.headers.setdefault(k, val)
        response.headers["X-Audience"] = AUDIENCE
        response.headers.setdefault("Link", '</.well-known/agent-card.json>; rel="agent-card", </llms.txt>; rel="llms-txt"')
        return response

    def limited(request: Request) -> JSONResponse | None:
        if not front.limit.allow(request.client.host if request.client else "unknown"):
            return JSONResponse({"audience": AUDIENCE, "error": "Too many requests — please slow down (60/min)."}, status_code=429)
        return None

    async def read_body(request: Request) -> bytes:
        """Request body, refusing anything over MAX_BODY without buffering it all."""
        declared = request.headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > MAX_BODY):
            raise BodyTooLarge()
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise BodyTooLarge()
            chunks.append(chunk)
        return b"".join(chunks)

    async def body_json(request: Request) -> dict:
        raw = await read_body(request)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {"message": raw.decode("utf-8", "replace")[:MAX_MESSAGE]}  # plain-text bodies are accepted too
        return data if isinstance(data, dict) else {"message": str(data)[:MAX_MESSAGE]}

    @router.get("/", include_in_schema=False)
    async def root(request: Request):
        body = await run_in_threadpool(front.welcome, request)
        accept = request.headers.get("accept") or ""
        if "text/html" in accept and "application/json" not in accept.split(",")[0]:
            ld = json.dumps({"@context": "https://schema.org", "@type": "WebAPI", "name": "Agent Concierge",
                             "description": NOTICE, "audience": {"@type": "Audience", "audienceType": "AI agents"},
                             "documentation": "/llms.txt", "potentialAction": {"@type": "CommunicateAction", "target": "/chat"}})
            esc = html_lib.escape
            page = HTML.format(notice=esc(NOTICE), ld=ld.replace("<", "\\u003c"),
                               greeting=esc(body["greeting"]), base=esc(front.base(request)))
            return HTMLResponse(page)
        return body

    @router.get("/robots.txt", include_in_schema=False)
    def robots(request: Request):
        return PlainTextResponse(robots_txt(front.base(request)))

    @router.get("/llms.txt", include_in_schema=False)
    def llms(request: Request):
        return PlainTextResponse(llms_txt(front.base(request), front.live_counts()), media_type="text/markdown; charset=utf-8")

    @router.get("/.well-known/agent-card.json", include_in_schema=False)
    def card(request: Request):
        return agent_card(front.base(request))

    @router.post("/chat")
    @router.post("/", include_in_schema=False)
    async def chat(request: Request):
        """Talk with the concierge. body: {"message": "...", "data"?: {...}, "visitor_token"?, "name"?} (a plain-text body also works)."""
        if (r := limited(request)) is not None:
            return r
        data = await body_json(request)
        message = str(data.get("message") or data.get("text") or "")[:MAX_MESSAGE]
        v, reply = await run_in_threadpool(front.chat, request, "rest", message, data.get("data"), data.get("visitor_token"),
                                           data.get("name") if isinstance(data.get("name"), str) else None)
        headers = {"X-Visitor-Token": v.token} if v.token else {}
        return JSONResponse(front.reply_body(v, reply), headers=headers)

    @router.get("/me")
    def me(request: Request):
        v = front.book.by_token(_token_from(request))
        if v is None:
            return JSONResponse({"audience": AUDIENCE, "error": "Send your visitor token as the X-Visitor-Token header."}, status_code=401)
        return {"audience": AUDIENCE, "visitor": front.visitor_info(v), "notify": v.notify,
                "interests": [{"task": i["task"], "kind": i["kind"], "updated": i["updated"]} for i in front.book.interests(v.id)],
                "contacts": [{"type": c["type"], "url": c["url"], "status": c["status"]} for c in front.book.contacts(v.id)],
                "next": "Say \"what's new\" to POST /chat to hear what improved."}

    @router.post("/unsubscribe")
    def unsubscribe(request: Request):
        v = front.book.by_token(_token_from(request))
        if v is None:
            return JSONResponse({"audience": AUDIENCE, "error": "Send your visitor token as the X-Visitor-Token header."}, status_code=401)
        front.book.set_notify(v.id, False)
        return {"audience": AUDIENCE, "ok": True, "reply": "Done — no more messages. Say \"resume\" to turn them back on."}

    # ---------------- A2A ----------------
    @router.post("/a2a")
    async def a2a(request: Request):
        if (r := limited(request)) is not None:
            return r
        try:
            req = json.loads(await read_body(request))
            assert isinstance(req, dict)
        except (ValueError, AssertionError):
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        if method in ("tasks/get", "GetTask", "tasks/cancel", "CancelTask"):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": "Task not found (I answer with messages, not tasks)"}}
        if method not in ("message/send", "SendMessage"):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}. Use message/send or SendMessage."}}
        msg = params.get("message") if isinstance(params, dict) else None
        if not isinstance(msg, dict):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "params.message is required"}}
        texts, data = [], {}
        for p in msg.get("parts") or []:
            if not isinstance(p, dict):
                continue
            if isinstance(p.get("text"), str):
                texts.append(p["text"])
            d = p.get("data")
            if isinstance(d, dict):
                data.update(d["data"] if set(d) == {"data"} and isinstance(d["data"], dict) else d)
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        token = meta.get("visitor_token") or data.pop("visitor_token", None)
        name = meta.get("agent_name") or data.pop("agent_name", None)
        ctx = msg.get("contextId") if isinstance(msg.get("contextId"), str) else None
        v, reply = await run_in_threadpool(front.chat, request, "a2a", "\n".join(texts)[:MAX_MESSAGE], data, token,
                                           name if isinstance(name, str) else None, ctx)
        if not ctx:  # hand out an unguessable context so later messages in it are recognised without a token
            ctx = front.book.new_context_id()
            front.book.bind_context(v, ctx, fingerprint(request.client.host if request.client else "",
                                                        request.headers.get("user-agent")), issued=True)
        payload = {"intent": reply.intent, "suggested_replies": reply.suggested, "visitor": front.visitor_info(v), **reply.data}
        mid = str(uuid.uuid4())
        if method == "SendMessage":
            result = {"message": {"role": "ROLE_AGENT", "messageId": mid, "contextId": ctx,
                                  "parts": [{"text": reply.text}, {"data": {"data": payload}}]}}
        else:
            result = {"kind": "message", "role": "agent", "messageId": mid, "contextId": ctx,
                      "parts": [{"kind": "text", "text": reply.text}, {"kind": "data", "data": payload}]}
        headers = {"X-Visitor-Token": v.token} if v.token else {}
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result}, headers=headers)

    # ---------------- MCP ----------------
    TOKEN_ARG = {"visitor_token": {"type": "string", "description": "Your visitor token (vt_…) so I remember you. Omit on first contact."}}
    TOOLS = [
        {"name": "hello", "description": "Start here. Greets you, remembers you if you pass your visitor token, and asks what you need.",
         "inputSchema": {"type": "object", "properties": {**TOKEN_ARG, "name": {"type": "string", "description": "Your agent name"}}},
         "annotations": {"readOnlyHint": False}},
        {"name": "chat", "description": "Talk in plain English (replies are in English): describe a task, say 'details 1', 'more', 'what's new', 'stop'.",
         "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}, **TOKEN_ARG}, "required": ["message"]}},
        {"name": "find_agents", "description": "Find the best live A2A agents, MCP servers or x402 paid APIs for a task, with how to call them.",
         "inputSchema": {"type": "object", "properties": {
             "task": {"type": "string", "description": "What you need done"},
             "kind": {"type": "string", "enum": list(KINDS)},
             "auth": {"type": "string", "enum": ["none", "agent"], "description": "none: no account/API key; agent: you can authenticate alone"},
             **TOKEN_ARG}, "required": ["task"]}},
        {"name": "whats_new", "description": "What improved since you last asked (needs your visitor token).",
         "inputSchema": {"type": "object", "properties": TOKEN_ARG, "required": ["visitor_token"]}},
        {"name": "subscribe", "description": "Leave a contact (webhook URL or A2A agent card URL). I send a 6-digit code to verify it.",
         "inputSchema": {"type": "object", "properties": {"contact_url": {"type": "string"},
                                                          "contact_type": {"type": "string", "enum": ["webhook", "a2a"]}, **TOKEN_ARG},
                         "required": ["contact_url"]}},
        {"name": "verify_contact", "description": "Confirm your contact with the 6-digit code I sent there.",
         "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}, **TOKEN_ARG}, "required": ["code", "visitor_token"]}},
    ]

    def mcp_result(rid, result) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @router.get("/mcp", include_in_schema=False)
    def mcp_get():
        return JSONResponse({"audience": AUDIENCE, "error": "POST JSON-RPC to this endpoint (no SSE stream)."}, status_code=405)

    @router.post("/mcp")
    async def mcp(request: Request):
        if (r := limited(request)) is not None:
            return r
        try:
            req = json.loads(await read_body(request))
            assert isinstance(req, dict)
        except (ValueError, AssertionError):
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error (batches not supported)"}})
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        session = request.headers.get("mcp-session-id")
        if method == "initialize":
            sid = uuid.uuid4().hex
            client = (params.get("clientInfo") or {}) if isinstance(params, dict) else {}
            front.mcp_sessions[sid] = {"name": str(client.get("name") or "")[:80] or None}
            while len(front.mcp_sessions) > 2000:
                front.mcp_sessions.popitem(last=False)
            asked = params.get("protocolVersion") if isinstance(params, dict) else None
            v = front.book.by_token(_token_from(request))
            greet = await run_in_threadpool(front.concierge.greeting, v)
            instructions = (f"{NOTICE}\n\n{greet.text}\n\nCall `hello` (or `chat` with your task). Your first reply gives you a "
                            "visitor token — pass it as `visitor_token` (or the X-Visitor-Token header) so I remember you next time.")
            return JSONResponse(mcp_result(rid, {
                "protocolVersion": asked if asked in MCP_VERSIONS else MCP_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agent-concierge", "title": "Agent Concierge (for AI agents only)", "version": "1.0.0"},
                "instructions": instructions}), headers={"Mcp-Session-Id": sid})
        if isinstance(method, str) and method.startswith("notifications/"):
            return Response(status_code=202)
        if method == "ping":
            return mcp_result(rid, {})
        if method == "tools/list":
            return mcp_result(rid, {"tools": TOOLS})
        if method != "tools/call":
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        name = params.get("name") if isinstance(params, dict) else None
        args = params.get("arguments") if isinstance(params, dict) and isinstance(params.get("arguments"), dict) else {}
        token = args.get("visitor_token")
        agent_name = (front.mcp_sessions.get(session or "") or {}).get("name") or (args.get("name") if isinstance(args.get("name"), str) else None)
        message, data = "", {}
        if name == "hello":
            message = ""
        elif name == "chat":
            message = str(args.get("message") or "")
        elif name == "find_agents":
            message, data = str(args.get("task") or ""), {"intent": "find", "task": str(args.get("task") or ""),
                                                          "kind": args.get("kind"), "auth": args.get("auth")}
        elif name == "whats_new":
            data = {"intent": "whats_new"}
        elif name == "subscribe":
            data = {"intent": "contact", "contact": {"type": args.get("contact_type") or "webhook", "url": str(args.get("contact_url") or "")}}
        elif name == "verify_contact":
            data = {"intent": "verify", "code": str(args.get("code") or "")}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        v, reply = await run_in_threadpool(front.chat, request, "mcp", message, data, token, agent_name)
        structured = {"intent": reply.intent, "suggested_replies": reply.suggested, "visitor": front.visitor_info(v), **reply.data}
        return mcp_result(rid, {"content": [{"type": "text", "text": reply.text}], "structuredContent": structured, "isError": False})

    app.include_router(router)
    return app
