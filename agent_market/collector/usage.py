"""MCP 사용 안내 만들기: 도구 목록을 정리하고, 안전한 도구 하나를 실제로 호출해 본 뒤
연결 방법·도구별 사용법·검증된 예제를 담은 안내(guide)를 만든다.

안전 원칙 (남의 서버에서 실제로 실행하므로)
- 서버가 destructiveHint=true로 표시한 도구는 절대 호출하지 않는다.
- readOnlyHint=true로 표시된 도구, 또는 표시가 없으면 이름·설명이 조회형(get/search/list/...)이고
  쓰기·전송·결제·삭제 성격(send/create/delete/pay/...)이 전혀 없는 도구만 호출한다.
- 이메일·전화·비밀번호·키·카드 같은 값을 요구하는 도구는 호출하지 않는다.
- 필수 인자를 자신 있게 채울 수 없으면 호출하지 않는다 (안내에는 자리표시자 예제만).
- 결과는 앞부분 500자만 보관한다.
"""

import hashlib
import json
import re
from datetime import date

MAX_TOOLS_IN_GUIDE = 15
SAMPLE_CHARS = 500

_DENY = re.compile(
    r"(send|create|delete|remove|destroy|drop|update|upsert|patch|post|publish|buy|sell|order|purchase|pay|payment|charge|"
    r"transfer|withdraw|deposit|write|submit|book|reserve|cancel|register|signup|sign_up|deploy|execute|exec|run_|shell|"
    r"command|insert|upload|mint|swap|trade|approve|sign|email|mail|sms|message|tweet|reply|comment|invite|subscribe|"
    r"reset|set_|edit|modify|move|rename|archive|merge|commit|push|close|open_|start|stop|kill|restart|grant|revoke|"
    r"follow|like|vote|claim|redeem|bid|stake|bridge|fund|refund|notify|call_phone|dial|schedule)", re.I)
_ALLOW = re.compile(
    r"^(get|search|list|lookup|look_up|fetch|read|query|find|describe|check|info|status|ping|health|version|resolve|"
    r"convert|calculate|calc|validate|explain|analy[sz]e|summar|count|compare|estimate|quote|price|weather|forecast|"
    r"define|translate|detect|parse|show|view|browse|discover|recommend|suggest|score|rate_?check|whois|geocode)", re.I)
_PII_PARAM = re.compile(r"(email|e_mail|phone|mobile|password|passwd|secret|token|api_?key|apikey|private|card|cvv|ssn|"
                        r"iban|account_?number|otp|pin|cookie|session)", re.I)


def compact_tools(tools: list[dict]) -> list[dict]:
    """저장·비교용으로 도구 정의를 줄인다 (이름, 설명, 파라미터, 주석)."""
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}  # 비표준 서버 방어
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        out.append({
            "name": str(t["name"])[:100],
            "description": str(t.get("description") or "")[:400],
            "required": [str(r) for r in (schema.get("required") if isinstance(schema.get("required"), list) else [])][:20],
            "params": {
                str(k): {key: v[key] for key in ("type", "description", "enum", "default", "examples", "minimum", "format")
                         if isinstance(v, dict) and key in v}
                for k, v in list(props.items())[:25]
            },
            "annotations": {k: v for k, v in (t.get("annotations") if isinstance(t.get("annotations"), dict) else {}).items()
                            if k in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint", "title")},
        })
    for t in out:  # 긴 enum·설명 정리
        for p in t["params"].values():
            if isinstance(p.get("enum"), list):
                p["enum"] = p["enum"][:15]
            if isinstance(p.get("description"), str):
                p["description"] = p["description"][:200]
    return out


def tools_hash(tools: list[dict]) -> str:
    return hashlib.sha1(json.dumps(tools, sort_keys=True, default=str).encode()).hexdigest()


def diff_tools(old: list[dict] | None, new: list[dict]) -> dict:
    old_map = {t["name"]: t for t in old or []}
    new_map = {t["name"]: t for t in new}
    return {
        "added": sorted(set(new_map) - set(old_map)),
        "removed": sorted(set(old_map) - set(new_map)),
        "changed": sorted(n for n in set(new_map) & set(old_map) if old_map[n] != new_map[n]),
    }


def is_safe_tool(tool: dict) -> bool:
    ann = tool.get("annotations") or {}
    if ann.get("destructiveHint") is True:
        return False
    if any(_PII_PARAM.search(p) for p in tool.get("required") or []):
        return False
    if ann.get("readOnlyHint") is True:
        return True
    name, desc = tool["name"], tool.get("description") or ""
    if _DENY.search(name) or _DENY.search(desc[:200]):
        return False
    return bool(_ALLOW.search(name.replace("-", "_").split("__")[-1]))


def _example_value(name: str, spec: dict, category: str | None):
    if "enum" in spec and spec["enum"]:
        return spec["enum"][0]
    if spec.get("default") is not None:
        return spec["default"]
    if isinstance(spec.get("examples"), list) and spec["examples"]:
        return spec["examples"][0]
    key, typ = name.lower(), spec.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), None)
    if typ in ("integer", "number"):
        if re.search(r"(limit|count|max|top|size|num|per_page|results|^n$)", key):
            return 1
        return spec.get("minimum", 1)
    if typ == "boolean":
        return False
    if typ not in (None, "string"):
        return None  # 배열·객체는 자신 있게 채울 수 없음
    if re.search(r"(url|link|website|uri)$", key):
        return "https://example.com"
    if re.search(r"domain|hostname|host$", key):
        return "example.com"
    if re.search(r"(city|location|place|address_city)", key):
        return "Seoul"
    if re.search(r"country", key):
        return "US"
    if re.search(r"(symbol|ticker)", key):
        return "BTC" if category == "finance_crypto" else "AAPL"
    if re.search(r"(coin|token_id|asset)", key):
        return "bitcoin"
    if re.search(r"(lang|locale)", key):
        return "en"
    if re.search(r"currency", key):
        return "USD"
    if re.search(r"date", key) or spec.get("format") == "date":
        return date.today().isoformat()
    if re.search(r"(query|^q$|search|keyword|term|text|topic|prompt|question|input|name|title|word)", key):
        return {"finance_crypto": "bitcoin", "travel_maps_weather": "Seoul", "media_generation": "a lighthouse at sunset",
                "dev_tools": "model context protocol", "public_legal": "data protection"}.get(category, "model context protocol")
    return None  # id 같은 값은 지어낼 수 없음


