"""Shared report-draft checks and quality standards for the report pipeline scripts.

Admin API calls use the caller's own ADMIN_SESSION_TOKEN (see submit_report_drafts.py); the shared
ADMIN_TOKEN only reads aggregate monitoring and is never used here.
"""
import math
import re
import time

HANGUL = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')
PRIVATE = re.compile(r'(?i)\b(?:127\.0\.0\.1|localhost|0\.0\.0\.0)\b|upstream\s+(?:provider\s+|agent\s+)?(?:target|binding|card|endpoint)|:(?:8080|8200|8400)\b')

CANONICAL_TEST_METHODS = (
    'A2A Agent Card',
    'A2A Message',
    'MCP Tools List',
    'MCP Tool Call',
    'x402 Challenge',
)

CANONICAL_GRADES = ('A', 'B', 'C', 'D')

COMMERCIAL_LEAD_GEN_RE = re.compile(
    r'(?i)\b(cold\s+(?:email|outreach|calling|prospecting)|b2b\s+prospecting|b2b\s+lead\s+intelligence|lead\s+scraping|prospecting\s+and\s+cold)\b'
)
COMMERCIAL_SPAM_RE = re.compile(
    r'(?i)\b(pump\.fun|memecoin\s+migration|affiliate\s+partners\s+traffic|referral\s+traffic|referral\s+code\s+injection)\b'
)
SECURITY_RISK_RE = re.compile(
    r'(?i)\b(prompt\s+injection\s+exploit|wallet\s+drainer|private\s+key\s+extractor|credential\s+harvesting)\b'
)
ABUSIVE_CONTENT_RE = re.compile(
    r'(?i)\b(fuck|pussy|cunt|blowjob|handjob)\b'
)


def is_excluded_agent(agent_data: dict) -> tuple[bool, str | None]:
    """Check if an agent resource must be excluded from test report generation.
    Returns (True, exclusion_reason) if excluded, or (False, None) if clean.
    """
    if not isinstance(agent_data, dict):
        return True, "invalid_agent_data"

    # 1. Active status check (must be active == 1)
    active_val = agent_data.get('active')
    if active_val is not None and active_val != 1 and active_val is not True:
        return True, f"inactive (active={active_val})"

    # 2. Security status check (quarantine or review required)
    sec = str(agent_data.get('eval_security') or '').lower().strip()
    if sec in ('review', 'quarantine', 'quarantined'):
        return True, f"security_{sec}"

    # 3. Explicit inactive reason check
    reason = agent_data.get('inactive_reason')
    if reason and str(reason).strip():
        return True, f"inactive_reason:{reason}"

    # 4. Health status check
    health = str(agent_data.get('health_status') or '').lower().strip()
    if health in ('down', 'retired', 'quarantined', 'failing', 'unreachable'):
        return True, f"unhealthy:{health}"

    # 5. Content-level heuristic checks across name, description, url, category
    text_corpus = ' '.join([
        str(agent_data.get('name') or ''),
        str(agent_data.get('description') or ''),
        str(agent_data.get('url') or ''),
        str(agent_data.get('category') or '')
    ]).lower()

    if COMMERCIAL_LEAD_GEN_RE.search(text_corpus):
        return True, "policy_violation_commercial_lead_gen"
    if COMMERCIAL_SPAM_RE.search(text_corpus):
        return True, "policy_violation_commercial_spam"
    if SECURITY_RISK_RE.search(text_corpus):
        return True, "security_risk_exploit"
    if ABUSIVE_CONTENT_RE.search(text_corpus):
        return True, "policy_violation_abusive_content"

    return False, None



def normalize_test_method(kind: str, raw_method: str | None) -> str:
    m = str(raw_method or '').strip()
    m_lower = m.lower()
    if kind == 'a2a':
        if any(k in m_lower for k in ('message', 'send', 'task', 'exec')):
            return 'A2A Message'
        return 'A2A Agent Card'
    elif kind == 'mcp':
        if any(k in m_lower for k in ('call', 'invoke')):
            return 'MCP Tool Call'
        return 'MCP Tools List'
    elif kind == 'x402':
        return 'x402 Challenge'
    return m or 'A2A Agent Card'


