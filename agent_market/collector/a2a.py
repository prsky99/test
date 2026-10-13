"""A2A(Agent2Agent) 에이전트 조사: agent card를 읽어 기능·인증·사용법을 정리하고, 살아 있는지와 실제 응답을 확인한다.

A2A v1.0(supportedInterfaces, PascalCase 메서드)과 아직 널리 쓰이는 v0.3(url·preferredTransport, message/send)을 모두 다룬다.
1. agent card: /.well-known/agent-card.json (v0.3 이전은 /.well-known/agent.json)
2. 인증: card의 securitySchemes·security(Requirements). OAuth 메타데이터·OIDC 설정이 있으면 읽어
   에이전트 혼자 토큰을 받을 수 있는지(client_credentials + 자동 등록) 판단. 자격 증명은 보내지 않는다.
3. 살아 있는지: 없는 작업 ID로 GetTask(tasks/get)를 보내 JSON-RPC 오류(-32001 TaskNotFound)가 오면 정상.
   에이전트에게 일을 시키지 않는 가장 가벼운 확인. 401/403이면 인증 필요.
4. 실제 사용 검증: 인증이 필요 없을 때만, 일을 저지르지 않는 안전한 메시지 하나를 보낸다
   (card의 스킬 예시 중 구매·전송·삭제 같은 행동이 없는 것, 없으면 "무엇을 도와줄 수 있는지" 질문).
   작업이 끝나지 않고 남으면 바로 취소한다.
"""

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from ..broker.discovery import DiscoveryError, check_public_url
from ..gateway import constraints as cons
from ..gateway.store import Store
from . import evaluation, usage
from .auth_discovery import compact, instructions

log = logging.getLogger("agent_market.collector.a2a")

USER_AGENT = "agent-collector/0.1 (+A2A agent survey; no credentials or payments are sent)"
MAX_CARD = 512 * 1024
CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")
SAMPLE_CHARS = 500
TERMINAL = {"completed", "failed", "canceled", "cancelled", "rejected", "input-required", "auth-required"}
GENERIC_PROMPT = "Hello! In one or two sentences, what can you help with?"
# 에이전트에게 보내는 메시지는 '행동'을 시킬 수 있으므로 MCP 도구보다 보수적으로 고른다
_ACTION = re.compile(
    r"\b(buy|sell|order|purchase|pay|payment|checkout|charge|transfer|send|wire|withdraw|deposit|book|reserve|cancel|"
    r"delete|remove|post|publish|tweet|email|e-mail|sms|text me|call me|dial|trade|swap|mint|stake|bridge|bet|deploy|"
    r"execute|run|sign|approve|register|sign up|subscribe|unsubscribe|invite|apply|submit|upload|vote|claim|redeem|"
    r"hire|schedule|create (an )?account|reset|update my|change my)\b", re.I)
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d|\b0x[a-fA-F0-9]{40}\b")


def card_candidates(url: str, declared: str | None = None) -> list[str]:
    """선언된 주소가 card 자체(.json)면 그대로, 아니면 그 경로·도메인 루트의 well-known 위치들."""
    out = [declared] if declared else []
    p = urlparse(url)
    if p.path.endswith(".json"):
        out.append(url)
    else:
        base = url.rstrip("/")
        origin = f"{p.scheme}://{p.netloc}"
        for path in CARD_PATHS:
            out.append(base + path)
            if base != origin:
                out.append(origin + path)
    return list(dict.fromkeys(u for u in out if u))


def _scopes(v) -> list[str]:
    if isinstance(v, dict):
        return [str(k) for k in v][:20]
    if isinstance(v, list):
        return [str(k) for k in v][:20]
    return []


def _flows(flows) -> dict:
    out = {}
    for name, f in (flows or {}).items() if isinstance(flows, dict) else []:
        if not isinstance(f, dict):
            continue
        key = {"client_credentials": "clientCredentials", "authorization_code": "authorizationCode",
               "device_code": "deviceCode"}.get(name, name)
        out[key] = {k: f.get(k) for k in ("tokenUrl", "authorizationUrl", "deviceAuthorizationUrl", "refreshUrl") if f.get(k)}
        out[key]["scopes"] = _scopes(f.get("scopes"))
        if f.get("pkceRequired"):
            out[key]["pkceRequired"] = True
    return out


