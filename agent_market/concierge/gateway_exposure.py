"""Leave out MCP servers whose gateway lists no callable tool while another choice remains (2026-11-10).

A first-time agent asked for "PDF to text" and got Clearcrawl first, whose gateway tools/list
was empty: its two tools fail the gateway's safety and schema checks. On 11-10, 17,253 of
40,275 live MCP servers listed no tool through the gateway (14,208 never surveyed, 3,045
surveyed but every tool filtered). This wrapper applies the gateway's own rule
(tools_for + safe_registered_tool) to the recommendations and moves those servers last.

It sits outside selection.py and execution_policy.py on purpose: both are part of the Explore
document policy hash, and changing them would rebuild every search document.
"""
import re
import threading
import time
from collections import OrderedDict

from .execution_policy import safe_registered_tool, tools_for
from .schema_cache import install as _install_schema_cache

_install_schema_cache()  # 16,384 schema checks remembered instead of 4,096 (11-11 Chat profile)
from .retrieval_metrics import stage

EXTRA = 3  # look this many further, so a demoted server is replaced rather than only moved

# A tool its own description restricts to a paid plan or an account (11-11 PM: "convert a pdf invoice
# into structured json fields" put extract_invoice_data first, "Requires Team tier or above"). The
# server itself needs no authorization, so the auth survey cannot see it; the selected tool's text can.
PAID = re.compile(r"""\b(?:requires?|needs?|only\s+(?:available\s+)?(?:on|with|for|in))\s+(?:an?\s+|the\s+)?
    (?:paid|pro|premium|team|business|enterprise|plus|starter|growth|scale)\b
  | \b(?:paid|pro|premium|enterprise)\s+(?:tier|plan|subscription)s?\s+(?:only|required)\b
  | \b(?:subscription|paid\s+plan|api\s+credits?)\s+(?:is\s+|are\s+)?required\b
  | \bpay[\s-]per[\s-](?:call|use|request)\b
  | \bupgrade\s+(?:to|your\s+plan)\b
  | \b\d+\s+credits?\b
  | (?:^|[.;:]\s*)paid(?:\s+(?:api|service|only|plan))?\s*(?:[.;]|$)""", re.I | re.X)
ACCOUNT = re.compile(r"""\b(?:requires?|needs?)\s+(?:an?\s+|your\s+(?:own\s+)?)?
    (?:api[\s_-]?key|access\s+token|oauth|login|sign[\s-]?in|account)\b""", re.I | re.X)
SHOWN = 3  # recommendations a visitor sees
PAID_NOTE = 'Paid plan: the description of this tool says it needs a paid plan.'
ACCOUNT_NOTE = 'Account: the description of this tool says it needs your own key or account.'


def order_key(item):
    """Free and not failing first, then recent real successes first; a stable sort keeps the rest's order."""
    standing = item.get('task_standing') if isinstance(item, dict) else 0
    standing = standing if type(standing) is int else 0
    return (bool(isinstance(item, dict) and item.get('access_note')), standing < 0, standing <= 0)


# The task asks to take data out of a document; a tool that makes the document does the reverse
# (11-11: "convert a pdf invoice into structured json fields" -> "Convert document details to an
# invoice ... PDF"). Geocoding an address is not reverse geocoding (real task a05).
EXTRACT_TASK = re.compile(r"""\b(?:extract|parse|ocr)\b
  | \b(?:convert|turn)\b[^.]{0,60}\b(?:into|to)\s+(?:structured\s+)?(?:json|fields|data|text|csv|markdown)\b""", re.I | re.X)
EXTRACT_TOOL = re.compile(r'\b(?:extract|parse|read|ocr|recogni[sz]e)', re.I)
MAKE_PDF_TOOL = re.compile(r"""^\s*(?:create|generate|make|render|build|compose|produce)\b
  | \bto\s+(?:an?\s+)?[a-z ,]{0,60}\bpdfs?\b""", re.I | re.X)
REVERSE_TOOL = re.compile(r'\breverse[\s_-]?geocod', re.I)
FORWARD_TASK = re.compile(r'\bgeocod|\baddress(?:es)?\s+(?:to|into)\s+(?:lat|coord|gps)', re.I)
REVERSE_TASK = re.compile(r"""\breverse\b
  | \b(?:coordinates?|lat(?:itude)?\b[\s/,&-]*(?:and\s+)?(?:lon|lng|long)(?:itude)?)\s+(?:to|into)\s+(?:an?\s+)?(?:street\s+)?address""", re.I | re.X)


def wrong_direction(task, item, descriptions=None):
    """True when the selected tool does the task the other way round."""
    if not isinstance(item, dict) or not isinstance(task, str):
        return False
    chosen = (item.get('tools') or [''])[0] or ''
    text = str(chosen) + ' ' + str((descriptions or {}).get(chosen) or next(
        (t.get('description') for t in item.get('tools_schema') or () if isinstance(t, dict) and t.get('name') == chosen), '') or '')
    if EXTRACT_TASK.search(task) and MAKE_PDF_TOOL.search(text) and not EXTRACT_TOOL.search(text):
        return True
    return bool(FORWARD_TASK.search(task) and not REVERSE_TASK.search(task) and REVERSE_TOOL.search(text))


