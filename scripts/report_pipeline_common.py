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
