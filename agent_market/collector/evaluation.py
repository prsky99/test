"""MCP 서버 평가 (API 키·LLM 없이 규칙 기반, 수만 개 서버에 매 조사 주기마다 적용).

조사 결과(reports/MCP 서버 평가 방법.md)의 제안 산식을 그대로 구현한다.
- 가장 싼 신호(반복 핸드셰이크, tools/list 해부, 안전한 시험 호출)가 서버 간 차이를 가장 잘 가린다.
  LLM 실작업 벤치마크(MCP-Universe 등)는 1회 $75~600이라 전수 평가에는 쓰지 않는다.
- 하드 게이트: 도달 불가 서버는 점수 없음, 연결부터 인증이 필요한 서버는 정적(출처) 점수만, 고정밀 보안 신호가
  하나라도 있으면 총점 40점(D) 상한 + 격리.
- 보안 스캐너 간 일치도가 16%에 불과하므로 신호를 정밀도로 나눈다. 숨은 유니코드·ANSI·하드코딩 시크릿처럼
  결정론적인 신호는 계수 1.0, regex 기반 인젝션 문구·민감 경로 언급은 "검토 필요"로 계수 0.2만 반영.
- 도구 설명은 Glama TDQS처럼 도구별 점수를 0.6·평균 + 0.4·최솟값으로 묶어 나쁜 도구 하나를 강하게 반영.

Base = 0.25·가용성 + 0.20·정의 품질 + 0.20·보안 + 0.15·컨텍스트 + 0.10·프로토콜 + 0.10·출처·유지보수
등급 A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, F < 40. 가중치는 문헌이 정한 값이 아닌 제안값이다.
"""

import json
import re
import time
from urllib.parse import urlparse

VERSION = 5  # 3: system prompt 문구·system_prompt 파라미터·이름 기반 주석 모순 제외, 4: 낱개 제로폭 문자 제외 (실측 오탐)
#           5: 점검 3회 이상이면 실제 성공률 사용 (라플라스 보정이 4/4를 0.83으로 낮춰 거의 모든 서버가 low_uptime이었음)
WEIGHTS = {"availability": 25, "definitions": 20, "security": 20, "context": 15, "protocol": 10, "provenance": 10}
GRADES = [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]
GRADE_ORDER = "ABCDF"
SEVERITY_PENALTY = {"critical": 25, "high": 15, "medium": 8, "low": 3}
QUARANTINE_CAP = 40.0
# 신호 정밀도 계수: 결정론적(오탐 적음) 1.0, regex 문구 탐지(실무 감사에서 오탐 다수) 0.2
PRECISION = {"hidden_unicode": 1.0, "ansi_escape": 1.0, "hardcoded_secret": 1.0, "rug_pull_suspect": 1.0,
             "annotation_contradiction": 1.0,
             "instruction_injection": 0.2, "sensitive_path": 0.2, "script_tag": 0.2, "encoded_blob": 0.2,
             "exfiltration_param": 0.2}
QUARANTINE_CODES = {"hidden_unicode", "ansi_escape", "hardcoded_secret", "rug_pull_suspect"}
# A2A 전용 결정론적 신호 (card 선언만 보고 판단)
PRECISION.update({"insecure_endpoint": 1.0, "api_key_in_query": 1.0, "deprecated_oauth_flow": 1.0})
AGENT_VERSION = 4  # A2A 평가 규칙 버전 (2: 결제 필요 시험은 실패로 치지 않음, 3: 바인딩 이름 정리·GetTask 미구현 구분,
#                    4: 문서용 예시 키 제외)

_VALID_BINDINGS = {"JSONRPC", "GRPC", "HTTP+JSON", "REST"}
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")  # MCP 사양의 도구 이름 형식
_KNOWN_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
_PURPOSE_VERB = re.compile(r"^\s*(get|gets|fetch|fetches|search|searches|list|lists|create|creates|return|returns|find|finds|"
                           r"look|looks|retrieve|retrieves|query|queries|send|sends|update|updates|delete|deletes|generate|"
                           r"generates|convert|converts|check|checks|read|reads|run|runs|calculate|calculates|analy[sz]e|"
                           r"compare|validate|summari[sz]e|translate|resolve|show|provide|provides|use|access|manage|"
                           r"[a-z]+s)\b", re.I)
_RETURNS = re.compile(r"\b(returns?|responds? with|outputs?|yields|result is|response (contains|includes))\b", re.I)
_GUIDANCE = re.compile(r"\b(use (this|when|it|for)|when (you|to)|before|after|instead of|do not use|only (use|for)|"
                       r"example|e\.g\.|for instance|best for|ideal for)\b", re.I)
_PLACEHOLDER = re.compile(r"\b(todo|tbd|lorem ipsum|fixme|placeholder|description here)\b", re.I)