def access_note(item, descriptions=None):
    """PAID_NOTE or ACCOUNT_NOTE when the selected tools or the listing say so, else None.
    DESCRIPTIONS (name -> full text) replaces the shortened tools_schema text when known."""
    if not isinstance(item, dict):
        return None
    chosen = set(item.get('tools') or ())
    texts = [str(item.get('description') or '')]
    if descriptions:
        texts += [text for name, text in descriptions.items() if not chosen or name in chosen]
    else:
        for tool in item.get('tools_schema') or ():
            if isinstance(tool, dict) and (not chosen or tool.get('name') in chosen):
                texts.append(str(tool.get('description') or ''))
    text = ' '.join(texts)[:20000]
    if PAID.search(text):
        return PAID_NOTE
    if item.get('kind') != 'x402' and ACCOUNT.search(text):
        return ACCOUNT_NOTE
    return None
CACHE_SIZE = 4096
CACHE_SECONDS = 600


class ExposedFirstRecommender:
    def __init__(self, recommender, store):
        self._recommender = recommender
        self._store = store
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)  # never recurse while copy() builds an empty instance
        return getattr(self._recommender, name)

    def __copy__(self):
        # front.chat copies the recommender and binds the copy to a request store.
        from copy import copy
        return ExposedFirstRecommender(copy(self._recommender), self._store)

    @property
    def store(self):
        return self._store

    @store.setter
    def store(self, value):
        self._store = value
        self._recommender.store = value

    def search(self, task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None):
        search = self._recommender.search
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 600:
            return search(task, kind, auth_pref, limit, offset, exclude, hint, category)
        wider = min(600 - min(offset, 599), limit + EXTRA)
        items = search(task, kind, auth_pref, max(limit, wider), offset, exclude, hint, category)
        with stage('exposure'):
            exposed = [item for item in items if self.callable(item)]
            ranked = exposed or items
            from .task_outcomes import recent, standing
            outcomes = recent([item.get('id') for item in ranked if isinstance(item, dict)])
            for item in ranked:
                texts = self.tool_texts(item)
                note = access_note(item, texts)
                chosen = (item.get('tools') or [None])[0]
                counts = outcomes.get(item.get('id'))
                score = standing(counts, chosen)
                needs_key = isinstance(counts, dict) and score < 0 and int(
                    ((counts.get('tools') or {}).get(chosen) or counts).get('needs_key') or 0) > 0
                if note is None and needs_key:
                    note = ACCOUNT_NOTE  # the agent itself asked our gateway for a key
                if note is not None:
                    item['access_note'] = note
                item['task_standing'] = score
                if wrong_direction(task, item, texts):
                    item['task_standing'] = min(score, -1)
                    item['direction_mismatch'] = True
            ranked = sorted(ranked, key=order_key)
            free = [item for item in ranked if order_key(item)[:2] == (False, False)]
        # Leave them out while any callable choice remains: Chat re-ranks a ten-item shortlist by
        # meaning, which moved a demoted server back to first (11-10 deploy check). A tool that needs
        # a paid plan or the caller's own account, whose recent calls through our gateway only failed,
        # or that does the task the other way round leaves the list while at least SHOWN other choices
        # remain (a demoted one came back first after the re-rank, 11-11); otherwise it follows them.
        if len(free) >= min(limit, SHOWN):
            return free[:limit]
        return ranked[:limit]

    def callable(self, item):
        """False only for an MCP server whose gateway tools/list would be empty."""
        facts = self._facts(item)
        return True if facts is None else facts[0]

    def tool_texts(self, item):
        """Full descriptions of the server's tools by name (the recommendation shortens them), or None."""
        facts = self._facts(item)
        return None if facts is None else facts[1]

    def _facts(self, item):
        if not isinstance(item, dict) or item.get('kind') != 'mcp':
            return None
        rid = item.get('id')
        if type(rid) is not int:
            return None
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(rid)
            if cached is not None and cached[0] > now:
                self._cache.move_to_end(rid)
                return cached[1]
        try:
            resource = self._store.resource(rid)
            specs = tools_for(resource) if resource else []
            value = (bool(resource) and any(safe_registered_tool(spec) for spec in specs),
                     {str(spec.get('name')): str(spec.get('description') or '')[:4000]
                      for spec in specs if isinstance(spec, dict)})
        except Exception:
            return None  # an unreadable row is judged by the recommender as before
        with self._lock:
            self._cache[rid] = (now + CACHE_SECONDS, value)
            self._cache.move_to_end(rid)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return value
