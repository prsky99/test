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
# A tool our gateway does not relay (an action tool such as send_email, 11-12 PM option b-1): the card says so and
# points at the provider's own website or repository; invocation URLs stay hidden at the response boundary.
UNRELAYED_NOTE = 'This tool performs an action, so the Agent Concierge gateway does not relay it.'


def unrelayed_note(name, source):
    """The public sentence for a recommendation whose chosen tool the gateway does not list."""
    if source:
        return UNRELAYED_NOTE + " Connect through the provider's own documentation: " + source
    return UNRELAYED_NOTE + ' Connect through the provider (' + (str(name or 'this provider')[:120]) + ') directly.'


def source_url(resource):
    """The provider's website, else its repository: https only, never an invocation binding."""
    import json
    from .connections import bindings
    details = (resource or {}).get('details') or {}
    try:
        details = json.loads(details) if isinstance(details, str) else details
    except ValueError:
        return None
    if not isinstance(details, dict):
        return None
    bound = bindings(resource)
    for key in ('website', 'repository'):
        value = details.get(key)
        if isinstance(value, str) and value.startswith('https://') and len(value) <= 300 and value not in bound \
                and not any(c in value for c in ' "<>') and '?' not in value and '@' not in value:
            return value
    return None
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


CURRENCIES = {'usd': ('dollar', 'usd'), 'krw': ('won', 'krw'), 'eur': ('euro', 'eur'), 'jpy': ('yen', 'jpy'),
              'gbp': ('pound', 'sterling', 'gbp'), 'cny': ('yuan', 'renminbi', 'cny'), 'inr': ('rupee', 'inr'),
              'ngn': ('naira', 'ngn'), 'cad': ('canadian', 'cad'), 'aud': ('australian', 'aud'),
              'chf': ('franc', 'chf'), 'mxn': ('peso', 'mxn'), 'brl': ('real', 'brl')}
CURRENCY_PAIR = re.compile(r'(?:^|[^a-z])([a-z]{3})[_\-]?(?:to[_\-]?)?([a-z]{3})(?:[_\-]|$)', re.I)


def _currency_mismatch(task, tool):
    """A converter fixed to one currency pair that the task does not ask for ("usd_ngn_convert" for won, p02)."""
    pair = CURRENCY_PAIR.search(tool.lower())
    if not pair or pair.group(1) not in CURRENCIES or pair.group(2) not in CURRENCIES:
        return False
    words = set(re.findall(r'[a-z]+', task.lower()))
    asked = {code for code, names in CURRENCIES.items() if words & set(names)}
    return bool(asked) and not asked <= {pair.group(1), pair.group(2)}


US_STATES = frozenset('''alabama alaska arizona arkansas california colorado connecticut delaware florida georgia
    hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota
    mississippi missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont
    virginia washington wisconsin wyoming'''.split())
PLACE_REGION = {'usa': 'us', 'america': 'us', 'american': 'us', 'nws': 'us', 'canada': 'ca', 'canadian': 'ca',
                'norway': 'no', 'norwegian': 'no', 'uk': 'gb', 'britain': 'gb', 'british': 'gb', 'england': 'gb',
                'london': 'gb', 'japan': 'jp', 'japanese': 'jp', 'tokyo': 'jp', 'korea': 'kr', 'korean': 'kr',
                'seoul': 'kr', 'germany': 'de', 'german': 'de', 'berlin': 'de', 'france': 'fr', 'french': 'fr',
                'paris': 'fr', 'australia': 'au', 'india': 'in', 'china': 'cn', 'chinese': 'cn', 'brazil': 'br',
                'mexico': 'mx', 'spain': 'es', 'italy': 'it', 'netherlands': 'nl', 'sweden': 'se', 'finland': 'fi',
                'denmark': 'dk', 'ireland': 'ie', 'singapore': 'sg', 'taiwan': 'tw'}
PLACE_PAIRS = {'united states': 'us', 'new york': 'us', 'north carolina': 'us', 'south carolina': 'us',
               'new jersey': 'us', 'new mexico': 'us', 'united kingdom': 'gb', 'south korea': 'kr'}
COVERAGE = re.compile(r"\b(?:covers?|covering|only\s+(?:for|in)|limited\s+to|available\s+only\s+in|for\s+any)\s+"
                      r"(?:the\s+)?([a-z]+(?:\s+[a-z]+)?)", re.I)


def task_region(task):
    """The one region a task names ('us' for a US state), or None when it names none or several."""
    text = ' ' + str(task or '').lower() + ' '
    found = {code for pair, code in PLACE_PAIRS.items() if ' ' + pair + ' ' in text}
    for word in re.findall(r'[a-z]+', text):
        if word in US_STATES:
            found.add('us')
        elif word in PLACE_REGION:
            found.add(PLACE_REGION[word])
    return found.pop() if len(found) == 1 else None