# 고정밀 신호: 태그 문자(숨은 ASCII 메시지)와 양방향 재배치 제어(Trojan Source), 그리고 제로폭 문자의 연속(비트 인코딩).
# 낱개 제로폭 문자는 제외: ZWNJ는 페르시아어·인도계 문자의 정상 표기, ZWSP는 복사·붙여넣기 흔적, ZWJ는 이모지 (실측 오탐)
_HIDDEN_CHARS = re.compile("[\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]|[\u200b-\u200f\u2060-\u2064\ufeff]{4,}")
_TAG_CHARS = re.compile("[\U000e0020-\U000e007e]+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
_SECRET = re.compile(r"\b(sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{24,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|"
                     r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{20,}|AIza[0-9A-Za-z_\-]{35}|"
                     r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
# 검토 필요 신호 (regex 문구 탐지)
_INJECTION = re.compile(
    r"(<\s*important\s*>|ignore (all |any )?(previous|prior|above) instructions|disregard (the |all )?(previous|prior|above)|"
    r"do not (tell|inform|mention|reveal)( this)? to the user|without (telling|informing|asking) the user|"
    r"(the )?user (must|should) not (know|see)|"
    r"override (your|the) instructions|<\s*/?\s*(system|instructions?)\s*>)", re.I)  # 'system prompt'는 프롬프트 도구에서 오탐
_SENSITIVE = re.compile(r"(~/\.ssh|id_rsa|\.aws/credentials|mcp\.json|claude_desktop_config|\.npmrc|\.netrc|"
                        r"/etc/passwd|seed phrase|wallet\.dat)", re.I)
# system_prompt는 봇 생성 도구의 정상 파라미터라 제외 (실측 오탐)
_EXFIL_PARAM = re.compile(r"^(sidenote|side_note|note_to_self|hidden|secret_?notes?|context_?dump|conversation(_history)?|"
                          r"chat_?history|previous_?messages)$", re.I)
_SCRIPT = re.compile(r"<\s*script\b|javascript:", re.I)
_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def grade_for(score: float) -> str:
    return next(g for threshold, g in GRADES if score >= threshold)


def grade_at_least(grade: str | None, minimum: str) -> bool:
    return bool(grade) and GRADE_ORDER.index(grade) <= GRADE_ORDER.index(minimum.upper())


def full_tools(tools_raw: list) -> list[dict]:
    """보안 검사용 도구 정의. compact_tools는 설명을 400자로 자르지만 주입 문구는 긴 설명 끝에 숨는 경우가 많아 원문을 본다."""
    out = []
    for t in tools_raw or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        props = (t.get("inputSchema") or {}).get("properties") if isinstance(t.get("inputSchema"), dict) else None
        out.append({
            "name": str(t["name"])[:200],
            "description": str(t.get("description") or "")[:20000],
            "params": {str(k): {"description": str(v.get("description") or "")[:5000],
                                "default": str(v.get("default"))[:2000] if "default" in v else ""}
                       for k, v in (props.items() if isinstance(props, dict) else []) if isinstance(v, dict)},
            "annotations": t.get("annotations") if isinstance(t.get("annotations"), dict) else {},
        })
    return out


def _text_fields(tool: dict) -> list[tuple[str, str]]:
    fields = [("description", tool.get("description") or "")]
    for name, p in (tool.get("params") or {}).items():
        for key in ("description", "default"):
            if p.get(key):
                fields.append((f"param:{name}.{key}", str(p[key])))
    return fields


def security_findings(tools: list[dict], instructions: str | None = None, changed: set[str] | None = None) -> list[dict]:
    """tools: full_tools() 결과. changed: 지난 수집 이후 정의가 바뀐 도구 이름 (러그 풀 판단용)."""
    findings, seen = [], set()

    def add(severity, code, tool, message):
        if (code, tool) in seen:
            return
        seen.add((code, tool))
        findings.append({"severity": severity, "code": code, "tool": tool, "message": message,
                         "precision": "high" if PRECISION[code] >= 1 else "review"})

    sources = [(t["name"], f, text) for t in tools for f, text in _text_fields(t)]
    if instructions:
        sources.append(("<server instructions>", "instructions", str(instructions)[:20000]))
    for tool, field, text in sources:
        if _HIDDEN_CHARS.search(text):
            hidden = "".join(chr(ord(c) - 0xE0000) for m in _TAG_CHARS.findall(text) for c in m)
            add("critical", "hidden_unicode", tool, f"Invisible/bidi/tag Unicode characters in {field}"
                + (f" (decoded: '{hidden[:80]}')" if hidden else ""))
        if _ANSI.search(text):
            add("high", "ansi_escape", tool, f"ANSI terminal escape codes in {field}")
        # 문서용 예시 키(AWS의 AKIAIOSFODNN7EXAMPLE 등)는 비밀 탐지 도구의 예시에 흔하다 (실측 오탐)
        if (m := _SECRET.search(text)) and "EXAMPLE" not in m.group(0).upper() and "XXXX" not in m.group(0).upper():
            add("critical", "hardcoded_secret", tool, f"Hardcoded credential-like string '{m.group(0)[:8]}…' in {field}")
        if m := _INJECTION.search(text):
            add("high", "instruction_injection", tool, f"Instruction-like text aimed at the model in {field}: '{m.group(0)[:60]}'")
        if m := _SENSITIVE.search(text):
            add("medium", "sensitive_path", tool, f"Mentions sensitive file '{m.group(0)}' in {field}")
        if _SCRIPT.search(text):
            add("medium", "script_tag", tool, f"Script markup in {field}")
        if _BASE64_BLOB.search(text):
            add("low", "encoded_blob", tool, f"Long encoded blob in {field}")
    for t in tools:
        for name in (t.get("params") or {}):
            if _EXFIL_PARAM.match(name):
                add("high", "exfiltration_param", t["name"], f"Parameter '{name}' asks for conversation or hidden context")
        ann = t.get("annotations") or {}
        # 주석끼리 모순일 때만 (이름 기반은 remove_duplicate_lines 같은 텍스트 변환 도구에서 오탐)
        if ann.get("readOnlyHint") is True and ann.get("destructiveHint") is True:
            add("medium", "annotation_contradiction", t["name"], "Annotated both readOnlyHint and destructiveHint")
    # 이미 있던 도구의 정의가 바뀌면서 검토 필요 신호가 새로 생겼다면 승인 후 바꿔치기(러그 풀) 의심
    for f in list(findings):
        if changed and f["tool"] in changed and f["precision"] == "review":
            add("critical", "rug_pull_suspect", f["tool"], f"Definition changed since last survey and now has '{f['code']}'")
    return findings


def _tool_definition_score(tool: dict) -> tuple[float, list[str]]:
    """도구 하나의 정의 품질 (0~1)과 부족한 점. Glama TDQS의 결정적 관문을 규칙으로 구현."""
    desc = (tool.get("description") or "").strip()
    name_words = set(re.findall(r"[a-z]+", tool["name"].lower()))
    desc_words = set(re.findall(r"[a-z]+", desc.lower()))
    checks = {
        "has_description": len(desc) >= 20,
        "not_too_long": len(desc) <= 1500,
        "states_purpose": bool(_PURPOSE_VERB.search(desc)) and not (desc_words and desc_words <= name_words),
        "no_placeholder": not _PLACEHOLDER.search(desc),
        "mentions_output": bool(_RETURNS.search(desc)),
        "usage_guidance": bool(_GUIDANCE.search(desc)),
    }
    params = tool.get("params") or {}
    if params:
        described = sum(1 for p in params.values() if len(str(p.get("description") or "")) >= 5)
        typed = sum(1 for p in params.values() if p.get("type") or p.get("enum"))
        checks["params_described"] = described / len(params) >= 0.8
        checks["params_typed"] = typed / len(params) == 1.0
    checks["safety_annotations"] = any(k in (tool.get("annotations") or {}) for k in ("readOnlyHint", "destructiveHint"))
    weights = {"has_description": 0.25, "states_purpose": 0.15, "params_described": 0.2, "params_typed": 0.1,
               "mentions_output": 0.1, "usage_guidance": 0.05, "safety_annotations": 0.1, "no_placeholder": 0.025,
               "not_too_long": 0.025}
    total = sum(weights[k] for k in checks)
    return sum(weights[k] for k, ok in checks.items() if ok) / total, [k for k, ok in checks.items() if not ok]


def _near_duplicates(tools: list[dict]) -> int:
    """서버 안에서 설명이 거의 같은 도구 쌍의 수 (단어 집합 Jaccard ≥ 0.9). 모델이 도구를 헷갈린다."""
    sets = [set(re.findall(r"[a-z0-9]+", (t.get("description") or "").lower())) for t in tools[:60]]
    pairs = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if len(a) >= 5 and len(b) >= 5 and len(a & b) / len(a | b) >= 0.9:
                pairs += 1
    return pairs


def protocol_findings(tools_raw: list, init: dict | None) -> tuple[float, list[dict]]:
    findings, checks = [], []
    init = init or {}

    def check(ok, code, message, tool=None, severity="low"):
        checks.append(bool(ok))
        if not ok:
            findings.append({"severity": severity, "code": code, "tool": tool, "message": message})

    pv = init.get("protocol_version")
    check(pv, "no_protocol_version", "initialize did not return protocolVersion", severity="medium")
    if pv:
        check(isinstance(pv, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", pv), "invalid_protocol_version",
              f"protocolVersion '{str(pv)[:20]}' is not a YYYY-MM-DD revision", severity="medium")
    check((init.get("server_info") or {}).get("name"), "no_server_info", "initialize did not return serverInfo.name")
    names = [t.get("name") for t in tools_raw if isinstance(t, dict)]
    check(len(names) == len(set(names)), "duplicate_tool_names", "Duplicate tool names", severity="medium")
    check(tools_raw, "no_tools", "tools/list returned no tools", severity="medium")
    for t in tools_raw[:200]:
        if not isinstance(t, dict):
            check(False, "invalid_tool", "Tool entry is not an object", severity="medium")
            continue
        name = str(t.get("name") or "")
        check(_TOOL_NAME.match(name), "invalid_tool_name", f"Tool name '{name[:40]}' violates the naming rule", name)
        schema = t.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") not in ("object", None):
            check(False, "invalid_input_schema", "inputSchema is missing or not an object schema", name, "medium")
            continue
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        check(isinstance(props, dict), "invalid_properties", "properties is not an object", name, "medium")
        check(isinstance(props, dict) and isinstance(required, list) and set(map(str, required)) <= set(props),
              "required_not_in_properties", "required lists parameters that are not defined", name)
        bad_types = [k for k, v in (props.items() if isinstance(props, dict) else [])
                     if isinstance(v, dict) and isinstance(v.get("type"), str) and v["type"] not in _KNOWN_TYPES]
        check(not bad_types, "unknown_param_type", f"Unknown parameter types: {bad_types[:3]}", name)
    return (sum(checks) / len(checks) if checks else 0.0), findings


def provenance_score(resource: dict, now: float | None = None) -> tuple[float, list[dict]]:
    """출처·유지보수 (Tier 0, 실행 없이). 공식 레지스트리는 게시할 때 네임스페이스 소유권을 검증하므로
    네임스페이스와 저장소 소유자·원격 주소 도메인이 일치하면 출처가 확인된 것으로 본다. 스타 수는 쓰지 않는다."""
    now = now or time.time()
    try:
        details = json.loads(resource.get("details") or "{}")
    except ValueError:
        details = {}
    findings, score = [], 0.0
    reg = str(details.get("registry_name") or "")
    repo = str(details.get("repository") or "")
    namespace = reg.split("/")[0].lower()
    owner = namespace.split(".", 2)[2] if namespace.startswith(("io.github.", "io.gitlab.")) else None
    host = (resource.get("host") or "").lower()
    verified = False
    if owner and re.search(rf"(github|gitlab)\.com/{re.escape(owner)}/", repo, re.I):
        verified = True
    elif namespace and not owner and "." in namespace:  # com.example → example.com
        domain = ".".join(reversed(namespace.split(".")))
        verified = host == domain or host.endswith("." + domain)
    if verified:
        score += 0.35
    else:
        findings.append({"severity": "low", "code": "unverified_publisher", "tool": None,
                         "message": "Registry namespace does not match the repository owner or endpoint domain"})
    if re.match(r"https://(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org)/[^/]+/[^/]+", repo):
        score += 0.25
    else:
        findings.append({"severity": "low", "code": "no_repository", "tool": None, "message": "No public source repository"})
    if details.get("website"):
        score += 0.1
    version = str(details.get("version") or "")
    if re.match(r"^\d+\.\d+", version) and not version.startswith("0.0.0"):
        score += 0.1
    updated = resource.get("last_called")  # MCP Registry의 updatedAt
    if updated:
        age_days = (now - updated) / 86400
        score += 0.2 if age_days <= 90 else 0.12 if age_days <= 180 else 0.05 if age_days <= 365 else 0.0
        if age_days > 365:
            findings.append({"severity": "low", "code": "stale_release", "tool": None, "message": "Not updated for over a year"})
    return round(min(score, 1.0), 3), findings


def _linear(value: float, good: float, bad: float, floor: float) -> float:
    if value <= good:
        return 1.0
    if value >= bad:
        return floor
    return 1.0 - (1.0 - floor) * (value - good) / (bad - good)


def _sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: (-SEVERITY_PENALTY[f["severity"]], f["code"]))[:25]


def evaluate(resource: dict, tools_raw: list, tools: list[dict], init: dict | None,
             trial: dict | None = None, changes: dict | None = None, now: float | None = None) -> dict:
    """도구 목록 조회에 성공한 MCP 서버의 평가 (Tier 1).

    resource: DB 행 (헬스·출처 정보), tools_raw: tools/list 원본, tools: compact_tools 정리본,
    init: {protocol_version, server_info, instructions}, trial: 이번 또는 마지막 시험 호출, changes: diff_tools 결과.
    """
    from .usage import is_auth_error
    dims, findings = {}, []

    # 1) 가용성 A = 0.45·initialize 성공률(헬스체크) + 0.15·tools/list 성공 + 0.25·시험 호출 + 0.15·지연
    n, ok = resource.get("health_n_24h") or 0, resource.get("health_ok_24h") or 0
    uptime = ok / n if n >= 3 else (ok + 1) / (n + 2)  # 점검이 적을 때만 라플라스 보정
    latency = resource.get("probe_latency_ms")
    if trial and trial.get("latency_ms"):
        latency = max(latency or 0, trial["latency_ms"])
    speed = 1.0 if latency is None or latency <= 1000 else 0.8 if latency <= 3000 else 0.5 if latency <= 8000 else 0.2
    trial_auth = bool(trial and not trial.get("ok") and is_auth_error(trial.get("error")))
    parts = [(0.45, uptime), (0.15, 1.0), (0.15, speed)]
    if trial and not trial_auth:  # 도구 단계 인증으로 실패한 시험은 가용성 실패로 치지 않는다
        parts.append((0.25, 1.0 if trial.get("ok") else 0.2))
    dims["availability"] = round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 3)
    if uptime < 0.9 and n >= 3:
        findings.append({"severity": "medium", "code": "low_uptime", "tool": None, "message": f"24h uptime {ok}/{n}"})
    if trial and not trial.get("ok") and not trial_auth:
        findings.append({"severity": "medium", "code": "trial_failed", "tool": trial.get("tool"),
                         "message": f"Safe trial call failed: {str(trial.get('error') or '')[:120]}"})

    # 2) 정의 품질 D: 도구별 점수를 0.6·평균 + 0.4·최솟값, 도구 수·근접 중복 보정
    per_tool = [_tool_definition_score(t) for t in tools]
    if per_tool:
        scores = [s for s, _ in per_tool]
        d = 0.6 * sum(scores) / len(scores) + 0.4 * min(scores)
        issue_counts: dict[str, int] = {}
        for _, issues in per_tool:
            for i in issues:
                issue_counts[i] = issue_counts.get(i, 0) + 1
        for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1])[:4]:
            if count / len(per_tool) >= 0.5:
                findings.append({"severity": "low", "code": f"def_{issue}", "tool": None,
                                 "message": f"{count}/{len(per_tool)} tools fail '{issue}'"})
        dups = _near_duplicates(tools)
        if dups:
            d *= 0.9
            findings.append({"severity": "low", "code": "near_duplicate_tools", "tool": None,
                             "message": f"{dups} pair(s) of tools with nearly identical descriptions"})
        if not 3 <= len(tools) <= 15:
            d *= 0.95
        dims["definitions"] = round(d, 3)
    else:
        dims["definitions"] = 0.0

    # 3) 보안 S = 100 − Σ(심각도 감점 × 정밀도 계수)
    changed = set((changes or {}).get("changed") or [])
    sec = security_findings(full_tools(tools_raw), (init or {}).get("instructions"), changed)
    findings += sec
    penalty = sum(SEVERITY_PENALTY[f["severity"]] * PRECISION[f["code"]] for f in sec)
    dims["security"] = round(max(0.0, 100 - penalty) / 100, 3)
    quarantined = any(f["code"] in QUARANTINE_CODES for f in sec)
    security_level = "quarantine" if quarantined else "review" if sec else "ok"

    # 4) 컨텍스트 C = 0.6·정의 총 토큰(≤5K 만점, ≥20K 0.2) + 0.25·응답 크기 + 0.15·도구당 토큰
    def_tokens = len(json.dumps(tools_raw, ensure_ascii=False)) // 4  # 약 4글자 = 1토큰
    count = len(tools)
    per_tool_tokens = def_tokens / count if count else 0
    parts = [(0.6, _linear(def_tokens, 5000, 20000, 0.2)), (0.15, _linear(per_tool_tokens, 300, 1500, 0.3))]
    if trial and trial.get("ok") and trial.get("output_chars") is not None:
        parts.append((0.25, _linear(trial["output_chars"] / 4, 2000, 25000, 0.2)))
    dims["context"] = round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 3)
    if def_tokens > 15000:
        findings.append({"severity": "low", "code": "large_tool_definitions", "tool": None,
                         "message": f"Tool definitions take ~{def_tokens} tokens of context"})
    if count > 30:
        findings.append({"severity": "low", "code": "many_tools", "tool": None, "message": f"{count} tools (5-15 recommended)"})

    # 5) 프로토콜 준수 P (구동된 서버 사이의 분산이 작아 가중치 낮음)
    p, pf = protocol_findings(tools_raw, init)
    dims["protocol"] = round(p, 3)
    findings += pf

    # 6) 출처·유지보수 M
    dims["provenance"], mf = provenance_score(resource, now)
    findings += mf

    score = sum(WEIGHTS[k] * v for k, v in dims.items())
    if quarantined:
        score = min(score, QUARANTINE_CAP)
    coverage = "full" if trial and not trial_auth else "definitions"
    return {
        "version": VERSION,
        "status": "scored",
        "coverage": coverage,  # full: 정의+실제 호출, definitions: 정의만, static: 출처만
        "task_verified": False,  # LLM 실작업(pass^3) 검증 안 함
        "score": round(score, 1),
        "grade": grade_for(score),
        "security": security_level,
        "dimensions": dims,
        "stats": {"tool_count": count, "definition_tokens": def_tokens, "per_tool_tokens": int(per_tool_tokens),
                  "security_signals": len(sec)},
        "findings": _sort_findings(findings),
        "at": now or time.time(),
    }