def english_clean(desc: str) -> str:
    """Ensure catalog descriptions embedded in English reports contain zero Korean/non-Latin scripts."""
    if not desc:
        return ''
    if '\ub098\ub9cc\uc744 \uc704\ud55c AI \uc1fc\ud551 MCP' in desc:
        return 'Personalized AI shopping MCP — Search, compare, and recommend products using natural language to streamline shopping.'
    if HANGUL.search(desc):
        sentences = [s.strip() for s in re.split(r'[\.!?]\s*', desc) if s.strip()]
        clean_sentences = [s for s in sentences if not re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f\u4e00-\u9fff\u3040-\u30ff]', s)]
        if clean_sentences:
            return '. '.join(clean_sentences) + '.'
        return re.sub(r'[^\x00-\x7F]+', ' ', desc).strip()
    return desc


def normalize_eval_grade(grade: str | None) -> str | None:
    if not grade:
        return None
    g = str(grade).strip()
    if g.startswith('Grade '):
        g = g[6:].strip()
    return g if g in CANONICAL_GRADES else None


CATEGORY_WORKFLOW_HINTS = {
    'research_knowledge': 'knowledge synthesis and evidence cross-checking pipelines',
    'web_search': 'multi-source web discovery and citation verification workflows',
    'developer_tools': 'automated code inspection, build verification, and repository maintenance pipelines',
    'data_analytics': 'structured dataset ingestion, schema validation, and analytical reporting pipelines',
    'finance_accounting': 'market data aggregation, risk monitoring, and audit trail workflows',
    'blockchain_web3': 'on-chain state inspection, ledger verification, and protocol monitoring workflows',
    'productivity_automation': 'task orchestration, schedule coordination, and automated operational handoffs',
    'communication_social': 'message routing, notification dispatch, and channel aggregation workflows',
    'travel_maps_weather': 'geospatial lookup, itinerary planning, and environmental monitoring workflows',
    'healthcare_bio': 'biomedical literature lookup and structured scientific reference workflows',
    'security_identity': 'access verification, compliance auditing, and threat surface inspection workflows',
    'media_content': 'asset transformation, transcription, and media indexing pipelines',
    'ecommerce_retail': 'catalog lookup, inventory comparison, and fulfillment tracking workflows',
}


def synthesize_workflow_recommendation(
    kind: str | None,
    category: str | None,
    agent_name: str | None = None,
    tool_name: str | None = None,
    is_success: int | bool | None = 1,
) -> str:
    """Generate a deterministic, 100% English workflow integration recommendation (AQEF-30 Layer 5)."""
    k = str(kind or 'a2a').lower().strip()
    cat_key = str(category or 'other').lower().strip()
    cat_hint = CATEGORY_WORKFLOW_HINTS.get(
        cat_key,
        'multi-agent orchestration and automated verification pipelines',
    )
    raw_tool = english_clean(str(tool_name or '').strip())
    tool_label = raw_tool if (raw_tool and len(raw_tool) <= 48 and not PRIVATE.search(raw_tool)) else ''

    if not is_success:
        return (
            f"Hold production integration in {cat_hint} until endpoint reachability and "
            f"protocol contract conformance pass automated pre-flight checks."
        )

    if k == 'a2a':
        skill_part = f" via the '{tool_label}' skill" if tool_label else ""
        return (
            f"Integrate as a specialized A2A delegate agent{skill_part} within {cat_hint}; "
            f"validate Agent Card capability declarations and response latency bounds before task dispatch."
        )
    if k == 'mcp':
        tool_part = f" exposing '{tool_label}'" if tool_label else ""
        return (
            f"Connect as a schema-verified MCP tool server{tool_part} in {cat_hint}; "
            f"enforce JSON-RPC 2.0 input schema validation and timeout guards in the calling host."
        )
    return (
        f"Chain as a challenge-verified HTTP resource node within {cat_hint}; "
        f"confirm challenge parameters and settlement timeout constraints prior to automated invocation."
    )


# Probe methods that only read a public contract (no tool, task or paid call was executed).
TRANSPORT_ONLY_METHODS = {'a2a agent card', 'mcp tools list', 'x402 challenge'}


def probe_evidence_scope(test_method: str | None) -> str:
    """'execution' only when the probe actually invoked a tool, task or paid call; otherwise 'transport'.

    AQEF-30 section 3.1: Grade A requires verified live execution evidence, so a card fetch, a tools/list
    handshake or an unpaid 402 challenge can never be labelled as execution evidence (11-10 audit: 213 of 300
    re-scored reports were graded A on transport-only probes).
    """
    return 'transport' if str(test_method or '').strip().lower() in TRANSPORT_ONLY_METHODS else 'execution'


