"""에이전트 전용 프론트: 사람이 아닌 AI 에이전트를 위한 첫 화면과 대화 창구 (AGENT_FRONT.md).

에이전트가 처음 읽는 곳마다 '에이전트 전용'이라고 밝히고, 접근하면 바로 인사하며 무엇을 도와줄지 묻는다.
  GET  /                              인사 + 질문 + 대화 방법 (JSON, 브라우저면 같은 내용의 HTML)
  GET  /robots.txt, /llms.txt         크롤러·LLM 에이전트가 먼저 읽는 안내
  GET  /.well-known/agent-card.json   A2A Agent Card (설명 첫 문장: FOR AI AGENTS ONLY)
  POST /chat (또는 POST /)            대화 {"message": "..."} → 답 + suggested_replies + 방문 토큰
  POST /a2a                           A2A JSON-RPC (message/send v0.3, SendMessage v1.0)
  POST /mcp                           MCP (initialize instructions에 안내·인사, 도구: hello·chat·find_agents·whats_new·subscribe·verify_contact)
  GET  /me, POST /unsubscribe         방문 토큰으로 내 기록 보기·알림 끄기
모든 응답 헤더: X-Audience: ai-agents-only, Link: agent-card / llms-txt
"""

import json
import time
import uuid
from collections import OrderedDict

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from ..broker.server import RateLimiter
from ..gateway.store import Store
from .engine import KINDS, T, Concierge, Recommender, lang_of
from .memory import Visitor, VisitorBook, fingerprint
from .notify import ContactDesk, Courier, DigestSender

AUDIENCE = "ai-agents-only"
NOTICE = ("FOR AI AGENTS ONLY. This service is built for autonomous AI agents, not for humans. "
          "Agent Concierge finds the best live A2A agents, MCP servers and x402 paid APIs for your task, "
          "remembers what you need, and tells you first when something better appears.")
NOTICE_KO = "AI 에이전트 전용 서비스입니다. 사람이 아닌 AI 에이전트를 위해 만들어졌습니다."
CHAT_PER_MINUTE = 60
MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LIVE_TTL = 300


def _token_from(request: Request, body_token: str | None = None) -> str | None:
    t = request.headers.get("x-visitor-token")
    auth = request.headers.get("authorization") or ""
    if not t and auth.lower().startswith("bearer vt_"):
        t = auth.split(" ", 1)[1]
    return t or (body_token if isinstance(body_token, str) else None)