def _scheme(s: dict) -> dict | None:
    """v1.0(apiKeySecurityScheme …)과 v0.3(OpenAPI 형식 type: apiKey …)을 같은 모양으로."""
    if not isinstance(s, dict):
        return None
    if "apiKeySecurityScheme" in s:
        a = s["apiKeySecurityScheme"] or {}
        return {"type": "apiKey", "location": a.get("location"), "name": a.get("name"), "description": a.get("description")}
    if "httpAuthSecurityScheme" in s:
        a = s["httpAuthSecurityScheme"] or {}
        return {"type": "http", "scheme": str(a.get("scheme") or "").lower(), "bearerFormat": a.get("bearerFormat"),
                "description": a.get("description")}
    if "oauth2SecurityScheme" in s:
        a = s["oauth2SecurityScheme"] or {}
        return {"type": "oauth2", "flows": _flows(a.get("flows")), "metadata_url": a.get("oauth2MetadataUrl"),
                "description": a.get("description")}
    if "openIdConnectSecurityScheme" in s:
        a = s["openIdConnectSecurityScheme"] or {}
        return {"type": "openIdConnect", "openid_url": a.get("openIdConnectUrl"), "description": a.get("description")}
    if "mtlsSecurityScheme" in s:
        return {"type": "mutualTLS", "description": (s["mtlsSecurityScheme"] or {}).get("description")}
    t = str(s.get("type") or "")
    if t == "apiKey":
        return {"type": "apiKey", "location": s.get("in"), "name": s.get("name"), "description": s.get("description")}
    if t == "http":
        return {"type": "http", "scheme": str(s.get("scheme") or "").lower(), "bearerFormat": s.get("bearerFormat"),
                "description": s.get("description")}
    if t == "oauth2":
        return {"type": "oauth2", "flows": _flows(s.get("flows")), "metadata_url": s.get("oauth2MetadataUrl"),
                "description": s.get("description")}
    if t == "openIdConnect":
        return {"type": "openIdConnect", "openid_url": s.get("openIdConnectUrl"), "description": s.get("description")}
    if t in ("mutualTLS", "mtls"):
        return {"type": "mutualTLS", "description": s.get("description")}
    return {"type": t or "unknown", "description": s.get("description")}


def _requirements(raw) -> list[list[str]]:
    """security(v0.3: [{"name": [scopes]}]) / securityRequirements(v1.0: [{"schemes": {"name": {...}}}]) → [[scheme 이름]]"""
    out = []
    for entry in raw or [] if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        names = entry["schemes"] if isinstance(entry.get("schemes"), dict) else entry
        out.append([str(k) for k in names])
    return [r for r in out if r]


def _text_list(v, limit=10, size=300) -> list[str]:
    return [str(x)[:size] for x in v[:limit]] if isinstance(v, list) else []


def _binding(value) -> str:
    """protocolBinding/transport 이름 정리: 'jsonrpc 2.0'·'HTTP'·'REST' 같은 변형과 MCP 인터페이스."""
    b = str(value or "JSONRPC").strip().upper()
    if "MODELCONTEXTPROTOCOL" in b or b.startswith("MCP") or "STREAMABLE" in b or b == "SSE":
        return "MCP"
    if b.replace("-", "").replace(" ", "").startswith("JSONRPC"):
        return "JSONRPC"
    if b in ("HTTP", "REST", "HTTP+JSON", "HTTP/JSON", "HTTPJSON", "JSON"):
        return "HTTP+JSON"
    return b


def normalize_card(raw, card_url: str) -> dict | None:
    """agent card → 정리본. A2A card가 아니면 None (같은 경로에 다른 형식의 JSON을 두는 곳이 많다)."""
    if not isinstance(raw, dict) or not raw.get("name") or not isinstance(raw.get("skills"), list):
        return None
    if not (raw.get("supportedInterfaces") or raw.get("url") or isinstance(raw.get("capabilities"), dict)):
        return None
    interfaces, mcp = [], []
    for i in raw.get("supportedInterfaces") or [] if isinstance(raw.get("supportedInterfaces"), list) else []:
        if isinstance(i, dict) and i.get("url"):
            binding = _binding(i.get("protocolBinding"))
            if binding == "MCP":  # A2A card에 MCP 인터페이스를 함께 적는 곳이 많다 → MCP 수집으로 넘김
                mcp.append(str(i["url"])[:500])
                continue
            interfaces.append({"url": str(i["url"]), "binding": binding, "version": str(i.get("protocolVersion") or "1.0")})
    spec = "1.0" if interfaces else str(raw.get("protocolVersion") or "0.3")
    if not interfaces and raw.get("url"):
        interfaces.append({"url": str(raw["url"]), "binding": _binding(raw.get("preferredTransport")), "version": spec})
        for i in raw.get("additionalInterfaces") or [] if isinstance(raw.get("additionalInterfaces"), list) else []:
            if isinstance(i, dict) and i.get("url") and i.get("url") != raw["url"]:
                binding = _binding(i.get("transport"))
                if binding == "MCP":
                    mcp.append(str(i["url"])[:500])
                else:
                    interfaces.append({"url": str(i["url"]), "binding": binding, "version": spec})
    skills = []
    for s in raw["skills"][:50]:
        if not isinstance(s, dict):
            continue
        skills.append({
            "name": str(s.get("id") or s.get("name") or "")[:100],  # diff/평가가 'name'을 키로 쓰므로 스킬 id를 넣는다
            "title": str(s.get("name") or "")[:200],
            "description": str(s.get("description") or "")[:1000],
            "tags": _text_list(s.get("tags"), 15, 60),
            "examples": _text_list(s.get("examples"), 5, 300),
            "input_modes": _text_list(s.get("inputModes"), 10, 80),
            "output_modes": _text_list(s.get("outputModes"), 10, 80),
            "params": {},
        })
    declared = raw.get("securitySchemes") if isinstance(raw.get("securitySchemes"), dict) else {}  # 목록으로 주는 card도 있다
    schemes = {str(k): v for k, v in ((k, _scheme(s)) for k, s in declared.items()) if v}
    caps = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
    provider = raw.get("provider") if isinstance(raw.get("provider"), dict) else {}
    extensions = [str(e.get("uri"))[:200] for e in caps.get("extensions") or [] if isinstance(e, dict) and e.get("uri")]
    return {
        "card_url": card_url,
        "name": str(raw["name"])[:200],
        "description": str(raw.get("description") or "")[:2000],
        "version": str(raw.get("version") or "")[:50],
        "spec_version": spec,
        "interfaces": interfaces[:5],
        "mcp_interfaces": [u for u in dict.fromkeys(mcp) if u.startswith("https://")][:3],
        "provider": {"organization": str(provider.get("organization") or "")[:200] or None,
                     "url": str(provider.get("url") or "")[:300] or None},
        "documentation_url": raw.get("documentationUrl"),
        "icon_url": raw.get("iconUrl"),
        "capabilities": {k: bool(caps.get(k)) for k in ("streaming", "pushNotifications", "stateTransitionHistory",
                                                       "extendedAgentCard") if k in caps},
        "extensions": extensions[:10],
        "payment": "x402" if any("x402" in e.lower() for e in extensions) else None,
        "default_input_modes": _text_list(raw.get("defaultInputModes"), 10, 80),
        "default_output_modes": _text_list(raw.get("defaultOutputModes"), 10, 80),
        "skills": skills,
        "security_schemes": schemes,
        "security": _requirements(raw.get("securityRequirements") or raw.get("security")),
        "signed": bool(raw.get("signatures")),
        "extended_card": bool(raw.get("supportsAuthenticatedExtendedCard") or caps.get("extendedAgentCard")),
    }