def _aqef_grade_gate(score: float, grade: str, evidence_scope: str | None, latency_ms) -> tuple[float, str]:
    """Enforce AQEF-30 Grade A: execution evidence, latency below 2000 ms and a score of at least 90."""
    if grade != 'A':
        return score, grade
    try:
        lat = float(latency_ms) if latency_ms is not None else None
    except (TypeError, ValueError):
        lat = None
    if str(evidence_scope or '').lower() == 'execution' and lat is not None and lat < 2000.0 and score >= 90.0:
        return score, grade
    return round(min(score, 89.4), 1), 'B'


def compute_aqef_score_and_grade(
    *,
    kind: str | None,
    is_success: int | bool | None,
    status_code: int | None,
    latency_ms: float | int | None,
    evidence_scope: str | None = None,
    connection_version_id: str | None = None,
    executed_at: float | None = None,
    execution_finished_at: float | None = None,
    pros: list | None = None,
    cons: list | None = None,
    health_status: str | None = None,
    existing_grade: str | None = None,
    existing_score: float | None = None,
    resource_grade: str | None = None,
    jitter_ms: float | None = None,
) -> tuple[float, str]:
    """Compute AQEF-30 5-Layer composite score (0.0-100.0) and canonical letter grade ('A'..'D')."""
    canon_grade = normalize_eval_grade(existing_grade) or normalize_eval_grade(resource_grade)

    if existing_score is not None:
        try:
            s_val = float(existing_score)
            if math.isfinite(s_val) and 0.0 < s_val <= 100.0:
                if not canon_grade:
                    canon_grade = 'A' if s_val >= 90.0 else 'B' if s_val >= 75.0 else 'C' if s_val >= 60.0 else 'D'
                return _aqef_grade_gate(round(s_val, 1), canon_grade, evidence_scope, latency_ms)
        except (ValueError, TypeError):
            pass

    ok = bool(is_success in (1, True))

    # Layer 1: Document Control & Cryptographic Provenance (15%)
    if connection_version_id and executed_at and execution_finished_at:
        l1 = 100.0
    elif executed_at and execution_finished_at:
        l1 = 88.0
    else:
        l1 = 78.0

    # Layer 2: Protocol Contract Conformance (25%)
    if not ok:
        l2 = 35.0
    else:
        l2 = 100.0 if status_code in (200, 401, 402) else 76.0
        cons_text = ' '.join(str(c).lower() for c in (cons or []))
        if 'no description' in cons_text:
            l2 -= 4.0
        if 'no input schema' in cons_text:
            l2 -= 5.0
        if 'declares no skills' in cons_text or 'does not declare' in cons_text:
            l2 -= 4.0
        l2 = max(60.0, l2)

    # Layer 3: Execution Reliability & Latency Telemetry (30%)
    if not ok:
        l3 = 30.0
    else:
        l3 = 100.0
        lat = float(latency_ms) if (latency_ms is not None and latency_ms >= 0) else 600.0
        if lat > 250.0:
            l3 -= min(22.0, (lat - 250.0) * 0.0055)
        if jitter_ms is not None and jitter_ms > 80.0:
            l3 -= min(8.0, (jitter_ms - 80.0) * 0.008)
        scope = str(evidence_scope or '').lower()
        if scope == 'transport':
            l3 -= 2.5
        elif scope == 'legacy':
            l3 -= 5.0
        l3 = max(55.0, l3)

    # Layer 4: Safety & Policy Quarantine (15%)
    h_stat = str(health_status or 'healthy').lower()
    l4 = 100.0 if h_stat in ('healthy', 'reachable') else 72.0

    # Layer 5: Consumability & Actionable UX (15%)
    l5 = 100.0 if (pros and cons) else 86.0

    raw_score = 0.15 * l1 + 0.25 * l2 + 0.30 * l3 + 0.15 * l4 + 0.15 * l5

    if not ok:
        final_score = round(min(55.0, raw_score), 1)
        return final_score, canon_grade if canon_grade in ('C', 'D') else 'D'

    if canon_grade == 'A':
        final_score = round(max(90.0, min(99.4, raw_score)), 1)
    elif canon_grade == 'B':
        # Map variation within Grade B band (78.0 - 89.4)
        b_mapped = 78.0 + ((max(70.0, min(100.0, raw_score)) - 70.0) / 30.0) * 11.4
        final_score = round(max(78.0, min(89.4, b_mapped)), 1)
    elif canon_grade == 'C':
        final_score = round(max(60.0, min(77.9, raw_score - 15.0)), 1)
    elif canon_grade == 'D':
        final_score = round(max(20.0, min(59.9, raw_score - 35.0)), 1)
    else:
        final_score = round(max(0.0, min(99.4, raw_score)), 1)
        canon_grade = (
            'A' if final_score >= 90.0 else
            'B' if final_score >= 75.0 else
            'C' if final_score >= 60.0 else 'D'
        )

    return _aqef_grade_gate(final_score, canon_grade, evidence_scope, latency_ms)


