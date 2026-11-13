"""Bounded task constraints and refinements; metadata never grants authority."""
from dataclasses import dataclass
import re

MAX_TASK_CHARS = 2000
VERSION = 'chat-task-v1'
# Literal aliases are a fast path, not evidence of a provider capability.
ALIASES = {
    "\uacc4\uc57d\uc11c": "contract",
    "\ubd88\ub9ac\ud55c \uc870\ud56d": "unfavorable clauses",
    "\uc870\ud56d": "clauses",
    "\uacc4\uc57d \uac80\ud1a0": "contract review",
    "\ucc3e\uc544\uc8fc\ub294": "find",
    "\uadf8\uc911": "only",
    "\uadf8 \uc911": "only",
    "\uadf8\uac70": "same task",
    "\uadf8\ub9ac\uace0": "also",
    "\ub300\uc2e0": "instead",
    "\uc0c8 \uc791\uc5c5": "new task",
    "\ub2e4\ub978 \uc791\uc5c5": "different task",
    "\uc2a4\uce94\ub41c": "scanned",
    "\uc2a4\uce94": "scanned",
    "\ud45c\ub97c \ubcf4\uc874": "preserve tables",
    "\ud45c \ubcf4\uc874": "preserve tables",
    "\ud45c\ub97c \uc720\uc9c0": "preserve tables",
    "\uacc4\uc815 \uc5c6\uc774": "without an account",
    "\uac00\uc785 \uc5c6\uc774": "without signup",
    "API \ud0a4 \uc5c6\uc774": "without an API key",
    "\ud0c0\uc784\uc2a4\ud0ec\ud504": "timestamps",
    "\uc601\uc218\uc99d": "receipt",
    "\uccad\uad6c\uc11c": "invoice",
    "\uc1a1\uc7a5": "invoice",
    "\uc77c\ubcf8\uc5b4": "Japanese",
    "\ud55c\uad6d\uc5b4": "Korean",
    "\uc601\uc5b4": "English",
    "\uc2a4\ud398\uc778\uc5b4": "Spanish",
    "\ub3c5\uc77c\uc5b4": "German",
    "\ud504\ub791\uc2a4\uc5b4": "French",
    "\uc911\uad6d\uc5b4": "Chinese",
    "\ud78c\ub514\uc5b4": "Hindi",
    "\ubcc0\ud658": "convert",
    "\uc694\uc57d": "summarize",
    "\uae30\uc0c1": "weather",
    "\ubbf8\uc138\uba3c\uc9c0": "air quality",
    "\ucd08\ubbf8\uc138\uba3c\uc9c0": "air quality",
    "\uacf5\uae30\uc9c8": "air quality",
    "\ub300\uae30\uc9c8": "air quality",
    "\ub3c4\ucfc4": "Tokyo",
    "\uc11c\uc6b8": "Seoul"
}


def canonical_text(value):
    text = str(value or '')
    typos={'wether':'weather','forcast':'forecast','traslate':'translate'}
    text=re.sub(r'\b(?:wether|forcast|traslate)\b',lambda m:typos[m.group().lower()],text,flags=re.I)
    text=re.sub(r'\bpictures?\b', 'image', text, flags=re.I)
    for source, target in sorted(ALIASES.items(), key=lambda pair: -len(pair[0])):
        text = text.replace(source, ' ' + target + ' ')
    return ' '.join(text.split())


ALIASES.update({"\ubb34\ub8cc\ub9cc":"only without a charge", "\uba54\uc77c":"email",
                "\ud68c\uc758\ub85d":"meeting notes", "\ubcf4\ub0b4\uc918":"send"})