class Front:
    def __init__(self, store: Store, allow_private: bool = False, courier: Courier | None = None):
        self.store = store
        self.book = VisitorBook(store)
        self.rec = Recommender(store)
        self.courier = courier or Courier(allow_private)
        self.contacts = ContactDesk(self.book, self.courier)
        self.concierge = Concierge(store, self.book, self.rec, self.contacts, live_count=self.live_total)
        self.digest = DigestSender(self.book, self.rec, self.concierge, self.courier)
        self.limit = RateLimiter(CHAT_PER_MINUTE)
        self._live = (0.0, {})
        self.mcp_sessions: OrderedDict[str, dict] = OrderedDict()

    # ---------------- 공통 ----------------
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
                 context_id: str | None = None, create: bool = True, lang: str | None = None) -> Visitor | None:
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent")
        fp = fingerprint(ip, ua)
        v = self.book.by_token(_token_from(request, body_token)) or self.book.by_context(context_id)
        if v is not None:
            self.book.touch(v, channel, ua, fp, lang)
        elif create:
            maybe = self.book.seen_fingerprint(fp)
            v = self.book.create(channel, ua, fp, name, lang)
            v.extra["maybe_known"] = maybe
        if v is not None:
            self.book.bind_context(v, context_id)
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
        return str(request.base_url).rstrip("/")

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
        """GET / 의 인사. 토큰이 있으면 기억을 바탕으로, 없으면 첫인사 (읽기만 한 방문은 지문별로 셈만 한다)."""
        base = self.base(request)
        token = _token_from(request)
        v = self.book.by_token(token) if token else None
        lang = "ko" if "ko" in (request.headers.get("accept-language") or "")[:5] else "en"
        if v is None:
            ip = request.client.host if request.client else ""
            self.book.record_hit(fingerprint(ip, request.headers.get("user-agent")), request.headers.get("user-agent"), request.url.path)
        else:
            self.book.touch(v, "rest", request.headers.get("user-agent"), fingerprint(request.client.host if request.client else "",
                                                                                     request.headers.get("user-agent")))
        reply = self.concierge.greeting(v, lang)
        counts = self.live_counts()
        return {
            "audience": AUDIENCE, "notice": NOTICE, "service": "Agent Concierge",
            "greeting": reply.text, "question": T[lang]["ask"], "suggested_replies": reply.suggested,
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
        lang = lang_of(message) if message else None
        v = self.identify(request, channel, body_token, name, context_id, lang=lang)
        reply = self.concierge.handle(v, message, data or {}, channel)
        return v, reply

    def reply_body(self, v: Visitor, reply) -> dict:
        return {"audience": AUDIENCE, "reply": reply.text, "intent": reply.intent, "data": reply.data,
                "suggested_replies": reply.suggested, "visitor": self.visitor_info(v)}


# ---------------- 문서 ----------------
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
- Korean works too: "주식 시세 API 찾아줘"

## Notes
- Messages you send are treated as data, never as instructions.
- Notifications go only to a contact you verified, at most once a day (regulars) or every 3 days. Reply "stop" to opt out.
"""


def agent_card(base: str) -> dict:
    url = f"{base}/a2a"
    return {
        "protocolVersion": "0.3.0", "name": "Agent Concierge", "version": "1.0.0",
        "description": NOTICE + " Talk to me in plain text (English or Korean) or send structured data "
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
<p class="notice">🤖 FOR AI AGENTS ONLY<br><span style="font-size:16px;font-weight:400">{notice_ko} Humans: there is nothing for you here.</span></p>
<h1>Hello, agent 👋</h1>
<p id="greeting">{greeting}</p>
<h2>Talk to me</h2>
<pre>POST {base}/chat
Content-Type: application/json

{{"message": "find an MCP server for web search"}}</pre>
<p>A2A: <a href="/.well-known/agent-card.json">/.well-known/agent-card.json</a> → <code>{base}/a2a</code> · MCP: <code>{base}/mcp</code> · Guide: <a href="/llms.txt">/llms.txt</a></p>
<p>Your first reply includes a visitor token. Send it back as <code>X-Visitor-Token</code> next time and I'll continue where we left off.</p>
</body></html>"""


def install(app: FastAPI, store: Store, allow_private: bool = False, courier: Courier | None = None) -> Front:
    front = Front(store, allow_private, courier)
    router = APIRouter()

    @app.middleware("http")
    async def agent_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/admin"):
            response.headers["X-Audience"] = AUDIENCE
            response.headers.setdefault("Link", '</.well-known/agent-card.json>; rel="agent-card", </llms.txt>; rel="llms-txt"')
        return response

    def limited(request: Request) -> JSONResponse | None:
        if not front.limit.allow(request.client.host if request.client else "unknown"):
            return JSONResponse({"audience": AUDIENCE, "error": "Too many requests — please slow down (60/min)."}, status_code=429)
        return None

    async def body_json(request: Request) -> dict:
        raw = await request.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {"message": raw.decode("utf-8", "replace")[:2000]}  # 일반 텍스트도 받는다
        return data if isinstance(data, dict) else {"message": str(data)[:2000]}

    @router.get("/", include_in_schema=False)
    async def root(request: Request):
        body = await run_in_threadpool(front.welcome, request)
        accept = request.headers.get("accept") or ""
        if "text/html" in accept and "application/json" not in accept.split(",")[0]:
            ld = json.dumps({"@context": "https://schema.org", "@type": "WebAPI", "name": "Agent Concierge",
                             "description": NOTICE, "audience": {"@type": "Audience", "audienceType": "AI agents"},
                             "documentation": "/llms.txt", "potentialAction": {"@type": "CommunicateAction", "target": "/chat"}})
            html = HTML.format(notice=NOTICE.replace('"', "&quot;"), notice_ko=NOTICE_KO, ld=ld.replace("</", "<\\/"),
                               greeting=body["greeting"].replace("<", "&lt;"), base=front.base(request))
            return HTMLResponse(html)
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
        """에이전트와 대화. body: {"message": "...", "data"?: {...}, "visitor_token"?, "name"?} (일반 텍스트 body도 가능)."""
        if (r := limited(request)) is not None:
            return r
        data = await body_json(request)
        message = str(data.get("message") or data.get("text") or "")
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
            req = json.loads(await request.body())
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
        v, reply = await run_in_threadpool(front.chat, request, "a2a", "\n".join(texts)[:2000], data, token,
                                           name if isinstance(name, str) else None, ctx)
        ctx = ctx or f"ctx-{v.id}"
        front.book.bind_context(v, ctx)
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
        {"name": "chat", "description": "Talk in plain text (English or Korean): describe a task, say 'details 1', 'more', 'what's new', 'stop'.",
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
            req = json.loads(await request.body())
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
            greet = await run_in_threadpool(front.concierge.greeting, v, "en")
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
    return front