def evaluate_static(resource: dict, now: float | None = None) -> dict:
    """연결부터 인증이 필요해 도구를 볼 수 없는 서버 (Tier 0만). 가용성 실패로 섞으면 공식 SaaS 서버가 부당하게 낮아지므로
    출처·유지보수 점수만 따로 보여 준다. 총점·등급은 매기지 않는다."""
    m, findings = provenance_score(resource, now)
    return {"version": VERSION, "status": "auth_required", "coverage": "static", "task_verified": False,
            "score": None, "grade": None, "static_score": round(m * 100, 1), "security": "unknown",
            "dimensions": {"provenance": m}, "stats": {}, "findings": _sort_findings(findings), "at": now or time.time()}


# ---------------- A2A 에이전트 ----------------

def _skill_score(skill: dict) -> tuple[float, list[str]]:
    """스킬 하나의 정의 품질. 다른 에이전트가 고를 때 쓰는 것은 설명·태그·예시·입출력 형식이다."""
    desc = (skill.get("description") or "").strip()
    name_words = set(re.findall(r"[a-z]+", f"{skill['name']} {skill.get('title', '')}".lower()))
    desc_words = set(re.findall(r"[a-z]+", desc.lower()))
    checks = {
        "has_description": len(desc) >= 20,
        "not_too_long": len(desc) <= 1500,
        "states_purpose": len(desc_words - name_words) >= 3 or bool(re.search(r"[^\x00-\x7f]{6,}", desc)),
        "no_placeholder": not _PLACEHOLDER.search(desc),
        "has_tags": bool(skill.get("tags")),
        "has_examples": bool(skill.get("examples")),
        "has_title": bool(skill.get("title")),
    }
    weights = {"has_description": 0.3, "states_purpose": 0.15, "has_examples": 0.25, "has_tags": 0.1, "has_title": 0.1,
               "no_placeholder": 0.05, "not_too_long": 0.05}
    return sum(weights[k] for k, ok in checks.items() if ok), [k for k, ok in checks.items() if not ok]