# Each constraint applies to one selected tool, never a union of unrelated tools.
CONSTRAINTS = (
    ('pdf_input', r'\bpdfs?\b', r'\bpdfs?\b|application/pdf'),
    ('ocr', r'\b(?:scanned|ocr)\b', r'\b(?:ocr|scanned|optical character recognition)\b'),
    ('table_structure', r'\b(?:preserve|retain|keep)\w*\b.{0,45}\b(?:tables?|structure)\b', r'\b(?:preserv\w*|retain\w*|structur\w*)\b.{0,45}\btable|\btable\b.{0,45}\b(?:preserv\w*|retain\w*|structur\w*)\b'),
    ('json_output', r'\b(?:into|as|return|output|in|to)\s+(?:structured\s+)?json\b', r'\bjson\b|application/json'),
    ('doi', r'\bdoi\b', r'\bdoi\b|digital object identifier'),
    ('timestamps', r'\btimestamps?\b', r'\btimestamps?\b|time[- ]coded'),
)
# A PDF input requirement needs the tool to read a PDF, not to produce one.
PDF_READS = re.compile(r'\b(?:from|of|in|within)\s+(?:an?\s+|the\s+|your\s+|any\s+)?(?:[\w-]+\s+){0,2}pdfs?\b'
                       r'|\bpdfs?\b[^.;\n]{0,40}\b(?:into|to)\s+(?:structured\s+)?(?:json|text|markdown|data|csv)\b'
                       r'|\b(?:read|extract|pars|ocr|analy[sz]|summari[sz]|split|redact|search|merg|combin|compress|rotat|sign|fill|annotat)\w*\b[^.;\n]{0,40}\bpdfs?\b', re.I)
PDF_WRITES = re.compile(r'\b(?:to|into|as)\s+(?:an?\s+)?(?:[\w-]+\s+){0,2}pdfs?\b(?!\s+(?:files?\s+)?(?:into|to)\b)'
                        r'|\bpdf\s+(?:synthesis|generation|rendering|export|creation)\b'
                        r'|\b(?:generat|creat|render|export|produc|print)\w*\b[^.;\n]{0,40}\bpdfs?\b', re.I)
AUTH_NONE = re.compile(r'\b(?:no|without|zero)\s+(?:an?\s+|any\s+)?(?:api[- ]?)?keys?\b|\bno api key required\b'
                       r"|\b(?:must|should|does|do|will|can|need|may)(?:\s+not|n['\u2019]t)\s+(?:require|need|ask for|use|have)\s+"
                       r'(?:an?\s+|any\s+)?(?:api[- ]?keys?|keys?|credentials?|authentication|auth)\b'
                       r'|\b(?:no|without)\s+(?:any\s+)?(?:authentication|auth|credentials?)\b|\bkey(?:less|[- ]free)\b', re.I)
ACCOUNT_NONE = re.compile(r'\b(?:no|without)\s+(?:an?\s+|any\s+)?(?:account|sign[- ]?up|oauth|login|registration)\b'
                          r"|\b(?:must|should|does|do|will|can|need|may)(?:\s+not|n['\u2019]t)\s+(?:require|need|ask for|have|use)\s+"
                          r'(?:an?\s+|any\s+)?(?:account|sign[- ]?up|oauth|login|registration)\b', re.I)
ZERO_CHARGE = re.compile(r'\bfree(?:\s+only)?\b|\b(?:no|without\s+(?:a\s+)?)\s*charge\b',re.I)
REFINE = re.compile(r'^(?:and|also|only|among those|of those|same task|instead|keep|preserve|retain|with|without)\b', re.I)
# "show only free options", "which of these is free?": a constraint on the list just given, not a new task.
LIST_REFERENCE = re.compile(r'^(?:(?:please\s+)?(?:show|list|give|keep|filter)(?:\s+me)?(?:\s+(?:only|just))?)\b'
                            r'|\b(?:these|those|them|ones|which of)\b', re.I)
NEW_TASK = re.compile(r'^(?:new task|different task|start over|now find|now search)\b[\s:,-]*', re.I)


@dataclass(frozen=True)
class TaskSpec:
    original: str
    positive: str
    excluded: tuple[str, ...]
    required: tuple[str, ...]
    operation: str = 'new'

    def state(self):
        from .task_conditions import requested
        return {'schema_version': 1, 'required': list(self.required), 'operation': self.operation,
                'conditions':requested(self.original)}


def parse(task, *, operation='new'):
    from .query_intent import interpret
    original = str(task or '').replace('\0', ' ').strip()
    if len(original) > MAX_TASK_CHARS:
        raise ValueError('Please keep the task within 2,000 characters; no conditions were discarded.')
    intent = interpret(canonical_text(original))
    required = [name for name, pattern, _ in CONSTRAINTS if re.search(pattern, intent.positive, re.I)]
    text = canonical_text(original)
    if AUTH_NONE.search(text): required.append('no_api_key')
    if ACCOUNT_NONE.search(text): required.append('no_account')
    if ZERO_CHARGE.search(text): required.append('no_charge')
    return TaskSpec(original, intent.positive, intent.excluded, tuple(required), operation)