def example_arguments(tool: dict, category: str | None = None) -> dict | None:
    """필수 인자를 채운 예제 인자. 하나라도 못 채우면 None (안내에는 자리표시자를 씀)."""
    args = {}
    for name in tool.get("required") or []:
        value = _example_value(name, tool["params"].get(name, {}), category)
        if value is None:
            return None
        args[name] = value
    for name, spec in tool["params"].items():  # 결과를 작게: limit 류는 1로
        if name not in args and re.search(r"^(limit|max_results|num_results|count|top_k|per_page)$", name.lower()) \
                and spec.get("type") in ("integer", "number"):
            args[name] = 1
    return args


def placeholder_arguments(tool: dict) -> dict:
    return {name: f"<{tool['params'].get(name, {}).get('type', 'value')}>" for name in tool.get("required") or []}


def pick_trial(tools: list[dict], category: str | None = None) -> tuple[dict, dict] | None:
    """실제로 호출해 볼 도구 하나: 안전하고 인자를 채울 수 있는 것 중 필수 인자가 가장 적은 것."""
    candidates = []
    for t in tools:
        if not is_safe_tool(t):
            continue
        args = example_arguments(t, category)
        if args is not None:
            explicit = (t.get("annotations") or {}).get("readOnlyHint") is True
            candidates.append((0 if explicit else 1, len(t.get("required") or []), t["name"], t, args))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[:3])
    return candidates[0][3], candidates[0][4]


_AUTH_ERROR = re.compile(r"(unauthori[sz]ed|authenticat|sign[ -]?in|log[ -]?in|api[ _-]?key|access token|bearer|\b401\b|"
                         r"forbidden|not authorized|missing token|invalid token|link your .* account|connect your .* account)", re.I)


def is_auth_error(text: str | None) -> bool:
    return bool(text and _AUTH_ERROR.search(text))


def result_text(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:SAMPLE_CHARS]
    parts = []
    for item in (result or {}).get("content") or []:
        if isinstance(item, dict):
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(f"[{item.get('type')} content]")
    if not parts and (result or {}).get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(parts)[:SAMPLE_CHARS]


def jsonrpc_call(name: str, arguments: dict, request_id: int = 3) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def build_guide(url: str, transport: str, protocol_version: str | None, tools: list[dict], category: str | None,
                trial: dict | None, changes: dict | None, server_info: dict | None, instructions: str | None) -> dict:
    """요청한 에이전트에게 줄 사용 안내 (영어: 에이전트 간 공용어)."""
    entries = []
    trial_name = (trial or {}).get("tool")
    ordered = sorted(tools, key=lambda t: (t["name"] != trial_name, t["name"]))[:MAX_TOOLS_IN_GUIDE]
    for t in ordered:
        args = example_arguments(t, category)
        verified = None
        if trial and t["name"] == trial_name:
            args = trial["arguments"]
            verified = {k: trial.get(k) for k in ("ok", "at", "latency_ms", "sample_output", "error")}
        entries.append({
            "name": t["name"],
            "description": t["description"][:300],
            "read_only": (t.get("annotations") or {}).get("readOnlyHint"),
            "params": [{"name": n, "type": p.get("type"), "required": n in (t.get("required") or []),
                        **({"enum": p["enum"]} if p.get("enum") else {}),
                        **({"description": p["description"]} if p.get("description") else {})}
                       for n, p in list(t["params"].items())[:12]],
            "example_request": jsonrpc_call(t["name"], args if args is not None else placeholder_arguments(t)),
            "verified": verified,
        })
    pv = protocol_version or "2025-06-18"
    return {
        "endpoint": url,
        "transport": transport,
        "protocol_version": pv,
        "server": {k: (server_info or {}).get(k) for k in ("name", "version")} if server_info else None,
        "server_instructions": (instructions or "")[:800] or None,
        "how_to_connect": [
            f"POST {url} with headers 'Content-Type: application/json' and 'Accept: application/json, text/event-stream'.",
            f"1) initialize: {{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{{\"protocolVersion\":\"{pv}\","
            "\"capabilities\":{},\"clientInfo\":{\"name\":\"your-agent\",\"version\":\"1.0\"}}}",
            "2) If the response has an 'Mcp-Session-Id' header, send it (and 'MCP-Protocol-Version') on every later request.",
            "3) notifications/initialized: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}",
            "4) tools/call with one of the example requests below. Responses may be JSON or Server-Sent Events (read the 'data:' line).",
            "5) When done, DELETE the endpoint with the Mcp-Session-Id header to close the session.",
        ],
        "tool_count": len(tools),
        "tools": entries,
        "verified_example": next((e for e in entries if (e["verified"] or {}).get("ok")), None),
        "changes": changes if changes and any(changes.values()) else None,
    }
