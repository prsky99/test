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

VERSION = 2
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

# 고정밀 신호. ZWJ(U+200D)·변이 선택자는 이모지에 정상적으로 쓰이므로 제외
_HIDDEN_CHARS = re.compile("[​‌‎‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
_TAG_CHARS = re.compile("[\U000e0020-\U000e007e]+")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
_SECRET = re.compile(r"\b(sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{24,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|"
                     r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{20,}|AIza[0-9A-Za-z_\-]{35}|"
                     r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
_DESTRUCTIVE_NAME = re.compile(r"(^|[_\-.])(delete|drop|remove|destroy|purge|truncate|wipe|erase)([_\-.]|$)", re.I)
# 검토 필요 신호 (regex 문구 탐지)
_INJECTION = re.compile(
    r"(<\s*important\s*>|ignore (all |any )?(previous|prior|above) instructions|disregard (the |all )?(previous|prior|above)|"
    r"do not (tell|inform|mention|reveal)( this)? to the user|without (telling|informing|asking) the user|"
    r"(the )?user (must|should) not (know|see)|"
    r"system prompt|override (your|the) instructions|<\s*/?\s*(system|instructions?)\s*>)", re.I)
_SENSITIVE = re.compile(r"(~/\.ssh|id_rsa|\.aws/credentials|mcp\.json|claude_desktop_config|\.npmrc|\.netrc|"
                        r"/etc/passwd|seed phrase|wallet\.dat)", re.I)
_EXFIL_PARAM = re.compile(r"^(sidenote|side_note|note_to_self|hidden|secret_?notes?|context_?dump|conversation(_history)?|"
                          r"chat_?history|system_?prompt|previous_?messages)$", re.I)
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
        if m := _SECRET.search(text):
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
        if ann.get("readOnlyHint") is True and (_DESTRUCTIVE_NAME.search(t["name"]) or ann.get("destructiveHint") is True):
            add("medium", "annotation_contradiction", t["name"], "Marked readOnlyHint but the name/annotations say destructive")
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

    check(init.get("protocol_version"), "no_protocol_version", "initialize did not return protocolVersion", severity="medium")
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

    # 1) 가용성 A = 0.45·initialize 성공률(헬스체크, 라플라스 보정) + 0.15·tools/list 성공 + 0.25·시험 호출 + 0.15·지연
    n, ok = resource.get("health_n_24h") or 0, resource.get("health_ok_24h") or 0
    uptime = (ok + 1) / (n + 2)
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