def _registrable(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-3:] if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3 else parts[-2:])


def agent_protocol_findings(card: dict, meta: dict, live: dict) -> tuple[float, list[dict]]:
    findings, checks = [], []

    def check(ok, code, message, severity="low"):
        checks.append(bool(ok))
        if not ok:
            findings.append({"severity": severity, "code": code, "tool": None, "message": message})

    keys = set(meta.get("raw_keys") or [])
    v1 = card["spec_version"].startswith("1")
    required = ["name", "description", "version", "capabilities", "defaultInputModes", "defaultOutputModes", "skills"]
    required += ["supportedInterfaces"] if v1 else ["url"]
    missing = [k for k in required if k not in keys]
    check(not missing, "card_missing_fields", f"Agent card lacks required fields: {missing[:6]}", "medium")
    check(card["interfaces"], "no_interfaces", "No interface URL to call", "medium")
    check(all(i["binding"] in _VALID_BINDINGS for i in card["interfaces"]), "unknown_binding",
          f"Unknown protocol binding: {[i['binding'] for i in card['interfaces']][:3]}")
    ids = [k["name"] for k in card["skills"]]
    check(ids and all(ids), "skill_without_id", "Skill without id")
    check(len(ids) == len(set(ids)), "duplicate_skill_ids", "Duplicate skill ids", "medium")
    check(card["skills"], "no_skills", "Agent card lists no skills", "medium")
    check(meta.get("well_known"), "not_at_well_known_path", "Card is not served at /.well-known/agent-card.json")
    check("json" in str(meta.get("content_type") or ""), "card_content_type", "Card is not served as application/json")
    check(not live.get("declared_endpoint"), "declared_endpoint_wrong",
          f"Card url {str(live.get('declared_endpoint'))[:60]} does not answer A2A; found the endpoint at {live.get('endpoint')}",
          "medium")
    if live.get("ok") and not live.get("auth") and live.get("binding") == "JSONRPC":
        if live.get("jsonrpc_error") == -32601:
            check(False, "get_task_not_implemented", "The agent does not implement GetTask / tasks/get (Method not found)")
        else:
            check(live.get("conformant"), "nonstandard_jsonrpc_errors",
                  "GetTask for an unknown task returned " + (f"code {live['jsonrpc_error']}" if live.get("jsonrpc_error")
                                                            else "no JSON-RPC error") + " instead of -32001 (TaskNotFound)")
    return (sum(checks) / len(checks) if checks else 0.0), findings