FALLBACK_PATHS = ("/a2a", "/a2a/v1", "/api/a2a", "/a2a/jsonrpc")


def endpoint(card: dict) -> dict | None:
    """호출할 인터페이스: JSON-RPC 우선, 없으면 HTTP+JSON(REST). gRPC만 있으면 None.
    선언된 주소가 A2A로 응답하지 않아 다른 주소를 찾았으면(endpoint_override) 그것을 쓴다."""
    if card.get("endpoint_override"):
        return card["endpoint_override"]
    for binding in ("JSONRPC", "HTTP+JSON", "REST"):
        for i in card["interfaces"]:
            if i["binding"] == binding and i["url"].startswith(("https://", "http://")):
                return i
    return None


def card_hash(card: dict) -> str:
    keep = {k: card.get(k) for k in ("name", "description", "version", "spec_version", "interfaces", "skills",
                                     "security_schemes", "security", "default_input_modes", "default_output_modes")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()


# ---------------- 인증 ----------------

def classify_card_auth(card: dict, observed_status: int | None, oauth_meta: dict | None = None) -> tuple[str, str, dict]:
    """card의 보안 선언과 실제 응답으로 (method, autonomy, info). info는 MCP 인증 조사와 같은 모양."""
    schemes = card["security_schemes"]
    required_names = [n for req in card["security"] for n in req if n in schemes] or list(schemes)
    observed_auth = observed_status in (401, 403)
    info: dict = {"http_status": observed_status, "scope": "connection", "schemes": compact(schemes, 10, 300),
                  "website": card["provider"].get("url") or card.get("documentation_url")}
    if not schemes and not observed_auth:
        info["instructions"] = ["No authentication needed: send A2A requests directly."]
        return "none", "none_needed", info
    if not card["security"] and not observed_auth and observed_status is not None and observed_status < 400:
        # 방식만 선언하고 요구하지 않음 + 인증 없이 응답함 → 실제로는 인증 불필요
        info["instructions"] = ["Security schemes are declared but not required; requests without credentials are accepted."]
        return "none", "none_needed", info
    primary = schemes.get(required_names[0]) if required_names else None
    if primary is None:
        info["instructions"] = ["Authentication is required (HTTP 401/403) but the agent card declares no scheme; "
                                "check the provider's documentation."]
        return "unknown", "unknown", info
    t = primary["type"]
    if t in ("oauth2", "openIdConnect"):
        flows = primary.get("flows") or {}
        meta = oauth_meta or {}
        grants = set(meta.get("grant_types_supported") or [])
        if "clientCredentials" in flows:
            grants.add("client_credentials")
        if "authorizationCode" in flows:
            grants.add("authorization_code")
        if "deviceCode" in flows:
            grants.add("urn:ietf:params:oauth:grant-type:device_code")
        flow = flows.get("clientCredentials") or flows.get("authorizationCode") or flows.get("deviceCode") or {}
        info["oauth"] = {
            "authorization_server_metadata": primary.get("metadata_url") or primary.get("openid_url"),
            "token_endpoint": meta.get("token_endpoint") or flow.get("tokenUrl"),
            "authorization_endpoint": meta.get("authorization_endpoint") or (flows.get("authorizationCode") or {}).get("authorizationUrl"),
            "device_authorization_endpoint": meta.get("device_authorization_endpoint")
                                              or (flows.get("deviceCode") or {}).get("deviceAuthorizationUrl"),
            "registration_endpoint": meta.get("registration_endpoint"),
            "client_id_metadata_document_supported": meta.get("client_id_metadata_document_supported"),
            "grant_types_supported": sorted(grants) or ["authorization_code"],
            "code_challenge_methods_supported": meta.get("code_challenge_methods_supported"),
            "scopes": flow.get("scopes") or meta.get("scopes_supported"),
        }
        can_register = bool(meta.get("registration_endpoint") or meta.get("client_id_metadata_document_supported"))
        autonomy = "agent_autonomous" if "client_credentials" in grants and can_register else "human_once"
        method = "oauth2"
    elif t == "apiKey":
        method, autonomy = "api_key", "human_once"
        info["api_key"] = {"header": primary.get("name") if primary.get("location") in (None, "header") else None,
                           "query_param": primary.get("location") == "query", "cookie": primary.get("location") == "cookie",
                           "param_name": primary.get("name"), "description": primary.get("description"),
                           "where_to_get": [u for u in (card["provider"].get("url"), card.get("documentation_url")) if u]}
    elif t == "http":
        method = "basic" if primary.get("scheme") == "basic" else "bearer"
        autonomy = "human_once"
        info["api_key"] = {"header": "Authorization", "description": primary.get("description"),
                           "where_to_get": [u for u in (card["provider"].get("url"), card.get("documentation_url")) if u]}
    elif t == "mutualTLS":
        method, autonomy = "mtls", "human_once"
    else:
        method, autonomy = "unknown", "unknown"
    if method == "mtls":
        info["instructions"] = ["Mutual TLS: obtain a client certificate from the provider and present it on every connection."]
    else:
        info["instructions"] = instructions(method, info, protocol="A2A")
    if card.get("extended_card"):
        info["instructions"].append("After authenticating, fetch the extended agent card (GetExtendedAgentCard / "
                                    "agent/getAuthenticatedExtendedCard) for the full skill list.")
    return method, autonomy, compact(info)


# ---------------- JSON-RPC ----------------

_PAYMENT = re.compile(r"payment required|x402|insufficient (funds|credit)|\b402\b|pay(ment)? (is )?needed|requires? payment", re.I)


def _v1(card: dict) -> bool:
    """메서드 형식: card가 선언한 버전, 실제 서버가 다른 형식으로 응답하면(method_style) 그것을 따른다."""
    style = card.get("method_style")
    return style == "1.0" if style else card["spec_version"].startswith("1")


def _methods(card: dict) -> dict:
    if _v1(card):
        return {"send": "SendMessage", "get": "GetTask", "cancel": "CancelTask"}
    return {"send": "message/send", "get": "tasks/get", "cancel": "tasks/cancel"}


def _headers(card: dict) -> dict:
    h = {"content-type": "application/json", "accept": "application/json, text/event-stream", "user-agent": USER_AGENT}
    if _v1(card):
        h["A2A-Version"] = "1.0"
    return h


def is_payment_error(text: str | None) -> bool:
    return bool(text and _PAYMENT.search(text))


def _parse(resp: httpx.Response) -> dict | None:
    text = resp.text[:MAX_CARD]
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:])
                except ValueError:
                    continue
                if isinstance(data, dict) and ("result" in data or "error" in data):
                    return data
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def message_request(card: dict, text: str, request_id: int = 1) -> dict:
    """사용 안내와 시험 호출에 쓰는 메시지 전송 요청 (버전별 형식)."""
    mid = str(uuid.uuid4())
    if _v1(card):
        return {"jsonrpc": "2.0", "id": request_id, "method": "SendMessage",
                "params": {"message": {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": mid},
                           "configuration": {"acceptedOutputModes": ["text/plain"], "returnImmediately": False}}}
    return {"jsonrpc": "2.0", "id": request_id, "method": "message/send",
            "params": {"message": {"kind": "message", "role": "user", "parts": [{"kind": "text", "text": text}], "messageId": mid},
                       "configuration": {"acceptedOutputModes": ["text/plain", "text"], "blocking": True}}}


def _parts_text(parts) -> str:
    out = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        if p.get("text") is not None:
            out.append(str(p["text"]))
        elif p.get("data") is not None:
            out.append(json.dumps(p["data"], ensure_ascii=False)[:SAMPLE_CHARS])
        elif p.get("file") or p.get("url") or p.get("raw"):
            out.append("[file]")
    return "\n".join(out)


def response_summary(result) -> dict:
    """SendMessage 결과(Message 또는 Task, v1은 {"task"|"message": …})에서 상태와 답변 텍스트."""
    if not isinstance(result, dict):
        return {"state": None, "text": str(result)[:SAMPLE_CHARS] if result else ""}
    obj = result.get("task") or result.get("message") or result
    if "status" in obj or obj.get("kind") == "task" or "artifacts" in obj:
        status = obj.get("status") if isinstance(obj.get("status"), dict) else {}
        state = str(status.get("state") or "").lower().replace("task_state_", "").replace("_", "-") or None
        texts = [_parts_text(a.get("parts")) for a in obj.get("artifacts") or [] if isinstance(a, dict)]
        if isinstance(status.get("message"), dict):
            texts.append(_parts_text(status["message"].get("parts")))
        if not any(texts):
            texts = [_parts_text(m.get("parts")) for m in (obj.get("history") or [])[-1:] if isinstance(m, dict)
                     and str(m.get("role", "")).lower() in ("agent", "role_agent")]
        return {"state": state, "task_id": obj.get("id"), "text": "\n".join(t for t in texts if t)[:SAMPLE_CHARS]}
    return {"state": "completed", "text": _parts_text(obj.get("parts"))[:SAMPLE_CHARS]}


def pick_message(card: dict) -> tuple[str | None, str] | None:
    """보낼 메시지: 행동을 시키지 않는 스킬 예시 → 없으면 일반 질문. 텍스트 입력을 받지 않으면 None."""
    modes = card["default_input_modes"] or ["text/plain"]
    if not any("text" in m for m in modes):
        return None
    for s in card["skills"]:
        if s["input_modes"] and not any("text" in m for m in s["input_modes"]):
            continue
        if _ACTION.search(" ".join([s["name"], s["title"], " ".join(s["tags"])])):
            continue
        for ex in s["examples"]:
            if 3 <= len(ex) <= 300 and not _ACTION.search(ex) and not _PII.search(ex) and not ex.strip().startswith(("{", "[")):
                return s["name"], ex
    return None, GENERIC_PROMPT


def build_guide(card: dict, auth: dict, trial: dict | None, changes: dict | None, live: dict | None) -> dict:
    """요청한 에이전트에게 줄 사용 안내 (영어)."""
    ep = endpoint(card)
    skills = []
    for s in card["skills"][:usage.MAX_TOOLS_IN_GUIDE]:
        example = next((e for e in s["examples"] if e), None) or f"<a request for the '{s['title'] or s['name']}' skill>"
        skills.append({"id": s["name"], "name": s["title"], "description": s["description"][:300], "tags": s["tags"],
                       "examples": s["examples"][:3], "example_request": message_request(card, example)})
    steps = [f"1) Fetch the agent card: GET {card['card_url']}"]
    if ep:
        auth_hint = " with your credentials (see auth)" if auth.get("method") not in (None, "none") else ""
        steps.append(f"2) POST a JSON-RPC '{_methods(card)['send']}' request to {ep['url']}{auth_hint}"
                     + (" with header 'A2A-Version: 1.0'" if _v1(card) else "") + ".")
        if card.get("method_style") and card["method_style"][0] != card["spec_version"][0]:
            steps.append(f"Note: the card declares A2A {card['spec_version']} but the server answers "
                         f"{card['method_style']}-style methods; use the method names above.")
        steps.append(f"3) If the result is a Task that is not finished, poll '{_methods(card)['get']}' with the task id"
                     + (" or use streaming." if card["capabilities"].get("streaming") else "."))
    else:
        steps.append("2) The agent exposes only gRPC; use an A2A gRPC client.")
    guide = {
        "protocol": "A2A", "spec_version": card["spec_version"], "agent_card": card["card_url"],
        "endpoint": ep["url"] if ep else None, "binding": ep["binding"] if ep else None,
        "interfaces": card["interfaces"], "methods": _methods(card),
        "capabilities": card["capabilities"], "input_modes": card["default_input_modes"], "output_modes": card["default_output_modes"],
        "auth": {"method": auth.get("method"), "autonomy": auth.get("autonomy"), "steps": auth.get("instructions")},
        "payment": card.get("payment") or ("required" if (trial or {}).get("payment_required") else None),
        "extensions": card["extensions"],
        "skills": skills, "skill_count": len(card["skills"]), "steps": steps,
        "provider": card["provider"], "documentation": card.get("documentation_url"),
        "endpoint_check": live,
    }
    if trial and trial.get("ok"):
        guide["verified_example"] = {"skill": trial.get("skill"), "message": trial.get("message"),
                                     "response_state": trial.get("state"), "response_sample": trial.get("sample_output"),
                                     "latency_ms": trial.get("latency_ms"), "verified_at": trial.get("at")}
    if changes and any(changes.values()):
        guide["recent_changes"] = changes
    return guide


class AgentProber:
    """A2A 에이전트를 하루 한 번 조사: card → 인증 → 엔드포인트 확인 → (안전한 메시지 1개) → 사용 안내 → 평가."""

    def __init__(self, store: Store, http: httpx.Client | None = None, allow_private: bool = False,
                 max_age: float = 86400, workers: int = 8, per_host_delay: float = 1.0,
                 trial_max_age: float = 7 * 86400, trials: bool = True):
        self.store = store
        self._fixed_http = http
        self.allow_private = allow_private
        self.max_age = max_age
        self.workers = workers
        self.per_host_delay = per_host_delay
        self.trial_max_age = trial_max_age
        self.trials = trials
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()

    def requeue_outdated_evaluations(self) -> int:
        """A2A 평가 규칙(evaluation.AGENT_VERSION)이 바뀌면 조사했던 에이전트를 다시 조사 대상으로."""
        if self.store.get_meta("agent_evaluation_version") == evaluation.AGENT_VERSION:
            return 0
        with self.store.tx() as db:
            n = db.execute("UPDATE resources SET cap_checked_at=NULL WHERE kind='a2a' AND cap_checked_at IS NOT NULL").rowcount
        self.store.set_meta("agent_evaluation_version", evaluation.AGENT_VERSION)
        return n

    def _check(self, url: str) -> None:
        if not self.allow_private:
            check_public_url(url)

    def _get_json(self, http: httpx.Client, url: str, cache: bool = False) -> tuple[int | None, dict | None, str | None]:
        if cache:
            with self._lock:
                hit = self._cache.get(url)
                if hit and time.time() - hit[0] < 3600:
                    return 200, hit[1], None
        try:
            self._check(url)
            resp = http.get(url, headers={"accept": "application/json", "user-agent": USER_AGENT})
        except (httpx.HTTPError, DiscoveryError) as exc:
            return None, None, f"{type(exc).__name__}: {exc}"[:200]
        data = None
        if resp.status_code == 200 and len(resp.content) <= MAX_CARD:
            try:
                parsed = resp.json()
                data = parsed if isinstance(parsed, dict) else None
            except ValueError:
                data = None
        if cache:
            with self._lock:
                self._cache[url] = (time.time(), data)
        return resp.status_code, data, resp.headers.get("content-type")

    def fetch_card(self, http: httpx.Client, resource: dict) -> tuple[dict | None, dict, str | None]:
        details = json.loads(resource.get("details") or "{}")
        meta = {"tried": []}
        for url in card_candidates(resource["url"], details.get("agent_card"))[:4]:
            status, data, ctype = self._get_json(http, url)
            meta["tried"].append({"url": url, "status": status})
            if data is not None:
                card = normalize_card(data, url)
                if card:
                    meta.update(content_type=ctype, size=len(json.dumps(data)), raw_keys=sorted(data)[:40],
                                well_known=url.endswith(CARD_PATHS[0]))
                    return card, meta, None
                meta["not_a2a"] = True
        return None, meta, "no valid A2A agent card" + (" (JSON found but not an A2A card)" if meta.get("not_a2a") else "")

    def check_endpoint(self, http: httpx.Client, card: dict) -> dict:
        """선언된 엔드포인트를 확인하고, A2A로 응답하지 않으면(홈페이지 주소를 적은 card가 많다) 흔한 경로 몇 개를 더 본다.
        메서드가 없다(-32601)고 하면 다른 버전의 메서드 이름(v0.3 tasks/get ↔ v1.0 GetTask)으로 한 번 더 확인한다."""
        live = self._check_one(http, card, endpoint(card))
        if live.get("jsonrpc_error") == -32601:
            card["method_style"] = "0.3" if _v1(card) else "1.0"
            other = self._check_one(http, card, endpoint(card))
            if other.get("ok") and other.get("jsonrpc_error") != -32601:
                return {**other, "method_style": card["method_style"]}
            card.pop("method_style")
        ep = endpoint(card)
        if live.get("ok") is False and ep and ep["binding"] == "JSONRPC" and live.get("status") in (200, 301, 302, 307, 308, 404, 405):
            p = urlparse(ep["url"])
            origin = f"{p.scheme}://{p.netloc}"
            card_dir = card["card_url"].split("/.well-known/")[0]
            for alt in dict.fromkeys([card_dir + "/a2a"] + [origin + path for path in FALLBACK_PATHS]):
                if alt.rstrip("/") == ep["url"].rstrip("/"):
                    continue
                candidate = {**ep, "url": alt}
                probe = self._check_one(http, card, candidate)
                if probe.get("ok"):
                    card["endpoint_override"] = candidate
                    return {**probe, "declared_endpoint": ep["url"], "declared_error": live.get("error"), "endpoint": alt}
        return live

    def _check_one(self, http: httpx.Client, card: dict, ep: dict | None) -> dict:
        """없는 작업을 조회해 엔드포인트가 A2A로 응답하는지 확인 (에이전트에게 일을 시키지 않음)."""
        if ep is None:
            return {"ok": None, "error": "no JSON-RPC or HTTP+JSON interface"}
        probe_id = f"collector-probe-{uuid.uuid4()}"
        started = time.monotonic()
        try:
            self._check(ep["url"])
            if ep["binding"] == "JSONRPC":
                resp = http.post(ep["url"], json={"jsonrpc": "2.0", "id": 1, "method": _methods(card)["get"],
                                                  "params": {"id": probe_id}}, headers=_headers(card))
            else:
                resp = http.get(ep["url"].rstrip("/") + f"/tasks/{probe_id}", headers=_headers(card))
        except (httpx.HTTPError, DiscoveryError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        out = {"status": resp.status_code, "latency_ms": int((time.monotonic() - started) * 1000), "binding": ep["binding"]}
        if resp.status_code in (401, 403):
            return {**out, "ok": True, "auth": True}
        if ep["binding"] != "JSONRPC":
            return {**out, "ok": resp.status_code in (200, 400, 404), "auth": False}
        data = _parse(resp)
        if data is None:
            return {**out, "ok": False, "error": f"not a JSON-RPC response (HTTP {resp.status_code})"}
        err = data.get("error") if isinstance(data.get("error"), dict) else None
        code = err.get("code") if err else None
        out.update(ok=True, auth=False, jsonrpc_error=code)
        if code in (-32001, -32602, -32601):  # TaskNotFound(정상) / 잘못된 파라미터·메서드(살아 있음)
            out["conformant"] = code == -32001
        elif err and re.search(r"auth|unauthori|token|credential|api.?key", str(err.get("message")), re.I):
            out["auth"] = True
        else:
            out["conformant"] = False
        return out

    def trial(self, http: httpx.Client, card: dict, picked: tuple[str | None, str]) -> dict:
        skill, text = picked
        ep = endpoint(card)
        out = {"skill": skill, "message": text, "at": time.time()}
        if ep is None or ep["binding"] != "JSONRPC":
            return {**out, "ok": False, "error": "trial supports JSON-RPC interfaces only", "skipped": True}
        started = time.monotonic()
        try:
            resp = http.post(ep["url"], json=message_request(card, text), headers=_headers(card),
                             timeout=httpx.Timeout(45.0, connect=5.0))
            data = _parse(resp) or {}
            err = data.get("error")
            if isinstance(err, dict) and err.get("code") == -32601 and not card.get("method_style"):
                card["method_style"] = "0.3" if _v1(card) else "1.0"  # 선언과 다른 버전의 메서드 이름으로 한 번 더
                resp = http.post(ep["url"], json=message_request(card, text), headers=_headers(card),
                                 timeout=httpx.Timeout(45.0, connect=5.0))
                data = _parse(resp) or {}
                if isinstance(data.get("error"), dict) and data["error"].get("code") == -32601:
                    card.pop("method_style")
            if resp.status_code == 402:
                out.update(ok=False, payment_required=True, error="Payment required (HTTP 402)")
            elif data.get("error"):
                err = data["error"]
                out.update(ok=False, error=str(err.get("message") if isinstance(err, dict) else err)[:300])
                if is_payment_error(out["error"]):
                    out["payment_required"] = True
            elif "result" in data:
                summary = response_summary(data["result"])
                out.update(state=summary["state"], sample_output=summary["text"] or None,
                           output_chars=len(json.dumps(data["result"], ensure_ascii=False)))
                out["ok"] = bool(summary["text"]) and summary["state"] not in ("failed", "rejected", "auth-required",
                                                                                "payment-required")
                if not out["ok"]:
                    out["error"] = f"task {summary['state'] or 'returned no text'}"
                    if summary["state"] == "payment-required" or is_payment_error(summary["text"]):
                        out["payment_required"] = True
                if summary.get("task_id") and summary["state"] not in TERMINAL:  # 남은 작업은 정리
                    try:
                        http.post(ep["url"], json={"jsonrpc": "2.0", "id": 2, "method": _methods(card)["cancel"],
                                                   "params": {"id": summary["task_id"]}}, headers=_headers(card))
                        out["canceled"] = True
                    except httpx.HTTPError:
                        pass
            else:
                out.update(ok=False, error=f"no JSON-RPC result (HTTP {resp.status_code})")
        except httpx.HTTPError as exc:
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        return out

    def _oauth_meta(self, http: httpx.Client, card: dict) -> dict | None:
        for s in card["security_schemes"].values():
            url = s.get("metadata_url") or s.get("openid_url")
            if url:
                status, data, _ = self._get_json(http, url, cache=True)
                if data and data.get("token_endpoint"):
                    return data
        return None

    def _domain_verified(self, http: httpx.Client, resource: dict, card: dict) -> bool | None:
        """ERC-8004에 등록된 에이전트: 엔드포인트 도메인의 /.well-known/agent-registration.json이 같은 등록을 가리키는지."""
        regs = json.loads(resource.get("details") or "{}").get("erc8004") or []
        if not regs:
            return None
        p = urlparse(card["card_url"])
        status, data, _ = self._get_json(http, f"{p.scheme}://{p.netloc}/.well-known/agent-registration.json", cache=True)
        if not data:
            return False
        listed = {(str(r.get("agentRegistry", "")).lower(), str(r.get("agentId"))) for r in data.get("registrations") or []
                  if isinstance(r, dict)}
        return any((str(r.get("registry", "")).lower(), str(r.get("agent_id"))) in listed for r in regs)

    def survey(self, resource: dict, http: httpx.Client) -> dict:
        card, meta, err = self.fetch_card(http, resource)
        if card is None:
            raise ValueError(err)
        live = self.check_endpoint(http, card)
        method, autonomy, auth_info = classify_card_auth(card, live.get("status") if live.get("ok") is not None else None,
                                                         self._oauth_meta(http, card) if card["security_schemes"] else None)
        auth_required = method not in ("none",) or bool(live.get("auth"))
        trial = None
        if self.trials and not auth_required and live.get("ok"):
            last = json.loads(resource.get("trial_info") or "null") or {}
            # 실패한 시험은 하루 뒤 다시 (일시 오류·버전 불일치 수정 반영), 성공했으면 trial_max_age(기본 7일)마다
            stale = not last or time.time() - last.get("at", 0) > (self.trial_max_age if last.get("ok") else 86400 - 3600)
            if stale or card_hash(card) != resource.get("usage_tools_hash"):
                picked = pick_message(card)
                if picked:
                    trial = self.trial(http, card, picked)
        verified = self._domain_verified(http, resource, card)
        return {"card": card, "meta": meta, "live": live, "auth": {"method": method, "autonomy": autonomy, "info": auth_info},
                "auth_required": auth_required, "trial": trial, "domain_verified": verified}

    def _record(self, r: dict, s: dict) -> dict:
        card = s["card"]
        digest = card_hash(card)
        old = json.loads(r.get("usage_tools") or "null")
        changes = usage.diff_tools(old, card["skills"]) if old is not None and r.get("usage_tools_hash") != digest else None
        text = " ".join([card["description"]] + [f"{k['title']} {k['description']} {' '.join(k['tags'])}" for k in card["skills"]])
        langs = sorted({cons.detect_language(text)} - {None}) if text.strip() else []
        caps = {"languages": langs, "regions": sorted(cons.regions_in_text(text))[:10], "currencies": [],
                "tool_count": len(card["skills"]), "tool_names": [k["name"] for k in card["skills"]][:50]}
        self.store.record_capability(r["id"], caps)
        for url in card["mcp_interfaces"]:  # card에 적힌 MCP 인터페이스 → MCP 수집 대상으로 (이미 알면 건너뜀)
            if not self.store.query("SELECT 1 FROM resources WHERE url=? LIMIT 1", (url,)):
                self.store.upsert_resource({
                    "key": f"a2a-card-mcp:{url}", "source": "a2a-card", "kind": "mcp", "url": url, "name": card["name"],
                    "description": card["description"], "category": r.get("category") or "other", "networks": [],
                    "price_usdc": 0, "details": {"remotes": [{"type": "streamable-http", "url": url}],
                                                 "agent_card": card["card_url"]}})
        self.store.record_auth(r["id"], s["auth"])
        self.store.set_auth_observed(r["id"], s["auth_required"])
        trial = s["trial"]
        last_trial = trial or json.loads(r.get("trial_info") or "null")
        guide = build_guide(card, {"method": s["auth"]["method"], "autonomy": s["auth"]["autonomy"],
                                   "instructions": s["auth"]["info"].get("instructions")}, last_trial, changes, s["live"])
        guide["updated_at"] = time.time()
        changed = self.store.record_usage(r["id"], card["skills"], digest, guide, changes, trial)
        fresh = self.store.resource(r["id"]) or r
        ev = evaluation.evaluate_agent(fresh, card, s["meta"], s["live"], last_trial if not s["auth_required"] else None,
                                       changes, s["domain_verified"])
        ev["percentile"] = self.store.score_percentile(ev["score"], kind="a2a")
        self.store.record_evaluation(r["id"], ev)
        return {"changed": changed and old is not None, "trial": trial, "grade": ev["grade"], "security": ev["security"]}

    def run_due(self, limit: int = 100) -> dict:
        due = self.store.due_for_capability(time.time(), self.max_age, limit, kind="a2a")
        if not due:
            return {"checked": 0}
        by_host: dict[str, list[dict]] = defaultdict(list)
        for r in due:
            by_host[r.get("host") or r["url"]].append(r)
        http = self._fixed_http or httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0, pool=30.0), follow_redirects=False)
        results, lock = [], threading.Lock()

        def work(resources: list[dict]) -> None:
            for i, r in enumerate(resources):
                if i:
                    time.sleep(self.per_host_delay)
                try:
                    s, err = self.survey(r, http), None
                except (httpx.PoolTimeout, httpx.ProxyError):
                    s, err = None, "local"
                except Exception as exc:  # 비표준 card 등: 이 에이전트만 실패로 기록
                    s, err = None, f"{type(exc).__name__}: {exc}"[:300]
                with lock:
                    results.append((r, s, err))

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(work, by_host.values()))
        finally:
            if http is not self._fixed_http:
                http.close()
        failed = sum(1 for _, s, _ in results if s is None)
        outage = len(results) >= 20 and failed / len(results) >= 0.8
        stats = defaultdict(int)
        for r, s, err in results:
            if s is None and (outage or err == "local"):
                stats["postponed"] += 1
                continue
            if s is None:
                self.store.record_capability(r["id"], None, err)
                stats["failed"] += 1
                continue
            try:
                out = self._record(r, s)
            except Exception as exc:
                log.warning("a2a record error for %s: %r", r["url"], exc)
                stats["record_error"] += 1
                continue
            stats["ok"] += 1
            stats[f"grade_{out['grade']}"] += 1
            stats["auth_required" if s["auth_required"] else "open"] += 1
            if out["trial"]:
                stats["trial_ok" if out["trial"].get("ok") else "trial_failed"] += 1
            stats["usage_changed"] += int(out["changed"])
        return {"checked": len(results), "local_network_problem": outage, **stats}