def merge(previous, current):
    """Refine an existing task only when the new turn explicitly refers to it."""
    current = str(current or '').strip()
    canonical = canonical_text(current)
    if NEW_TASK.match(canonical):
        return parse(NEW_TASK.sub('', canonical)), False
    constraint = AUTH_NONE.search(canonical) or ACCOUNT_NONE.search(canonical) or ZERO_CHARGE.search(canonical)
    refine = bool(previous and (REFINE.match(canonical) or re.search(r'\b(?:too|as well)\s*[.!?]?$', canonical, re.I)
                                or constraint and LIST_REFERENCE.search(canonical)))
    if not refine:
        return parse(current), False
    combined = str(previous).rstrip(' .') + '. ' + canonical
    return parse(combined, operation='refine'), True


def _schema_text(tool):
    schema = tool.get('inputSchema') or {}
    if not isinstance(schema, dict): schema = {}
    output = tool.get('outputSchema') or {}
    if not isinstance(output, dict): output = {}
    # Input fields can prove accepted input, not an output guarantee.
    def bounded_text(value):
        pending, parts, seen = [(value, 0)], [], set()
        while pending and len(parts) < 128:
            current, depth = pending.pop()
            if depth > 8: continue
            if isinstance(current, (dict, list)):
                if id(current) in seen: continue
                seen.add(id(current))
                if isinstance(current, dict):
                    for key, child in list(current.items())[:32]:
                        parts.append(str(key)[:80])
                        pending.append((child, depth+1))
                else:
                    pending.extend((child, depth+1) for child in current[:32])
            elif isinstance(current, str): parts.append(current[:256])
        return ' '.join(parts)[:16384]
    inputs = bounded_text(schema)
    outputs = bounded_text(output)
    if output.get('type') == 'object': outputs += ' JSON' 
    description = (str(tool.get('name') or '') + ' ' + str(tool.get('description') or '')).replace('_', ' ')
    return description[:4000], inputs, outputs


def tool_fit(spec, tool):
    """Three-state constraints using one current declared contract."""
    description, inputs, outputs = _schema_text(tool)
    matched, unknown, violated = [], [], []
    for key, _, proof in CONSTRAINTS:
        if key not in spec.required: continue
        text = description + (' ' + inputs if key == 'pdf_input' else ' ' + outputs if key == 'json_output' else '')
        negative = re.search(r'\b(?:no|without|cannot|does not support|not supported)\b[^.;\n]{0,40}(?:' + proof + ')', description, re.I)
        if negative:
            violated.append(key)
        elif key == 'pdf_input' and PDF_WRITES.search(description) and not (
                PDF_READS.search(description) or re.search(proof, inputs, re.I)):
            violated.append(key)  # e.g. "Convert HTML to a PDF", "PDF synthesis" produce PDFs
        elif re.search(proof, text, re.I):
            matched.append(key)
        else:
            unknown.append(key)
    return {'matched': matched, 'unknown': unknown, 'violated': violated,
            'status': 'mismatch' if violated else 'unknown' if unknown else 'match'}


def task_proof(tool_name, report, report_ok):
    """A resource-wide success does not imply the selected tool was exercised."""
    verified = bool(report_ok and isinstance(report, dict) and tool_name
                    and report.get('tool_name') == tool_name)
    return {'status': 'verified' if verified else 'not_recorded',
            'tool': tool_name or None, 'report_id': report.get('id') if verified else None,
            'verified_at': report.get('executed_at') if verified else None}


# 11-13 Chat answer-quality gate (figma-ko0, cve_scan-ko0): "\uc2a4\uce94" alone is the act of scanning; only
# "\uc2a4\uce94\ub41c" (a scanned PDF) is the adjective. Product and security words had no alias.
ALIASES.update({"\uc2a4\uce94": "scan", "\ud53c\uadf8\ub9c8": "figma", "\ub514\uc790\uc778": "design",
                "\ucde8\uc57d\uc810": "vulnerability", "\uc77d\uae30": "read", "\ud30c\uc77c": "file"})