def lint(report: dict, now: float | None = None) -> list[str]:
    """Return a list of policy violations (R1~R8) for a report dict (empty list means clean)."""
    problems = []
    if now is None:
        now = time.time()

    # R1: English only / zero Hangul in public text fields
    for key in ('title', 'summary', 'content_md', 'workflow_recommendation', 'tags'):
        text = str(report.get(key) or '')
        if HANGUL.search(text):
            problems.append(f'R1: {key} contains Hangul')

    # R2: Zero-leakage policy (no internal IPs, ports, localhost, debug traces)
    for key in ('title', 'summary', 'content_md', 'workflow_recommendation', 'tags'):
        text = str(report.get(key) or '')
        if PRIVATE.search(text):
            problems.append(f'R2: {key} contains private/infra text')

    # R3: Consistency & zero self-contradiction
    md = str(report.get('content_md') or '')
    pros_list = report.get('pros') if isinstance(report.get('pros'), list) else []
    cons_list = report.get('cons') if isinstance(report.get('cons'), list) else []
    cons_text = ' '.join(str(c) for c in cons_list)

    # A2A version contradiction check
    if 'does not declare a protocol version' in cons_text.lower():
        if '| Protocol | A2A v' in md:
            problems.append('R3: Contradiction: Cons claims no protocol version but table declares concrete A2A version')

    # MCP description contradiction check
    agent_desc = str(report.get('agent_description') or '').strip()
    if agent_desc and 'The provider published no description.' in md:
        problems.append('R3: Contradiction: Agent has catalog description but content claims provider published no description')

    # Summary vs is_success consistency
    is_success = report.get('is_success')
    summary = str(report.get('summary') or '').lower()
    if is_success == 1 and 'failed' in summary and 'passed' not in summary:
        problems.append('R3: Contradiction: is_success=1 but summary states failed')
    elif is_success == 0 and 'passed' in summary and 'failed' not in summary:
        problems.append('R3: Contradiction: is_success=0 but summary states passed')

    # R4: Markdown structure requirements
    if '### Pros' not in md or '### Cons' not in md:
        problems.append('R4: Missing Pros/Cons sections')
    if report.get('source') == 'verification_probe':
        for sec in ('## Verification Summary', '## Measured Facts', '## Scope'):
            if sec not in md:
                problems.append(f'R4: Missing markdown section {sec}')

    # R5: Standardized test method
    test_method = report.get('test_method')
    if test_method not in CANONICAL_TEST_METHODS:
        problems.append(f'R5: Non-canonical test method: {test_method}')

    # R6: Standardized evaluation grade
    grade = report.get('eval_grade')
    if grade is not None and grade not in CANONICAL_GRADES:
        problems.append(f'R6: Non-canonical eval_grade: {grade}')

    # R7: Execution timestamps
    ex = report.get('executed_at')
    fin = report.get('execution_finished_at')
    if ex is not None or fin is not None:
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in (ex, fin)) or not (0 < ex <= fin <= now + 15):
            problems.append(f'R7: Invalid execution timestamps ({ex}, {fin})')

    # R8: No broken placeholders or unsubstantiated claims
    if '[Retired gateway reference]' in md or '[Retired gateway reference]' in str(report.get('summary') or ''):
        problems.append('R8: Contains [Retired gateway reference] artifact')

    # R9: Zero excluded / quarantined / review / commercial-spam agents
    sec_status = str(report.get('target_eval_security') or '').lower()
    if sec_status in ('quarantine', 'review', 'quarantined'):
        problems.append(f'R9: Target has excluded security status: {sec_status}')
    if report.get('target_active') is not None and report.get('target_active') != 1:
        problems.append(f"R9: Target is inactive (active={report.get('target_active')})")
    if report.get('target_inactive_reason'):
        problems.append(f"R9: Target has inactive reason: {report.get('target_inactive_reason')}")

    return problems