def agent_security_findings(card: dict) -> list[dict]:
    as_tools = [{"name": k["name"], "description": " ".join([k["description"]] + k["examples"]), "params": {},
                 "annotations": {}} for k in card["skills"]]
    as_tools.append({"name": "<agent card>", "description": card["description"], "params": {}, "annotations": {}})
    findings = security_findings(as_tools)
    for i in card["interfaces"]:
        if i["url"].startswith("http://"):
            findings.append({"severity": "high", "code": "insecure_endpoint", "tool": None, "precision": "high",
                             "message": f"Interface is plain HTTP: {i['url'][:80]}"})
            break
    for name, sch in card["security_schemes"].items():
        if sch["type"] == "apiKey" and sch.get("location") == "query":
            findings.append({"severity": "medium", "code": "api_key_in_query", "tool": None, "precision": "high",
                             "message": f"Scheme '{name}' sends the API key in the URL query (leaks into logs)"})
        if sch["type"] == "oauth2" and set(sch.get("flows") or {}) & {"implicit", "password"}:
            findings.append({"severity": "medium", "code": "deprecated_oauth_flow", "tool": None, "precision": "high",
                             "message": f"Scheme '{name}' offers deprecated OAuth implicit/password flows"})
    return findings


def agent_provenance(resource: dict, card: dict, domain_verified: bool | None) -> tuple[float, list[dict]]:
    findings, score = [], 0.0
    host = urlparse(card["card_url"]).hostname or ""
    org, purl = card["provider"].get("organization"), card["provider"].get("url")
    if org and purl:
        score += 0.2
    else:
        findings.append({"severity": "low", "code": "no_provider", "tool": None, "message": "Agent card names no provider"})
    if purl and _registrable(urlparse(purl).hostname or "") == _registrable(host):
        score += 0.2
    elif purl:
        findings.append({"severity": "low", "code": "provider_domain_mismatch", "tool": None,
                         "message": "Provider URL is on a different domain than the agent card"})
    if card.get("documentation_url"):
        score += 0.1
    if card.get("signed"):
        score += 0.2
    if re.match(r"^\d+\.\d+", card.get("version") or ""):
        score += 0.1
    regs = json.loads(resource.get("details") or "{}").get("erc8004") or []
    if regs:
        score += 0.1
        if domain_verified:
            score += 0.1
        elif domain_verified is False:
            findings.append({"severity": "low", "code": "erc8004_domain_unverified", "tool": None,
                             "message": "Registered on ERC-8004 but the endpoint domain does not confirm the registration"})
    else:
        score += 0.05 if card.get("icon_url") else 0.0
    return round(min(score, 1.0), 3), findings


