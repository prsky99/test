"""Task-level evidence from real gateway calls (2026-11-11, PM: "a tool confirmed to work ranks higher").

Connection checks marked almost every candidate verified_working, while the answers failed the task:
a translate tool answered {"error": "translation failed"} (real task p10), an A2A agent answered
"Provide an API key ..." (a07). Every tools/call and message/send that passes through our gateway is
classified here from the answer itself and kept per listing for 7 days in the shared Redis store, so
both frontend slots and restarts see it. The real-task scorer calls through the same gateway, so its
results count as well. Nothing about the caller, the arguments or the answer text is stored: only
counts of succeeded, failed and needs_key, and the time of the last one.

Recommendation order uses it (gateway_exposure and fast_chat): a listing whose recent calls only
failed, or that asked for a key, follows the others; one whose calls succeeded leads among equals.
"""
import hashlib
import json
import os
import re
import time

TTL = 7 * 86400
KEY = 'task-outcome:v1:'
FAILED = re.compile(r"""^\s*(?:error|failed|failure|exception|invalid|unknown|not\s+found|unavailable|internal\s+server)\b
  | \b(?:translation|request|call|lookup|search|conversion|extraction)\s+failed\b
  | \bunknown\s+(?:category|parameter|tool|argument|method)\b""", re.I | re.X)
NEEDS_KEY = re.compile(r"""\b(?:provide|requires?|need|missing|invalid|supply)\b[^.]{0,40}
    \b(?:api[\s_-]?key|access\s+token|bearer|authorization\s+header|credentials?)\b
  | \b(?:sign[\s-]?in|log\s?in|subscribe|upgrade)\s+(?:is\s+)?(?:required|to\s+(?:continue|use|access))\b""", re.I | re.X)


# An answer that found nothing did not do the task (11-11: FinzData's "datasets matching your request:
# - none matched" for a time question counted as a success and led "time in New York" ahead of a time
# tool, real task p13; an author search answered {"returned":0,"total_matches":0}, p08).
EMPTY = re.compile(r"""\b(?:none|nothing)\s+(?:matched|was\s+found|found)\b
  | \bno\s+(?:results?|matches|data(?:sets?)?|records?|items?)\s+(?:were\s+|was\s+)?(?:found|matched|available)\b
  | \b(?:returned|found)\s+(?:0|no|zero)\s+(?:results?|matches|items|records)\b""", re.I | re.X)
EMPTY_COUNTS = ('returned', 'total_matches', 'total_results', 'result_count', 'match_count')


def _empty_json(value):
    """A JSON answer whose own count fields say nothing was found and whose lists are all empty."""
    if not isinstance(value, dict):
        return False
    counts = [value[k] for k in EMPTY_COUNTS if k in value]
    lists = [v for v in value.values() if isinstance(v, list)]
    return bool(counts) and all(type(c) is int and c == 0 for c in counts) and not any(lists)


def _text(output):
    """The answer text of an MCP result or an A2A message, capped."""
    if not isinstance(output, dict):
        return '', False
    error = output.get('isError') is True
    parts = output.get('content') if isinstance(output.get('content'), list) else output.get('parts')
    texts = []
    for part in parts or ():
        if isinstance(part, dict):
            if isinstance(part.get('text'), str):
                texts.append(part['text'])
            elif isinstance(part.get('data'), dict):
                texts.append(json.dumps(part['data'])[:4000])
    if isinstance(output.get('structuredContent'), dict):
        texts.append(json.dumps(output['structuredContent'])[:4000])
    return '\n'.join(texts)[:8000], error


def classify(output):
    """'succeeded', 'failed' or 'needs_key' from the answer itself."""
    text, error = _text(output)
    if error:
        return 'needs_key' if NEEDS_KEY.search(text) else 'failed'
    if not text.strip():
        return 'failed'
    if NEEDS_KEY.search(text[:600]):
        return 'needs_key'
    try:
        value = json.loads(text.strip().split('\n')[0])
    except ValueError:
        value = None
    if isinstance(value, dict) and 'error' in value and len([k for k in value if value[k] not in (None, '', [], {})]) <= 3:
        return 'failed'
    if _empty_json(value) or EMPTY.search(text[:400]):
        return 'failed'
    if len(text) < 200 and FAILED.search(text):
        return 'failed'
    return 'succeeded'


def _key(rid):
    root = os.environ.get('AGENTCON_PROJECT_ROOT') or ''
    prefix = 'a2a:shared:' + hashlib.sha256(root.encode()).hexdigest()[:12] + ':' if root else 'a2a:local:'
    return prefix + KEY + str(int(rid))


def _hub():
    try:
        from ..infra.redis_hub import RedisHub
        hub = RedisHub.get_instance()
        return hub if hub.is_available() else None
    except Exception:
        return None


def record(rid, output, *, tool=None, now=None):
    """Classify one gateway answer and add it to the listing's (and the tool's) 7-day counts. Never raises."""
    try:
        return count(rid, classify(output), tool=tool, now=now)
    except Exception:
        return None


def count(rid, outcome, *, tool=None, now=None):
    """Add one already classified OUTCOME ('succeeded', 'failed' or 'needs_key') to the 7-day counts. Never raises.

    The edge Worker runs provider calls itself and reports only the outcome (11-14: real tasks a02 and p03 failed
    at the edge and were recommended again, because nothing reached these counts)."""
    try:
        if outcome not in ('succeeded', 'failed', 'needs_key'):
            return None
        hub = _hub()
        if hub is None or type(rid) is not int:
            return outcome
        key = _key(rid)
        value = hub.get_json(key)
        value = value if isinstance(value, dict) else {}
        value[outcome] = int(value.get(outcome) or 0) + 1
        if isinstance(tool, str) and tool:
            tools = value.get('tools') if isinstance(value.get('tools'), dict) else {}
            entry = tools.get(tool[:80]) if isinstance(tools.get(tool[:80]), dict) else {}
            entry[outcome] = int(entry.get(outcome) or 0) + 1
            tools[tool[:80]] = entry
            value['tools'] = dict(list(tools.items())[-20:])
        value['last'] = outcome
        value['at'] = float(now if now is not None else time.time())
        hub.set_json(key, value, ttl_seconds=TTL)
        return outcome
    except Exception:
        return None


def recent(rids):
    """{rid: counts} for listings with a recorded call; empty when the store is unavailable."""
    hub = _hub()
    found = {}
    if hub is None:
        return found
    for rid in rids:
        if type(rid) is not int:
            continue
        try:
            value = hub.get_json(_key(rid))
        except Exception:
            return found
        if isinstance(value, dict):
            found[rid] = value
    return found


def standing(counts, tool=None):
    """-1 for a listing (or its TOOL, when that tool was called) whose recent calls only failed or asked
    for a key, 1 for one that succeeded, else 0. A failure of another tool does not count against TOOL."""
    if not isinstance(counts, dict):
        return 0
    tools = counts.get('tools') if isinstance(counts.get('tools'), dict) else {}
    if isinstance(tool, str) and tool:
        if isinstance(tools.get(tool[:80]), dict):
            counts = tools[tool[:80]]
        elif tools:
            return 0  # other tools were called; nothing is known about this one
    good = int(counts.get('succeeded') or 0)
    bad = int(counts.get('failed') or 0) + int(counts.get('needs_key') or 0)
    if good == 0 and bad >= 1:
        return -1
    if good > 0 and good >= bad:
        return 1
    return 0