def _coverage(text):
    regions = set()
    for match in COVERAGE.finditer(text):
        phrase = match.group(1).lower()
        for pair, code in PLACE_PAIRS.items():
            if phrase.startswith(pair):
                regions.add(code)
        first = phrase.split()[0]
        if first in PLACE_REGION:
            regions.add(PLACE_REGION[first])
        elif first in ('us', 'u.s'):
            regions.add('us')
    return regions


def region_mismatch(task, item, descriptions=None, regions=None):
    """True when the task names one region and the listing clearly serves another (11-11: MET Norway's
    alerts led "weather alerts in California"). A listing without a stated region is not moved."""
    wanted = task_region(task)
    if not wanted or not isinstance(item, dict):
        return False
    chosen = (item.get('tools') or [''])[0] or ''
    stated = {code for code in str(regions or '').strip(',').split(',') if code}
    stated |= _coverage(str((descriptions or {}).get(chosen) or ''))
    if not stated or stated & {'global', 'world', 'worldwide', wanted}:
        return False
    return True


# The task hands over a link (a YouTube video, a web page) and the tool only takes a file, a stored
# upload or base64 bytes (11-11 real task p15: all three recommendations for "the transcript of a
# YouTube video" were audio transcribers that read a local file, an upload reference or base64 audio).
URL_TASK = re.compile(r'https?://|\byoutu(?:\.be|be)\b|\b(?:web\s?page|url|link)\b', re.I)
URL_INPUT = re.compile(r'ur[li]|link|href|youtube|video[\s_-]?id|web\s?page|website|domain', re.I)
FILE_INPUT = re.compile(r'file|path|base64|b64|audio[\s_-]?(?:data|bytes)|upload|bytes|blob|attachment', re.I)


def input_mismatch(task, item):
    """True when the task gives a link and the chosen tool's own inputs only take files or bytes."""
    if not isinstance(item, dict) or not isinstance(task, str) or not URL_TASK.search(task):
        return False
    chosen = (item.get('tools') or [''])[0] or ''
    schema = next((t.get('inputSchema') for t in item.get('tools_schema') or ()
                   if isinstance(t, dict) and t.get('name') == chosen), None)
    properties = schema.get('properties') if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return False
    def text(name, spec):
        return str(name) + ' ' + (str(spec.get('description') or '') if isinstance(spec, dict) else '')
    if any(URL_INPUT.search(text(name, spec)) and not FILE_INPUT.search(str(name)) for name, spec in properties.items()):
        return False
    return any(FILE_INPUT.search(text(name, spec)) for name, spec in properties.items())


def wrong_direction(task, item, descriptions=None):
    """True when the selected tool does the task the other way round."""
    if not isinstance(item, dict) or not isinstance(task, str):
        return False
    chosen = (item.get('tools') or [''])[0] or ''
    text = str(chosen) + ' ' + str((descriptions or {}).get(chosen) or next(
        (t.get('description') for t in item.get('tools_schema') or () if isinstance(t, dict) and t.get('name') == chosen), '') or '')
    if EXTRACT_TASK.search(task) and MAKE_PDF_TOOL.search(text) and not EXTRACT_TOOL.search(text):
        return True
    if _currency_mismatch(task, str(chosen)):
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
                if (wrong_direction(task, item, texts) or region_mismatch(task, item, texts, self.regions(item))
                        or input_mismatch(task, item)):
                    item['task_standing'] = min(score, -1)
                    item['direction_mismatch'] = True
                if not self.tool_listed(item, chosen):
                    # The chosen tool is not on the gateway's tools/list (11-11 real task a12: tollbooth's
                    # air_quality_index is not an admitted tool, so the caller could only try another one).
                    item['task_standing'] = min(item['task_standing'], -1)
                    item['tool_unlisted'] = True
                    facts = self._facts(item)
                    item['connection_note'] = unrelayed_note(item.get('name'), facts[4] if facts and len(facts) > 4 else None)
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

    def tool_listed(self, item, tool):
        """False only when an MCP server's gateway tools/list is known and leaves TOOL out."""
        facts = self._facts(item)
        if facts is None or len(facts) < 4 or facts[3] is None or not isinstance(tool, str) or not tool:
            return True  # an unreadable or missing row is judged by the recommender as before
        return tool in facts[3]

    def regions(self, item):
        facts = self._facts(item)
        return None if facts is None or len(facts) < 3 else facts[2]

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
            listed = frozenset(str(spec.get('name')) for spec in specs if safe_registered_tool(spec))
            value = (bool(resource) and bool(listed),
                     {str(spec.get('name')): str(spec.get('description') or '')[:4000]
                      for spec in specs if isinstance(spec, dict)},
                     str((resource or {}).get('regions') or ''), listed if resource else None,
                     source_url(resource) if resource else None)
        except Exception:
            return None  # an unreadable row is judged by the recommender as before
        with self._lock:
            self._cache[rid] = (now + CACHE_SECONDS, value)
            self._cache.move_to_end(rid)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return value