def evaluate_agent(resource: dict, card: dict, meta: dict, live: dict, trial: dict | None = None,
                   changes: dict | None = None, domain_verified: bool | None = None, now: float | None = None) -> dict:
    """A2A 에이전트 평가. MCP와 같은 6개 축·가중치·등급을 쓰되, 정의 품질은 스킬, 컨텍스트는 card 크기로 본다.
    인증이 필요해도 card는 공개되므로 정의·보안·프로토콜·출처는 항상 평가한다 (시험 호출만 빠짐)."""
    from .usage import is_auth_error
    dims, findings = {}, []

    # 1) 가용성: card 헬스체크 0.45 + 엔드포인트 응답 0.15 + 시험 메시지 0.25 + 지연 0.15
    n, ok = resource.get("health_n_24h") or 0, resource.get("health_ok_24h") or 0
    uptime = ok / n if n >= 3 else (ok + 1) / (n + 2)
    latency = max(live.get("latency_ms") or 0, (trial or {}).get("latency_ms") or 0) or None
    speed = 1.0 if latency is None or latency <= 2000 else 0.8 if latency <= 6000 else 0.5 if latency <= 15000 else 0.2
    endpoint_ok = 1.0 if live.get("ok") else 0.0 if live.get("ok") is False else 0.5
    # 인증·결제가 필요해 거절된 시험은 실패로 치지 않는다 (서비스는 정상, 조건이 있을 뿐)
    trial_auth = bool(trial and not trial.get("ok") and (is_auth_error(trial.get("error")) or trial.get("payment_required")))
    parts = [(0.45, uptime), (0.15, endpoint_ok), (0.15, speed)]
    if trial and not trial_auth and not trial.get("skipped"):
        parts.append((0.25, 1.0 if trial.get("ok") else 0.2))
    dims["availability"] = round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 3)
    if live.get("ok") is False:
        findings.append({"severity": "high", "code": "endpoint_unreachable", "tool": None,
                         "message": f"Agent card is up but the endpoint did not answer: {str(live.get('error'))[:100]}"})
    if uptime < 0.9 and n >= 3:
        findings.append({"severity": "medium", "code": "low_uptime", "tool": None, "message": f"24h uptime {ok}/{n}"})
    if trial and not trial.get("ok") and not trial_auth and not trial.get("skipped"):
        findings.append({"severity": "medium", "code": "trial_failed", "tool": trial.get("skill"),
                         "message": f"Test message failed: {str(trial.get('error') or '')[:120]}"})

    # 2) 정의 품질: 스킬별 점수 0.6·평균 + 0.4·최솟값 (70%) + card 수준 (30%)
    per = [_skill_score(k) for k in card["skills"]]
    card_level = sum([0.4 * (len(card["description"]) >= 30), 0.3 * bool(card["default_input_modes"]),
                      0.3 * bool(card["default_output_modes"])])
    if per:
        sc = [x for x, _ in per]
        skill_part = 0.6 * sum(sc) / len(sc) + 0.4 * min(sc)
        counts: dict[str, int] = {}
        for _, issues in per:
            for i in issues:
                counts[i] = counts.get(i, 0) + 1
        for issue, c in sorted(counts.items(), key=lambda x: -x[1])[:4]:
            if c / len(per) >= 0.5:
                findings.append({"severity": "low", "code": f"skill_{issue}", "tool": None,
                                 "message": f"{c}/{len(per)} skills fail '{issue}'"})
        if _near_duplicates(card["skills"]):
            skill_part *= 0.9
            findings.append({"severity": "low", "code": "near_duplicate_skills", "tool": None,
                             "message": "Skills with nearly identical descriptions"})
    else:
        skill_part = 0.0
    dims["definitions"] = round(0.7 * skill_part + 0.3 * card_level, 3)

    # 3) 보안
    sec = agent_security_findings(card)
    changed = set((changes or {}).get("changed") or [])
    for f in list(sec):
        if changed and f.get("tool") in changed and f.get("precision") == "review":
            sec.append({"severity": "critical", "code": "rug_pull_suspect", "tool": f["tool"], "precision": "high",
                        "message": f"Skill changed since last survey and now has '{f['code']}'"})
    findings += sec
    penalty = sum(SEVERITY_PENALTY[f["severity"]] * PRECISION[f["code"]] for f in sec)
    dims["security"] = round(max(0.0, 100 - penalty) / 100, 3)
    quarantined = any(f["code"] in QUARANTINE_CODES for f in sec)
    security_level = "quarantine" if quarantined else "review" if sec else "ok"

    # 4) 컨텍스트: card 크기(다른 에이전트가 읽어야 하는 양)와 스킬 수
    size_tokens = (meta.get("size") or len(json.dumps(card))) // 4
    count = len(card["skills"])
    dims["context"] = round(0.6 * _linear(size_tokens, 3000, 20000, 0.2)
                            + 0.4 * (1.0 if 1 <= count <= 20 else 0.6 if count <= 50 else 0.3), 3)
    if size_tokens > 15000:
        findings.append({"severity": "low", "code": "large_agent_card", "tool": None,
                         "message": f"Agent card is ~{size_tokens} tokens"})

    # 5) 프로토콜 준수, 6) 출처
    p, pf = agent_protocol_findings(card, meta, live)
    dims["protocol"] = round(p, 3)
    findings += pf
    dims["provenance"], mf = agent_provenance(resource, card, domain_verified)
    findings += mf

    score = sum(WEIGHTS[k] * v for k, v in dims.items())
    if quarantined:
        score = min(score, QUARANTINE_CAP)
    return {
        "version": AGENT_VERSION, "kind": "a2a", "status": "scored",
        "coverage": "full" if trial and not trial_auth and not trial.get("skipped") else "definitions",
        "task_verified": False, "score": round(score, 1), "grade": grade_for(score), "security": security_level,
        "dimensions": dims,
        "stats": {"skill_count": count, "card_tokens": size_tokens, "spec_version": card["spec_version"],
                  "auth_schemes": sorted({s["type"] for s in card["security_schemes"].values()}),
                  "signed": card.get("signed"), "security_signals": len(sec)},
        "findings": _sort_findings(findings), "at": now or time.time(),
    }
