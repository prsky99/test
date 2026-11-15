"""What an outside recommendation request is for, from its question text (PM 11-16 08:2x, connect-gap plan A).

11-15: 74 outside recommendation requests led to no gateway connection, but most of them were not tasks at all:
liveness pings, partnership and promotion messages, a red-team audit and the fixed texts of directory monitors
(reports/connect-gap-2026-11-16). The north star's denominator is the requests that carry a task; the others are
counted beside it under their own names, never dropped.

intent(text) -> one of
- 'task'      a request that names something to get done (the denominator)
- 'liveness'  ping / hi / "reply with OK" / "what can you do?": a check that the agent answers
- 'outreach'  partnership, referral, alliance and promotion messages
- 'security'  red-team and prompt-injection audits
- 'fixture'   the fixed texts monitors send on a timer ("Structured discovery request", "audit-fixture")
- 'command'   our own follow-up words sent without a task ("what's new", "details 1", "get updates for this task")
- 'empty'     no text
The phrase lists live in traffic_classes.json (ask_* keys) so they change without code. Only the class is kept;
the text is read in memory and never stored.
"""
import json
import re

from .traffic import _classes

MAX_TEXT = 2000
INTENTS = ('task', 'liveness', 'outreach', 'security', 'fixture', 'command', 'empty')
_SPACE = re.compile(r'\s+')
_EDGE = re.compile(r'^[\s"\'`.!?¡¿,;:()\[\]-]+|[\s"\'`.!?,;:()\[\]-]+$')


def _phrases(name):
    return [w.lower() for w in _classes().get(name, []) if isinstance(w, str) and w]


LIVENESS_EXACT = set(_phrases('ask_liveness_exact'))
LIVENESS_CONTAINS = _phrases('ask_liveness_contains')
OUTREACH = _phrases('ask_outreach_contains')
SECURITY = _phrases('ask_security_contains')
FIXTURE_EXACT = set(_phrases('ask_fixture_exact'))
COMMAND = [re.compile(p, re.I) for p in _classes().get('ask_command_patterns', []) if isinstance(p, str) and p]


def intent(text):
    if not isinstance(text, str):
        return 'empty'
    plain = _SPACE.sub(' ', text[:MAX_TEXT]).strip().lower()
    core = _EDGE.sub('', plain)
    if not core:
        return 'empty'
    if core in FIXTURE_EXACT:
        return 'fixture'
    if any(p in plain for p in SECURITY):
        return 'security'
    if any(p in plain for p in OUTREACH):
        return 'outreach'
    if core in LIVENESS_EXACT or any(p in plain for p in LIVENESS_CONTAINS):
        return 'liveness'
    if any(p.fullmatch(core) for p in COMMAND):
        return 'command'
    return 'task'


def _a2a_text(params):
    message = params.get('message') if isinstance(params, dict) else None
    parts = message.get('parts') if isinstance(message, dict) else None
    if not isinstance(parts, list):
        return None
    texts = [p.get('text') for p in parts if isinstance(p, dict) and isinstance(p.get('text'), str)]
    return ' '.join(texts) if texts else None


def request_text(surface, body):
    """The question text of one recommendation request body (A2A message/send, MCP find_agents/chat/search, REST
    chat), or None. Explore requests are typed searches and are read as tasks without their text."""
    if not body:
        return None
    try:
        data = json.loads(body[:65536])
    except (ValueError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    params = data.get('params') if isinstance(data.get('params'), dict) else {}
    if surface == 'a2a':
        return _a2a_text(params)
    if surface == 'rest_chat':
        value = data.get('message') or data.get('text') or data.get('task')
        return value if isinstance(value, str) else None
    arguments = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
    for key in ('task', 'query', 'message', 'q', 'need'):
        if isinstance(arguments.get(key), str):
            return arguments[key]
    return None


def request_intent(surface, body):
    if surface == 'explore':
        return 'task'
    return intent(request_text(surface, body))
