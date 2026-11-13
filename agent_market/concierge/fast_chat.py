"""Up to three concise choices, selected only from recorded verification data."""
import json
import re
import threading
import time
from datetime import datetime, timezone

from .engine import Concierge, Reply, NAME, clean_task
from .selection import search_terms
from .protocols import requested_protocol
from ..gateway.classify import classify
from ..observability import journal_for
from .chat_query_rewrite import SUMMARY_MIN_CHARS


DISPLAY_RESTRICTED = re.compile(
    r'\b(?:free|paid|pay|micro[ -]?payments?|pay[ -]?per[ -]?call|payments?|billing|pricing|prices?|fees?|costs?|charges?|subscriptions?|premium|wallets?|USDC)\b'
    r'|[$\u20ac\u00a3\u20a9]|[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]',
    re.I,
)

from urllib.parse import urlsplit

GENERIC_NAMES = frozenset({'weather', 'ticker', 'tickers', 'stock', 'stocks', 'quote', 'quotes', 'translate', 'translator', 'translation', 'chat', 'search', 'api', 'agent', 'bot'})


def refined_agent_name(item):
    name = str(item.get('name') or '').strip()
    lowered = name.lower()
    if not name or lowered in GENERIC_NAMES or lowered.endswith((':ticker', ':symbol')) or name.startswith('http'):
        desc = str(item.get('description') or '')
        m = re.match(r"^([A-Z0-9][A-Za-z0-9\s-]{2,35}?)(?:\s+(?:alerts|forecasts?|api|service|for|is|provides|returns|enables)\b|[.,;])", desc)
        if m and len(m.group(1).split()) <= 4:
            cand = m.group(1).strip()
            if cand.lower() not in GENERIC_NAMES:
                return cand
        url = item.get('url') or item.get('usage_endpoint') or ''
        host = urlsplit(url).hostname or ''
        parts = [p for p in host.split('.') if p not in ('www', 'api', 'mcp', 'agent', 'biz', 'com', 'io', 'dev', 'net', 'org')]
        prefix = parts[0].replace('-', ' ').title() if parts else ''
        tools = item.get('tools') or []
        base = name if (name and lowered not in GENERIC_NAMES and not lowered.endswith((':ticker', ':symbol'))) else (tools[0].replace('_', ' ').title() if tools else 'Agent')
        return f"{prefix} {base}".strip() if prefix else base
    return name


DATABASE_PRODUCTS = frozenset(('postgres', 'postgresql', 'mysql', 'mariadb', 'sqlite', 'mongodb', 'redis',
                               'supabase', 'clickhouse', 'snowflake', 'bigquery', 'dynamodb'))


def retrieval_text(task):
    """Name the capability a bare product request implies, for the catalog search only.

    "PostgreSQL MCP server" names a database product and no task, so it matched setup
    generators by name; database tools say "database" or "SQL". "email sending" ranked
    validation tools whose text mentions sending ahead of tools that send."""
    from .selection import capability_terms
    # Verb first: "email send" let any send_* tool (feedback, invites) match the request.
    # A URL is the task's input, not a capability: "give me the main text: https://…/news" found
    # nothing while the same request without it found page readers (11-11 real task p04).
    text = re.sub(r'(?:https?://|www\.)\S+', ' web page ', str(task or ''), flags=re.I)
    # "Need a tool that returns current price of BTC in USD as JSON": "returns" and "json" became
    # required capability words and nothing matched, while "current price of BTC in USD" finds price
    # tools (11-11 real task a02). What the tool returns is the capability; its format is a condition.
    framed = OUTPUT_FRAME.sub('', text)
    framed = OUTPUT_FORMAT.sub('', framed)
    if framed.strip():
        text = framed
    unqualified = re.sub(r'\s{2,}', ' ', QUALIFIERS.sub(' ', text)).strip()
    if re.search(r'[^\W\d_]', unqualified):
        text = unqualified
    text = re.sub(r'\b([a-z]+)\s+sending\b', r'send \1', text, flags=re.I)
    text = re.sub(r'\bsending\b', 'send', text, flags=re.I)
    # Tools say "postgres" (postgres__sql_read); the lexical index does not equate the two spellings.
    text = re.sub(r'\bpostgresql\b', 'postgres', text, flags=re.I)
    # "alert me on Telegram": the place after "on" is the channel, not a subject to drop.
    text = re.sub(r'\b(?:alert|notify|ping|message|tell)\s+(?:me|us|the team|my team)?\s*(?:on|via|through|in|over)\s+'
                  r'(telegram|slack|discord|whatsapp|teams)\b', r'send \1 message', text, flags=re.I)
    # "Context: a small shop. Requirement: compose a jingle. Nothing else is needed": the labelled
    # requirement is the capability; the original stays after "for" for its conditions (stage 1, 11-04).
    stated = STATED_REQUIREMENT.search(text)
    need = next((part for part in stated.groups() if part), '') if stated else ''
    if need and len(text) > len(need) + 20:
        text = need.strip() + ' for ' + text
    terms = capability_terms(text)
    if terms and set(terms) <= DATABASE_PRODUCTS:
        text += ' database'
    return text


OUTPUT_FRAME = re.compile(
    r'^\s*(?:i\s+)?(?:need|want|looking\s+for|find(?:\s+me)?|get(?:\s+me)?)\s+(?:an?\s+|the\s+|some\s+)?'
    r'(?:tool|agent|api|endpoint|mcp\s+server|server|service)\s+(?:that|which|to)\s+'
    r'(?:returns?|gives?|provides?|outputs?)\s+(?:me\s+|us\s+|back\s+)?', re.I)
OUTPUT_FORMAT = re.compile(r'\s+(?:as|in)\s+(?:a\s+)?(?:json|csv|xml|yaml)(?:\s+(?:format|object|response|output))?\s*[.!?]?\s*$', re.I)
# When or for whom, not what (PM 11-13 22:3x): "<Korean for translation> small business", "send email small business" and "invoice ocr small
# business" found nothing with these words required, fell to narrow -> split (2.2-4.1 s) and led with value_business,
# send_message_to_vendor and business_services; without them translate, send_email and invoice_ocr in 0.5-1.3 s.
# They stay in the task, so conditions and the answer still see them. "bulk" stays: batch processing is a capability.
QUALIFIERS = re.compile(r'\b(?:today|in\s+real[\s-]time|quickly|for\s+my\s+team|for\s+agents|(?:for\s+(?:a\s+|my\s+)?)?small\s+business(?:es)?)\b', re.I)


STATED_REQUIREMENT = re.compile(
    r'\b(?:requirements?|task|goal|objective|need)\s*:\s*([^.!?;:]{3,200})'
    r'|\bautomate\s+(?:one|a single|this|the next|the following)\s+step\s*:\s*([^.!?;:]{3,200})', re.I)


QUESTION_FORM = re.compile(r'^\s*(?:what|who|when|where|why|which|how (?:many|much|old|far|tall|long))\b', re.I)
FOCUS_SHORTLIST = 120
FOCUS_SHARE = 0.5
# Prepositions, times of day and relative dates qualify a request; they never name its capability.
QUALIFIER_WORDS = frozenset('across through between around along within near over under after before during via toward towards beside last next night tonight yesterday today tomorrow morning evening afternoon week weekend month year now'.split())


def capability_focus(store, engine, task, protocol=None):
    """The request's capability words that the retrieved candidates actually share, or None.

    A word found in fewer than half as many shortlisted listings as the most shared
    word names the subject the capability is applied to, not the capability. Only the
    listing's own compact text is read; nothing is selected here."""
    from .selection import capability_terms, _term_in
    from .discovery import candidates, enabled, normalize_task, ranking_text
    # The same retrieval the first search used; without an enabled engine there is none to repeat.
    if not enabled(engine):
        return None
    core = capability_terms(normalize_task(task))
    if len(core) < 2:
        return None
    # A capitalized word inside the request ("Times Square", "Amsterdam") names its subject.
    names = {word.lower() for word in re.findall(r"[A-Za-z][\w'-]*", task)[1:]
             if word[0].isupper() and not word.isupper()}
    try:
        rows = candidates(store, engine, task, kind=protocol, maximum=FOCUS_SHORTLIST, ranking_only=True)
    except Exception:
        return None
    texts = [row.get('_rank_text') if isinstance(row.get('_rank_text'), str) else ranking_text(row) for row in rows]
    if len(texts) < 5:
        return None
    shared = {term: sum(_term_in(term, text) for text in texts) for term in core}
    top = max(shared.values())
    kept = [term for term in core if top and shared[term] >= FOCUS_SHARE * top
            and term not in QUALIFIER_WORDS and term not in names]
    if not kept or len(kept) == len(core):
        return None
    # A word found across the whole catalog ("source", "data") cannot name a capability alone,
    # and one remaining word must itself be specific ("NBA scores last night" kept "scores").
    if all(catalog_share(store, term) > GENERIC_SHARE for term in kept):
        return None
    # One remaining word must be what the retrieval converged on, and specific in the catalog.
    if len(kept) == 1 and (shared[kept[0]] < SINGLE_CONVERGENCE * len(texts) or catalog_share(store, kept[0]) > SINGLE_SHARE):
        return None
    return ' '.join(kept)


NEIGHBOR_ROWS = 30          # listings closest to the request that vote on shared words
NEIGHBOR_SHARE = 0.3        # a word must appear in this share of them
NEIGHBOR_CATALOG_SHARE = 0.02  # and in no more than this share of the whole catalog
NEIGHBOR_WORDS = 2
NEIGHBOR_CLOSENESS = 0.73  # minimum request-to-tool similarity for an answer found this way
NEIGHBOR_STOP = frozenset('this that with from your their they have will what when where which into about using used '
                          'uses tool tools agent agents data api apis service services server mcp returns return get list '
                          'search find query results result information info based support supports provide provides '
                          'allows access'.split())


def neighbor_focus(store, engine, task, protocol=None):
    """Words the listings nearest the request share but the request never says, or None.

    Measured offline (11-05, production read-only) on Chat misses the canonical phrase would have
    answered: tuning 93 -> 54 answered, 42 right; holdout 32 -> 20 answered, 19 right. Only the
    listings' own compact text is read; the search that follows applies every usual gate."""
    from .selection import search_terms, FILLER
    from .discovery import candidates, enabled, ranking_text
    if not enabled(engine):
        return None
    try:
        rows = candidates(store, engine, task, kind=protocol, maximum=2 * NEIGHBOR_ROWS, ranking_only=True)
    except Exception:
        return None
    texts = [(row.get('_rank_text') if isinstance(row.get('_rank_text'), str) else ranking_text(row)).lower()
             for row in rows][:NEIGHBOR_ROWS]
    if len(texts) < 8:
        return None
    own = set(search_terms(task))
    counts = {}
    for text in texts:
        for word in set(re.findall(r'[a-z]{4,}', text)):
            if word not in NEIGHBOR_STOP and word not in FILLER and word not in own:
                counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
    picked = [word for word, count in ranked if count >= NEIGHBOR_SHARE * len(texts)
              and catalog_share(store, word) <= NEIGHBOR_CATALOG_SHARE][:NEIGHBOR_WORDS]
    return ' '.join(picked) or None


STRONG_MODEL = 'qwen3-embedding:0.6b'
STRONG_INSTRUCT = 'Instruct: Given a task an agent should perform, retrieve the tool that performs it\nQuery: '
STRONG_BUDGET = 1.5  # seconds; past it the answer is given as usual
# Below this closeness of the first listing, Chat asks which listed tool fits (tuning chose 0.70:
# 13% asked, direct-answer precision 92.1% -> 97.1%; holdout 89.4% -> 96.2%).
CHOICE_CLOSENESS = 0.70
CHOICE_LEAD = ('Not sure which of these fits your task. Choose one, or say more about what the agent should do.\n\n')


STRONG_PAUSE = 60.0        # seconds the stronger model is skipped after a failure
STRONG_WARMUP_BUDGET = 30.0  # a load takes about 6 s; the warm-up runs off the request path
_strong_state = {'down_until': 0.0, 'warming': False, 'lock': threading.Lock()}


def _warm_strong_model(http, url):
    try:
        http.post(url + '/api/embed', json={'model': STRONG_MODEL, 'input': ['warm up'], 'keep_alive': -1},
                  timeout=STRONG_WARMUP_BUDGET)
    except Exception:
        pass
    finally:
        _strong_state['warming'] = False


MODEL_WATCH_INTERVAL = 600.0  # seconds between checks that the embedding models are loaded


def _watch_models(engine):
    """Reload the embedding models Ollama dropped (11-06 an Ollama restart left qwen3 unloaded for 3 days)."""
    url = str(getattr(engine, 'ollama_url', '') or '').rstrip('/')
    http = getattr(engine, 'http', None)
    while True:
        time.sleep(MODEL_WATCH_INTERVAL)
        try:
            loaded = {model.get('name') for model in http.get(url + '/api/ps', timeout=3).json().get('models') or []}
        except Exception:
            continue
        if STRONG_MODEL not in loaded and not _strong_state['warming']:
            _strong_state['warming'] = True
            _warm_strong_model(http, url)


def _start_model_watch(engine):
    if _strong_state.get('watching'):
        return
    with _strong_state['lock']:
        if _strong_state.get('watching'):
            return
        _strong_state['watching'] = True
    threading.Thread(target=_watch_models, args=(engine,), name='embed-model-watch', daemon=True).start()


def strong_embeddings(engine, texts):
    """Vectors from the stronger local model, or None (model missing, slow or failing).

    11-09: after Ollama unloaded the model, every request waited the full budget and cancelled
    the 6 s reload, so it never loaded. A failure now pauses the model for STRONG_PAUSE and
    reloads it in the background; requests meanwhile answer without it at once."""
    url = str(getattr(engine, 'ollama_url', '') or '').rstrip('/')
    http = getattr(engine, 'http', None)
    if not url or http is None or getattr(engine, 'embeddings_enabled', False) is not True:
        return None
    _start_model_watch(engine)
    if time.monotonic() < _strong_state['down_until']:
        return None
    try:
        response = http.post(url + '/api/embed', json={'model': STRONG_MODEL, 'input': texts, 'keep_alive': -1},
                             timeout=STRONG_BUDGET)
        vectors = response.json().get('embeddings') if response.status_code == 200 else None
    except Exception:
        vectors = None
    if isinstance(vectors, list) and len(vectors) == len(texts):
        return vectors
    with _strong_state['lock']:
        _strong_state['down_until'] = time.monotonic() + STRONG_PAUSE
        start = not _strong_state['warming']
        _strong_state['warming'] = True
    if start:
        threading.Thread(target=_warm_strong_model, args=(http, url), name='strong-embed-warmup', daemon=True).start()
    return None


NEXT_STEPS_BUDGET = 0.4   # seconds; the suggestions are optional, the answer is not
NEXT_STEPS_TTL = 600.0
_next_steps_cache = {}
_next_steps_pool = None


def bounded_next_steps(store, rid, tool, protocol, excluded):
    """predict_next within NEXT_STEPS_BUDGET, cached per listing and tool (11-09: p50 0.6 s, max 4 s)."""
    global _next_steps_pool
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    from .inertia import InertiaGraph
    key = (id(store), rid, tool, protocol)
    cached = _next_steps_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < NEXT_STEPS_TTL:
        steps = cached[1]
    else:
        if _next_steps_pool is None:
            _next_steps_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='next-steps')
        def predict():
            found = InertiaGraph(store).predict_next(rid, tool, limit=2, protocol=protocol)
            if len(_next_steps_cache) > 2048:
                _next_steps_cache.clear()
            _next_steps_cache[key] = (time.monotonic(), found)
            return found
        try:
            steps = _next_steps_pool.submit(predict).result(timeout=NEXT_STEPS_BUDGET)
        except FutureTimeout:
            return []  # the prediction still finishes and fills the cache for the next answer
        except Exception:
            return []
    excluded = set(excluded or ())
    return [step for step in steps if step.get('resource_id') not in excluded]


def _tool_doc(item):
    tool = (item.get('tools_schema') or [{}])[0] or {}
    return (str(item.get('name') or '')[:80] + ': ' + str(tool.get('name') or '') + ' ' +
            str(tool.get('description') or item.get('description') or '')[:300]).strip() or 'agent'


def strong_closeness(engine, task, item):
    """Closeness of TASK and ITEM's chosen tool by the stronger model, or None when it cannot be measured."""
    vectors = strong_embeddings(engine, [STRONG_INSTRUCT + str(task)[:1000], _tool_doc(item)])
    return _cosine(vectors[0], vectors[1]) if vectors else None


def states_every_word(item, words):
    """Each word, or its plural, as a whole word in the recommended tool's own name and description."""
    schema = (item.get('tools_schema') or [{}])[0] or {}
    text = ' '.join([str(item.get('name') or ''), str((item.get('tools') or [''])[0] or '').replace('_', ' '),
                     str(schema.get('description') or '')] + ([] if schema.get('description') else [str(item.get('description') or '')])).lower()
    return all(re.search(r'\b' + re.escape(word.lower()) + r'(?:e?s)?\b', text) for word in words)


def unknown_words(store, task):
    """Capability words of TASK that no indexed listing contains."""
    from .selection import capability_terms
    from .discovery import normalize_task
    return [term for term in capability_terms(normalize_task(task))
            if term.isascii() and len(term) >= 4 and catalog_share(store, term) == 0]


GENERIC_SHARE = 0.05
SINGLE_SHARE = 0.002
SINGLE_CONVERGENCE = 0.3
_catalog_counts = {}


def catalog_share(store, term):
    """The share of indexed listings whose text matches TERM; 0 when it cannot be read."""
    key = (id(store), term)
    cached = _catalog_counts.get(key)
    if cached is not None and time.monotonic() - cached[0] < 3600:
        return cached[1]
    try:
        if getattr(store, 'backend', None) == 'postgresql':
            from ..postgres_lexical import QUERY
            with store.tx(readonly=True):
                total = store._execute('SELECT count(*) FROM public.resources_fts').fetchone()[0]
                found = store._execute(QUERY + 'SELECT count(*) FROM public.resources_fts f CROSS JOIN ac_query q '
                                       'WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms',
                                       (term,)).fetchone()[0]
        else:
            total = store.query('SELECT COUNT(*) AS c FROM resources_fts')[0]['c']
            found = store.query('SELECT COUNT(*) AS c FROM resources_fts WHERE resources_fts MATCH ?',
                                ('"' + term.replace('"', '') + '"',))[0]['c']
    except Exception:
        return 0.0
    share = found / total if total else 0.0
    if len(_catalog_counts) > 4096:
        _catalog_counts.clear()
    _catalog_counts[key] = (time.monotonic(), share)
    return share


def part_text(part):
    """Search text for one part of a compound request; "... when it goes down" states when to act."""
    return retrieval_text(re.split(r'\s+(?:when|whenever|if|once)\s+', str(part or ''), maxsplit=1, flags=re.I)[0])


def display_label(value, fallback):
    text = str(value or '')
    return fallback if DISPLAY_RESTRICTED.search(text) else text or fallback


def agent_display_name(item):
    """Keep a public brand legible while omitting commercial or untranslated labels."""
    name = str(item.get('name') or '').strip()
    name = re.sub(r'[$\u20ac\u00a3\u20a9]\s*\d[\d.,]*(?:\s*/\s*\w+)?', '', name)
    name = DISPLAY_RESTRICTED.sub(' ', name)
    name = re.sub(r'\s+', ' ', name).strip(' /|,;:-\u2013\u2014')
    if name and re.search(r'[A-Za-z]', name):
        return name[:140]
    kind = str(item.get('kind') or 'Agent').upper()
    return kind+' agent'+(' #'+str(item['id']) if type(item.get('id')) is int else '')


# Words that say what kind of answer is wanted rather than what it is about ("status", "number").
GENERIC_SUBJECT_TERMS = frozenset({'status','number','numbers','data','info','information','check','get','find',
    'lookup','look','search','list','details','detail','value','values','current','latest','today','tool','api',
    'service','agent','free','key','account','without','using','tomorrow'})


def subject_first(task, items):
    """When the first candidate never names the task's subject ("flight") and another does, that one leads.

    Only that case moves: a full reorder by word count lost "convert time between time zones" on the
    evaluation set (11-04), while a shop's "order status" leading "check flight status" is the failure."""
    terms = [t for t in search_terms(task) if t not in GENERIC_SUBJECT_TERMS]
    if len(items) < 2 or not terms:
        return items
    said = lambda item: _subject_words(terms, item)
    if said(items[0]):
        return items
    best = max(range(1, len(items)), key=lambda i: (said(items[i]), -i))
    return [items[best]] + items[:best] + items[best + 1:] if said(items[best]) else items


def _subject_words(terms, item):
    """How many of the task's subject words the listing's own name, description or tools say."""
    from .selection import _term_in
    text = ' '.join([str(item.get('name') or ''), str(item.get('description') or '')] +
                    [str(s.get('name') or '') + ' ' + str(s.get('description') or '') for s in item.get('tools_schema') or []]).lower()
    return sum(1 for t in terms if _term_in(t, text))


SEMANTIC_SHORTLIST = 10
RELAY_WIDEN = 30          # candidates read once more when none of the admitted ones is relayed by the gateway
RELAY_WIDEN_BEFORE = 2.5  # seconds into a request after which that wider read does not start (recommend: 5 s interim)


def relayable(item):
    """False for an MCP recommendation whose chosen tool is left out of the gateway's tools/list (an action tool or
    one not verified read-only), so the caller could not run it through the gateway."""
    return not (isinstance(item, dict) and item.get('tool_unlisted') is True)


def relayable_only(items):
    """PM 11-14: a tool the relay policy will not run is not recommended while a relayed one is admitted; later
    re-orders (subject_first, condition_first) could otherwise move it back to first. When none is relayed, the
    honest documentation-link answer stays (11-12 PM decision on unrelayed recommendations)."""
    kept = [item for item in items if relayable(item)]
    return kept or items


FALLBACK_DEADLINE = 8.0  # seconds into a request after which the split and neighbor searches do not start
SEMANTIC_BUDGET = 0.8  # seconds; past it the ranked order stands
# One request at a time searches its parts at once (two read-pool sessions), as Explore does (11-13).
_parallel_parts = threading.BoundedSemaphore(1)


def _cosine(a, b):
    import math
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


PLACES = frozenset('''alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii
    idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi
    missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia washington
    wisconsin wyoming usa us america canada mexico brazil uk england britain france germany spain italy japan china
    korea india australia europe asia africa seoul tokyo london paris berlin'''.split())
PLACE_PAIRS = ('new york', 'new jersey', 'new mexico', 'new hampshire', 'north carolina', 'south carolina',
               'north dakota', 'south dakota', 'west virginia', 'rhode island', 'united states', 'south korea')


def without_places(task):
    """The task without the places it names and their prepositions ("in California"), or None when it names none."""
    lowered = ' ' + str(task or '').lower() + ' '
    for pair in PLACE_PAIRS:
        lowered = lowered.replace(' ' + pair + ' ', ' california ')  # one place token stands for the pair
    words = re.findall(r"[a-z][a-z'-]*|[^\sa-z]", lowered)
    kept, dropped = [], False
    for word in words:
        if word in PLACES:
            dropped = True
            if kept and kept[-1] in ('in', 'for', 'near', 'around', 'across', 'of', 'from'):
                kept.pop()
            continue
        kept.append(word)
    text = re.sub(r'\s+([?.!,])', r'\1', ' '.join(kept)).strip()
    return text if dropped and text else None


SEMANTIC_MEMO = 5000  # candidate texts kept with their vectors (768 floats each, about 30 MB in all)
_SEMANTIC_VECTORS = __import__('collections').OrderedDict()
_SEMANTIC_LOCK = __import__('threading').Lock()


def semantic_first(engine, task, items):
    """The ranked list with the closest tool first; one candidate needs no embedding call."""
    return items if len(items) < 2 else semantic_rank(engine, task, items)[0]


def semantic_rank(engine, task, items):
    """Move the candidate whose chosen tool is closest in meaning to the task to the front.

    Measured offline (11-04, production read-only, threshold chosen on tuning only): of answered
    cases the first of ten was right for 85% and some of the ten for 93%; moving the closest tool
    first gained 28 and lost 5 on tuning, gained 13 and lost 3 on holdout, in about 0.22 s. The
    ranked order stands when embeddings are off, slow or fail."""
    # The same "enabled" rule as discovery: a stub engine (tests, a disabled RAG) is never called.
    if not items or engine is None or getattr(engine, 'embeddings_enabled', False) is not True:
        return items, None
    docs = []
    for item in items:
        tool = (item.get('tools_schema') or [{}])[0] or {}
        docs.append((str(item.get('name') or '')[:80] + ': ' + str(tool.get('name') or '') + ' ' +
                     str(tool.get('description') or item.get('description') or '')[:300]).strip() or 'agent')
    # A listing's text is embedded once per process (11-11: 0.3 s of each Chat answer re-embedded the
    # same ten candidate texts); only the task and texts not seen before go to the embedding model.
    model = getattr(engine, 'embed_model', None)
    missing = [doc for doc in dict.fromkeys(docs) if (model, doc) not in _SEMANTIC_VECTORS]
    from .retrieval_metrics import stage
    try:
        with stage('semantic'):
            fresh = engine.embed_texts([str(task)[:1000]] + missing, timeout_seconds=SEMANTIC_BUDGET)
    except Exception:
        return items, None
    if not isinstance(fresh, list) or len(fresh) != len(missing) + 1:
        return items, None
    with _SEMANTIC_LOCK:
        for doc, vector in zip(missing, fresh[1:]):
            _SEMANTIC_VECTORS[(model, doc)] = vector
            _SEMANTIC_VECTORS.move_to_end((model, doc))
        while len(_SEMANTIC_VECTORS) > SEMANTIC_MEMO:
            _SEMANTIC_VECTORS.popitem(last=False)
        known = [_SEMANTIC_VECTORS.get((model, doc)) for doc in docs]
    if any(vector is None for vector in known):
        return items, None
    vectors = [fresh[0]] + known
    scores = [_cosine(vectors[0], vector) for vector in vectors[1:]]
    best = max(range(len(items)), key=lambda i: (scores[i], -i))
    return ([items[best]] + items[:best] + items[best + 1:] if best else items), scores[best]


def condition_first(task, items):
    """Among candidates that name the task's subject, the one meeting more requested conditions leads.

    2nd review (11-04): the weather #1 left the forecast range unknown while #2 matched it. Order
    changes only between candidates whose verdicts differ: fewer violated, then fewer unknown,
    keeping the earlier order otherwise; a candidate that never names the subject never moves up."""
    fits = [item.get('task_fit') or {} for item in items]
    if len(items) < 2 or not any(fit.get('matched') or fit.get('unknown') or fit.get('violated') for fit in fits):
        return items
    terms = [t for t in search_terms(task) if t not in GENERIC_SUBJECT_TERMS]
    def key(pair):
        index, item = pair
        fit = fits[index]
        return (0 if not terms or _subject_words(terms, item) else 1,
                1 if fit.get('violated') else 0, len(fit.get('unknown') or []), index)
    return [item for _, item in sorted(enumerate(items), key=key)]


# Readable names for task_fit keys in the reason sentence.
FIT_LABELS = {'no_api_key': 'no API key', 'no_account': 'no account', 'no_charge': 'free to call',
              'region': 'the requested region', 'forecast': 'the forecast range', 'language_pair': 'the language pair',
              'pdf_input': 'PDF input'}


def recommendation_reason(subject, item):
    """Why this listing, in task and condition terms rather than matched words (2nd review B3, 11-04)."""
    fit = item.get('task_fit') or {}
    label = lambda key: FIT_LABELS.get(key, str(key).replace('_', ' '))
    tool = next(iter(item.get('tools') or []), None)
    tool = display_label(tool, '') if tool else ''
    met = [label(key) for key in fit.get('matched') or []]
    open_ = [label(key) for key in fit.get('unknown') or []]
    missed = [label(key) for key in fit.get('violated') or []]
    text = 'Chosen for "' + subject + '"' if subject else 'Chosen for this task'
    if tool:
        text += ' through its ' + tool + ' tool'
    if met:
        text += '; meets ' + ', '.join(met)
    if open_:
        text += '; not confirmed: ' + ', '.join(open_)
    if missed:
        text += '; does not meet ' + ', '.join(missed)
    return {'task': subject, 'tool': tool or None, 'meets': met, 'not_confirmed': open_, 'does_not_meet': missed,
            'text': text + '.'}


def merged_fit(required, item):
    """One verdict per requested condition: declared tool constraints, recorded conditions and access needs."""
    fit = item.get('task_fit') or {}
    matched, unknown, violated = list(fit.get('matched') or []), list(fit.get('unknown') or []), list(fit.get('violated') or [])
    seen = lambda key: key in matched or key in unknown or key in violated
    needs_auth = item.get('auth_required')
    for key in ('no_api_key', 'no_account'):
        if key in (required or ()) and not seen(key):
            if needs_auth is False:
                matched.append(key)
            elif needs_auth and key == 'no_api_key' and 'key' in str(item.get('auth_method') or '').lower():
                violated.append(key)
            else:
                unknown.append(key)
    check = item.get('condition_check') or {}
    for name, bucket in (('matched', matched), ('unknown', unknown), ('violated', violated)):
        for key in check.get(name) or []:
            if not seen(key):
                bucket.append(key)
    return {'matched': matched, 'unknown': unknown, 'violated': violated,
            'status': 'mismatch' if violated else 'unknown' if unknown else 'match'}


# Tasks the catalog answers well, offered when a request names no task.
CLARIFY_EXAMPLES = ('Find research papers on a topic', 'Get a weather forecast for a city',
                    'Convert currency rates without an API key')


class FastConcierge(Concierge):
    """Keep transport/session compatibility with bounded factual task matching."""

    def greeting(self, v=None, maybe_known=False):
        from .chat_guidance import EXAMPLES
        return Reply('Describe the task. I will recommend up to three relevant agents or published workflows. '
                     'For example: ' + '; '.join(EXAMPLES) + '.',
                     'welcome_back' if v and not v.new else 'greet', {'examples': list(EXAMPLES)})

    def _workflow_recommend(self, v, task, data, *, offset=0, previous=None, changes=False):
        from .workflow_discovery import recommend
        from .chat_progress import step
        step('workflows')
        result = recommend(self.store, task, data, runtime=getattr(self, 'workflow_runtime', None), offset=offset)
        selected = next(iter(result['workflows']), None)
        signature = ({'id': selected['id'], 'definition_hash': selected['definition_hash'],
                      'availability_code': selected['execution_availability']['reason_code']} if selected else {})
        if changes:
            result['changed'] = any((previous or {}).get(k) != signature.get(k) for k in ('id', 'definition_hash', 'availability_code'))
        self.book.save_results(v, [{'resource_type': 'workflow', 'task': task[:2000],
            'protocol_filter': result['protocol'], 'id': item['id'], 'definition_hash': item['definition_hash'],
            'availability_code': item['execution_availability']['reason_code']} for item in result['workflows']],
            offset+len(result['workflows']))
        if selected:
            lines = []
            for index, item in enumerate(result['workflows']):
                lines.append(str(index+1)+'. '+display_label(item['name'], 'Published workflow')+' [WORKFLOW]')
                detail = display_label(item['description'], '')
                if detail: lines.append(detail)
            lines += ['Open: https://agentconcierge.biz'+selected['page_path'],
                      'Review the published inputs and authorize a run before execution.']
            if changes and not result['changed']: lines.append('No material workflow change was found.')
            message = '\n'.join(lines)
        else:
            message = ('No published workflow matches the selected protocol. Choose another protocol explicitly.'
                       if result['reason_code'] == 'protocol_mismatch' else
                       'No published workflow matches this task. Browse published workflows or use Workspace to review a new workflow.')
        return Reply(message, 'find_workflow', result)

    @staticmethod
    def _brief(item, first=True):
        kind = item['kind']
        name = agent_display_name(item)
        call = {'mcp':'initialize → tools/list → tools/call',
                'a2a':'Agent Card → message/send or SendMessage',
                'x402':item.get('method') or 'GET'}[kind]
        lines = [f"{display_label(name, 'Recommended agent')} [{kind.upper()}]", 'Endpoint: '+(item.get('usage_endpoint') or item['url']),
                 'Call: '+call]
        if item.get('tool_unlisted') is True and isinstance(item.get('connection_note'), str):
            lines.append('Connection: '+item['connection_note'][:600])  # 11-12 PM: not relayed by our gateway
        elif first and kind == 'mcp':
            # 11-12 PM: an MCP host cannot add a server mid-conversation; our /mcp `call` tool runs the
            # recommended informational tool in the same session, and a person can paste the config line.
            from .connections import run_here, mcp_config, gateway_agent_url
            step = run_here(item.get('id'), (item.get('tools_schema') or [None])[0])
            if step:
                # growth plan 7 item 3 (PM 11-14): the line to run it comes right under the name, before the details
                lines.insert(1, 'Run here: call ' + json.dumps(step['arguments'], separators=(',', ':')))
            gateway = gateway_agent_url(item.get('id'), 'mcp')
            if gateway:
                lines.append('MCP config: ' + json.dumps(mcp_config(name, gateway), separators=(',', ':')))
        summary=next((part.strip() for part in re.split(r'(?<=[.!?])\s+|;',str(item.get('description') or '')) if part.strip() and not DISPLAY_RESTRICTED.search(part)), '')
        if summary:lines.append('Capability: '+summary[:220])
        from .task_conditions import explanation
        conditions = explanation(item.get('condition_check') or {})
        if conditions:
            lines.append('Conditions: '+conditions)
        reason = (item.get('reason') or {}).get('text')
        if reason and not DISPLAY_RESTRICTED.search(reason):
            lines.append('Why: '+reason)
        if item.get('tools'):
            lines.append('Tool: '+display_label(item['tools'][0], 'Available tool'))
            schema = (item.get('tools_schema') or [{}])[0]
            purpose = display_label(schema.get('description'), '')
            if purpose:  # omitted when the provider text is restricted in Chat
                lines.append('What it does: '+purpose)
        grade = item.get('grade') or 'unrated'
        report = item.get('test_report')
        checked = datetime.fromtimestamp(item['active_checked_at'],timezone.utc).isoformat(timespec='seconds')
        proof = f"Grade: {grade}"
        if report:
            tested = datetime.fromtimestamp(report['created_at'],timezone.utc).isoformat(timespec='seconds')
            state = "passed" if report["success"] else "failed"
            proof += f" · Test report: #{report['id']} ({state}; {tested})"
        lines.extend([proof, 'Active checked: '+checked])
        task_check = item.get('task_verification') or {}
        if task_check.get('status') == 'verified':
            lines.append('Selected tool check: passed')
        if item.get('auth_required') and kind != 'x402':
            lines.append('Auth: required')
        return '\n'.join(lines)

    def _recommend(self, v, task, offset=0, exclude=None, protocol=None, operation="new"):
        observation=journal_for(self.store).begin('recommendation','chat',proto=protocol)
        try:
            result=self._recommend_unobserved(v,task,offset,exclude,protocol,operation)
            items=result.data.get('recommendations') or []
            if items:observation.selected(items[0].get('id'),items[0].get('kind'))
            observation.finish('matched' if result.data.get('recommendations') else 'no_match')
            return result
        except Exception:
            observation.finish('failed','EXECUTION_FAILED')
            raise

    def lookup(self, visitor, task, protocol=None):
        """Read recorded recommendations without changing a conversation."""
        return self._recommend_unobserved(visitor,task,protocol=protocol,persist=False)

    def _recommend_unobserved(self, v, task, offset=0, exclude=None, protocol=None, operation="new", *, persist=True):
        started=time.monotonic()
        from .chat_task_spec import parse
        from .chat_progress import step
        step('understand')
        spec = parse(task, operation=operation)
        task = spec.original
        # One-letter typos become required capability words otherwise ("sttaus", stage 1, 11-04).
        from .catalog_spelling import respell
        task = respell(task)
        visitor_excluded = (self.book.failed_resources(v.id) if v else set()) | set(exclude or ())
        circuit_excluded = self.book.global_failing_resources()
        excluded = visitor_excluded | circuit_excluded
        step('search')
        if offset == 0:
            # Rank ten, then let the tool closest in meaning lead (stage 2, 11-04): the right listing was
            # in the first ten for 93% of answered cases but first for 85%.
            items = semantic_first(getattr(self.rec, 'rag_engine', None), task,
                                   self.rec.search(retrieval_text(task), kind=protocol, limit=SEMANTIC_SHORTLIST,
                                                   exclude=excluded))
            # A tool that needs a paid plan or the caller's own account, or whose recent calls through our
            # gateway only failed, follows the others, and one whose calls succeeded leads; the meaning
            # order holds within each group (11-11 PM: extract_invoice_data first; real tasks p10, a05).
            from .gateway_exposure import order_key
            items = sorted(items, key=lambda item: order_key(item) if isinstance(item, dict) else (True, True, True))[:3]
        else:
            items = self.rec.search(retrieval_text(task), kind=protocol, limit=3, offset=offset, exclude=excluded)
        if not items and offset == 0:
            # A place the task names is a condition, not a capability: no alert tool says
            # "California", so "weather alerts in California" found nothing while Explore listed five
            # NWS alert tools (11-11 real task p12). Search once more without the place names.
            placeless = without_places(task)
            if placeless:
                step('place')
                items = semantic_first(getattr(self.rec, 'rag_engine', None), task,
                                       self.rec.search(retrieval_text(placeless), kind=protocol,
                                                       limit=SEMANTIC_SHORTLIST, exclude=excluded))
                from .gateway_exposure import order_key
                items = sorted(items, key=lambda item: order_key(item) if isinstance(item, dict) else (True, True, True))[:3]
        focus = None
        summarizer = getattr(self, 'query_summarizer', None)
        if not items and callable(summarizer):
            # A long narrative can name its capability after the first clause. One grounded
            # summary leads the search; the full original still supplies every condition.
            if len(task) >= SUMMARY_MIN_CHARS:
                step('rephrase')
            focus = summarizer(task) if len(task) >= SUMMARY_MIN_CHARS else None
            # "<focus> for <request>": capability terms stop at "for", so the summary names the
            # capability while the request still supplies subjects and conditions.
            if focus and len(focus) + 5 + len(task) <= 2000:
                items = self.rec.search(focus + ' for ' + task, kind=protocol, limit=3, offset=offset, exclude=excluded)
                if not items:
                    # The narrative's own words can still fail every gate ("we keep losing track of
                    # related work"); the grounded capability phrase alone is the request's need.
                    items = self.rec.search(focus, kind=protocol, limit=3, offset=offset, exclude=excluded)
            else:
                focus = None
        rewriter = getattr(self, 'query_rewriter', None)
        # A request the normalizer already rewrote keeps its original words beside the rewrite.
        if not items and callable(rewriter) and task.isascii() and ' for ' not in task and unknown_words(self.store, task):
            # "wheather in pariss": words no listing contains are misspellings far more often than
            # capabilities; the grounded normalizer respells them and the search runs once more.
            step('respell')
            respelled = rewriter(task)
            if isinstance(respelled, str) and respelled and respelled.lower() != task.lower():
                items = self.rec.search(retrieval_text(respelled), kind=protocol, limit=3, offset=offset, exclude=excluded)
                if items:
                    focus = focus or respelled
        if not items and len(task) < SUMMARY_MIN_CHARS and not QUESTION_FORM.match(task):
            # Every gate requires most of the capability words. When the request also names
            # its subject ("remote software engineering jobs", "restaurants near Times Square")
            # those subject words appear in almost none of the retrieved candidates; search
            # again with the words the candidates share (pseudo-relevance feedback).
            narrowed = capability_focus(self.store, getattr(self.rec, 'rag_engine', None), retrieval_text(task), protocol)
            if narrowed:
                step('narrow')
                # Fewer words admit more listings; keep only those whose chosen tool says every one
                # of them as a word ("directions" is not "directory").
                items = [item for item in self.rec.search(narrowed, kind=protocol, limit=3, offset=offset, exclude=excluded)
                         if states_every_word(item, narrowed.split())]
                if items:
                    focus = focus or narrowed
        parts = []
        # Past FALLBACK_DEADLINE the last fallbacks no longer start (11-09: split->narrow answers took
        # 11.5-12.5 s); 3.5 and 5.0 s cut right answers (11-05), so only the long tail is cut.
        late = lambda: time.monotonic() - started >= FALLBACK_DEADLINE
        if not items and not late():
            # "weather data, a translator and a stock price feed": one match for each named capability.
            from .chat_guidance import separate_requests
            step('split')
            for part in separate_requests(task):
                # Rank like the part asked alone: a limit of one stops at the first focused listing.
                found = self.rec.search(part_text(part), kind=protocol, limit=3, offset=0,
                                        exclude=excluded | {item['id'] for item in items})
                if found:
                    items.append({**found[0], 'request_part': part[:120]})
                    parts.append(part[:120])
        elif items and offset == 0:
            step('cover')
            items, parts = self._cover_parts(task, items, protocol, excluded)
        if not items and offset == 0 and not late():
            # Last: the words the listings closest in meaning share, when the request's own words
            # never appear in them ("emotion analysis" -> listings that say "sentiment"; stage 2, 11-05).
            shared = neighbor_focus(self.store, getattr(self.rec, 'rag_engine', None), task, protocol)
            if shared:
                step('narrow')
                ranked, closeness = semantic_rank(getattr(self.rec, 'rag_engine', None), task,
                                                  self.rec.search(shared + ' for ' + task, kind=protocol,
                                                                  limit=SEMANTIC_SHORTLIST, exclude=excluded))
                # Words the request never said need a clearly close tool; below the bar, no answer
                # is more accurate than a guess (tuning chose 0.73: 39 answers, 95% right).
                if ranked and closeness is not None and closeness >= NEIGHBOR_CLOSENESS:
                    items = ranked[:3]
                    focus = focus or shared
        # Rewrites, narrowing and part searches cannot discard the original conditions.
        items = self._condition_admit(task, items)
        if items and offset == 0 and not any(relayable(item) for item in items) and \
                time.monotonic() - started < RELAY_WIDEN_BEFORE:
            # Every admitted candidate's tool is one the gateway does not relay (an action such as translate_file,
            # 11-14 user_slo 06:04 mcp/36882): look once further down the same search for one it does relay.
            step('relay')
            further = [item for item in self.rec.search(retrieval_text(task), kind=protocol, limit=RELAY_WIDEN,
                                                        exclude=excluded | {item.get('id') for item in items})
                       if relayable(item)]
            items = self._condition_admit(task, further)[:3] or items
        items = relayable_only(items)
        if not items:
            if persist:
                with self.book.batch():
                    self.book.save_results(v,[],0)
                    self.book.remember_interest(v,task,classify(' '.join(search_terms(task))),protocol,None,[])
            from .chat_guidance import QUESTION
            reason = 'out_of_scope' if QUESTION.match(task) and offset == 0 else 'no_eligible_match'
            no_match_data = {'task':task,'protocol':protocol,'recommendations':[],'status':'no_match',
                             'reason_code':reason,'task_spec':spec.state(),
                             # Explore lists every listing, including ones not yet verified for Chat.
                             'explore_query':' '.join(search_terms(task))[:120]}
            # A cross-scope suggestion is optional; do not double an already
            # slow search just to check whether another selector might help.
            if protocol in ('a2a', 'mcp') and time.monotonic()-started < 2:
                alt = self.rec.search(task, kind=None, limit=1, exclude=excluded)
                if alt and alt[0].get('kind') != protocol:
                    alt_kind = alt[0]['kind']
                    qualifier = 'Verified ' if alt[0].get('verified_working') else ''
                    no_match_data['cross_protocol_hint'] = {
                        'available_protocol': alt_kind,
                        'retry_protocol': 'any',
                        'message': f'{qualifier}{alt_kind.upper()} alternatives exist if queried with protocol="any" or protocol="{alt_kind}".',
                    }
            from .chat_guidance import MESSAGES
            message = MESSAGES['out_of_scope'] if reason == 'out_of_scope' else 'No currently active, relevant agent found.'
            if no_match_data.get('cross_protocol_hint'):
                message += ' ' + no_match_data['cross_protocol_hint']['message']
            return Reply(message, 'find', no_match_data)
        # Among the admitted candidates, the ones whose own words name the task's subject lead (11-04 review A-1).
        items = subject_first(task, items)
        step('prepare')
        from .recommendation_evidence import evidence
        from .selection import capability_terms
        from .discovery import normalize_task
        subject = (focus or ' '.join(capability_terms(normalize_task(task))))[:80]
        for item in items:
            item['display_name'] = agent_display_name(item)
            item['task_fit'] = merged_fit(spec.required, item)
            item['reason'] = recommendation_reason(subject, item)
            item['evidence'] = evidence(item)
        items = condition_first(task, items)
        if persist:
            saved = [{**item,'task':task,'task_spec':spec.state(),'protocol_filter':protocol} for item in items]
            listed, category = list(items), items[0]['category']
            def remember():
                with self.book.batch():
                    self.book.save_results(v,saved,offset+len(listed))
                    # Retain only the structured task state needed for subsequent requests.
                    self.book.remember_interest(v,task,category,protocol,None,listed)
            # The answer does not need these writes; the visitor's next read waits for them (11-09).
            defer = getattr(self.book, 'defer', None)
            defer(v.id, remember) if callable(defer) else remember()
        top_tool = (items[0].get('tools') or [''])[0]
        next_steps = bounded_next_steps(self.store, items[0]['id'], str(top_tool or ''), protocol, excluded)
        continuation_plan = {
            'inspect_contract': {'command': 'details 1'},
            'more_candidates': {'command': 'more'},
            'report_outcome': {'succeeded': 'worked 1', 'failed': 'failed 1', 'mcp_tool': 'report'},
            'session_resume': {'method': 'GET', 'path': '/api/agent/v1/resume', 'header': 'X-Visitor-Token'},
        }
        if not persist:
            continuation_plan={'inspect_contract':{'method':'GET','path':'/api/agents/{resource_id}'},
                               'start_conversation':{'tool':'chat','message':task}}
        state=spec.state()
        # A follow-up such as "only free ones" says which conditions the new list satisfies.
        labels={'no_charge':'free to call','no_api_key':'no API key','no_account':'no account'}
        applied=[labels[name] for name in state.get('required',[]) if name in labels]
        lead=('Filtered for: '+', '.join(applied)+'.\n\n') if state.get('operation')=='refine' and applied else ''
        # Low closeness of the first listing: offer the list as choices instead of asserting it (stage 4, 11-05).
        unsure = (not parts and offset == 0 and state.get('operation') != 'refine'
                  and (strong_closeness(getattr(self.rec, 'rag_engine', None), task, items[0]) or 1.0) < CHOICE_CLOSENESS)
        if unsure:
            lead = CHOICE_LEAD + lead
        # The first listing that our gateway runs is offered as a `call` in this session (11-12 PM).
        from .connections import run_here
        runnable = next((item for item in items[:1] if item.get('kind') == 'mcp' and item.get('tool_unlisted') is not True), None)
        here = run_here(runnable.get('id'), (runnable.get('tools_schema') or [None])[0]) if runnable else None
        if here:
            # next_steps stay follow-up listings (their own contract and safety gates, test_b2a_retention);
            # running the recommended tool here is a continuation of this answer.
            continuation_plan['run_here'] = here
        return Reply(lead+'\n\n'.join(str(i+1)+'. '+self._brief(item, first=i == 0) for i,item in enumerate(items)),'find',
                     {**({'status':'needs_choice','confidence':'low'} if unsure else {}),
                      'task':task,'watch_task':' '.join(search_terms(task))[:160],'protocol':protocol,
                      'category':items[0]['category'],'revalidate_after_sec':3600,
                      'task_spec':spec.state(),'quality_policy':'task_constraints_verified_recency_v1',
                      **({'task_focus':focus} if focus else {}),
                      **({'request_parts':parts} if parts else {}),
                      'continuation_plan':continuation_plan,
                      'next_steps':next_steps,'recommendations':items})

    def _condition_admit(self, task, items):
        from .task_conditions import requested, assess
        from .selection import _advertised_tools
        wanted = requested(task)
        if not (wanted['regions'] or wanted['languages'] or wanted['forecast']):
            return items
        result = []
        for item in items:
            check = item.get('condition_check') or {}
            if check.get('requested') != wanted:
                resource = self.store.resource(item['id'])
                if not resource:
                    continue
                name = next(iter(item.get('tools') or []), None)
                tool = next((tool for tool in _advertised_tools(resource)
                             if (tool.get('name') or tool.get('id')) == name), {})
                check = assess(task, resource, tool, conditions=wanted)
            if check.get('status') != 'mismatch':
                result.append({**item, 'condition_check':check})
        return result

    def _part_searches(self, parts, protocol, excluded):
        """Each part's own search as the in-turn loop asks it when nothing is chosen yet (exclude=EXCLUDED), two
        at a time on read-pool sessions (PM 11-13 21:0x). None when the pool has no two free sessions, another
        request is doing this, or the store has no read pool: the caller then searches in turn as before."""
        source = getattr(self, 'store', None)
        pool = getattr(source, '_admin_read_pool', None)
        if (len(parts) < 2 or getattr(source, 'backend', None) != 'postgresql' or pool is None
                or getattr(pool, 'maximum', 0) < 2 or not _parallel_parts.acquire(blocking=False)):
            return None
        try:
            if pool.free_sessions() < 2:
                return None
            from concurrent.futures import ThreadPoolExecutor
            from contextvars import copy_context
            from copy import copy
            from .discovery import discovery_store
            from .discovery_contracts import isolated_contract_reads

            def search(part):
                # The caller holds no read-pool lease, so the workers cannot wait on their parent.
                with discovery_store(source) as store, isolated_contract_reads():
                    recommender = copy(self.rec)
                    recommender.store = store
                    return recommender.search(part_text(part), kind=protocol, limit=3, offset=0, exclude=excluded)

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix='chat-part') as executor:
                pending = [executor.submit(copy_context().run, search, part) for part in parts]
                return [future.result() for future in pending]
        except Exception:
            return None  # a failed early read only loses the head start
        finally:
            _parallel_parts.release()

    def _cover_parts(self, task, items, protocol, excluded):
        """'Monitor my website and alert me on Telegram': when the matches cover only one
        named capability, keep the best match for each part instead of three for the first.
        The parts are searched at once when the read pool allows (_part_searches); a part whose early result
        names a listing an earlier part already took is searched again in turn, with that listing excluded,
        so the answer is the one the in-turn loop gives."""
        from .chat_guidance import separate_requests
        from .selection import capability_terms, _term_in
        split = separate_requests(task)
        if not split:
            return items, []
        early = FastConcierge._part_searches(self, split, protocol, excluded)
        def text(item):
            tools = ' '.join(str(t) for t in (item.get('tools') or []))
            return ' '.join(str(item.get(k) or '') for k in ('name', 'description', 'capability')).lower() + ' ' + tools.lower()
        def covers(item, part):
            terms = capability_terms(part_text(part))
            return bool(terms) and all(_term_in(term, text(item)) for term in terms)
        chosen, parts = [], []
        for index, part in enumerate(split):
            # The part's own best match first: in the whole-sentence ranking, the other part's
            # words promote listings that only mention this part.
            taken = {item['id'] for item in chosen}
            found = early[index] if early is not None else None
            if found is None or taken & {item.get('id') for item in found}:
                found = self.rec.search(part_text(part), kind=protocol, limit=3, offset=0,
                                        exclude=excluded | taken)
            match = found[0] if found else next(
                (item for item in items if covers(item, part) and item['id'] not in {c['id'] for c in chosen}), None)
            if match is None:
                return items, []  # a part nothing serves: keep the original matches
            chosen.append({**match, 'request_part': part[:120]})
            parts.append(part[:120])
        return chosen, parts

    def handle(self, v, text, data=None, channel='rest', fast=False):
        text = str(text or '').strip()
        data = data if isinstance(data,dict) else {}
        from .chat_task_spec import MAX_TASK_CHARS
        if len(text) > MAX_TASK_CHARS or len(str(data.get('task') or '')) > MAX_TASK_CHARS:
            return Reply('Please keep the task within 2,000 characters; no conditions were discarded.',
                         'error', {'status':'invalid_request','recommendations':[]})
        selected=data.get('protocol',data.get('kind'))
        mode=selected.strip().lower() if isinstance(selected,str) and selected.strip().lower() in ('auto','any','a2a','mcp','x402') else 'auto' if selected is None else 'invalid'
        contact_request=bool(data.get('intent') in ('contact','verify') or data.get('contact') or re.match(r'^(?:contact|webhook)\s+https?://|^verify\s+\d{6}$',text,re.I))
        from .chat_guidance import review, redacted, MESSAGES, action_request
        structured_task=str(data.get('task')or'')
        guidance = review(structured_task or text)
        if redacted(text)!=text or redacted(structured_task)!=structured_task:guidance='needs_redaction'
        stored_text='Task update destination request' if contact_request else text or str(data.get('task') or 'Structured discovery request')[:2000]
        stored_text=redacted(stored_text)
        from .chat_progress import step
        step('review')
        metadata={'protocol_mode':mode,'record_version':1}
        reason=data.get('feedback_reason')
        if reason in ('matched_task','connection_failed','unrelated_result','authorization_required','incomplete_result','other'):
            metadata['feedback_reason']=reason
        request_id=self.book.add_message(v,'agent',channel,stored_text,metadata)
        try:
            if data.get('resource_type') not in (None, 'auto', 'agent', 'workflow'):
                raise ValueError('Choose an agent or a published workflow.')
            requested_protocol(text or data.get('task'), data)
        except ValueError as exc:
            reply=Reply(str(exc),'error',{'status':'invalid_protocol'})
        else:
            if guidance:
                reply=Reply(MESSAGES[guidance],'clarify',{'status':guidance,'recommendations':[]})
            else:
                reply=Reply('Use task update preferences to authorize and verify a destination.','contact',{'status':'permission_required'}) if contact_request else self._fast_route(v,text,data)
            if action_request(structured_task or text):reply.data['action_review_required']=True
        snapshot=[]
        for item in reply.data.get('recommendations',[])[:3]:
            snapshot.append({key:item.get(key) for key in ('id','name','kind','url','usage_endpoint','category','grade','quality_score','test_report','active_checked_at')})
        workflows_snapshot=[]
        for wf in reply.data.get('workflows',[])[:3]:
            if isinstance(wf, dict):
                workflows_snapshot.append({key:wf.get(key) for key in ('id','name','node_protocols','detail_path')})
        # Tokens stay in the transport/visitor object, never in the answer text.
        msg_meta = {'record_version':1,'request_message_id':request_id,
            'intent':reply.intent,'status':reply.data.get('status','recommended' if (snapshot or workflows_snapshot) else reply.intent),
            'task':' '.join(search_terms(reply.data.get('task') or ''))[:160],
            'protocol_filter':reply.data.get('protocol'),'recommendations':snapshot}
        if workflows_snapshot:
            msg_meta['workflows'] = workflows_snapshot
        self.book.add_message(v,'concierge',channel,reply.text,msg_meta)
        return reply

    def _fast_route(self,v,text,data):
        name = NAME.search(text)
        if name:
            self.book.set_name(v,name.group(1))
        intent = str(data.get('intent') or '').lower()
        previous, offset = self.book.last_results(v.id)
        interests = self.book.interests(v.id) if not previous else []
        last_task = previous[0]['task'] if previous else (interests[0]['task'] if interests else None)
        last_protocol = previous[0].get('protocol_filter') if previous else (interests[0].get('kind') if interests else None)
        stored_protocol = last_protocol
        selected = data.get('protocol',data.get('kind'))
        explicit = isinstance(selected,str) and selected.strip().lower() in ('any','a2a','mcp','x402')
        inferred = requested_protocol(text or data.get('task'),data)
        last_protocol = inferred if explicit else inferred or last_protocol
        lowered = text.lower().strip(' .!?')
        from .chat_guidance import ordinal, pronoun_reference, condition_question
        number=ordinal(text)
        condition_query = bool(previous and condition_question(text))
        if not number and previous and (pronoun_reference(text) or condition_query):
            # "how do I connect to it?" continues with the recommendation last discussed.
            number=next((i+1 for i,item in enumerate(previous[:3]) if item.get('conversation_focus')),1)
        alternatives = re.search(r'\b(?:alternatives?|instead of|other options?|something else|similar to|replacements?)\b'
                                 r'|\banother (?:agent|one|option)\b.{0,35}\b(?:same|this|that) task\b', text, re.I)
        if previous and last_task and alternatives:
            # "alternatives to the first one" asks for other agents for the same task, not its details.
            focused = [item for item in previous[:3] if item.get('conversation_focus')]
            reply = self._recommend(v,last_task,exclude={item['id'] for item in (focused or previous[:3]) if item.get('id')},protocol=last_protocol)
            reply.intent = 'alternatives'
            return reply
        if number and previous and last_task:
            from .chat_task_spec import REFINE, canonical_text, merge
            if REFINE.match(canonical_text(text)):
                spec,_=merge(last_task,text)
                refined=self._recommend(v,spec.original,protocol=last_protocol,operation='refine')
                previous,offset=self.book.last_results(v.id)
                if not previous:return refined
                last_task=spec.original
        if number:lowered='details '+str(number)
        # Explicit session controls remain supported but are never promoted in discovery answers.
        if intent == 'contact' or data.get('contact') or re.match(r'^(contact|webhook)\s+https?://',lowered):
            reply = super()._contact(v,text,data)
            reply.suggested=[]
            return reply
        verify = re.fullmatch(r'verify\s+(\d{6})',lowered)
        if intent == 'verify' or verify:
            code = data.get('code') or (verify.group(1) if verify else '')
            reply = super()._verify(v,str(code))
            reply.suggested=[]
            return reply
        if intent in ('stop','resume') or lowered in ('stop','unsubscribe','mute','resume'):
            enabled = intent == 'resume' or lowered == 'resume'
            if hasattr(self,'updates'):
                if not enabled:
                    self.updates.stop_all(v.id)
                else:
                    return Reply('Manage task updates to resume an authorized task.','resume')
            self.book.set_notify(v.id,enabled)
            return Reply('Updates enabled.' if enabled else 'Updates disabled.','resume' if enabled else 'stop')
        from .workflow_discovery import wants_workflow, AUTHORING
        workflow_context = bool(previous and previous[0].get('resource_type') == 'workflow')
        workflow_more = intent == 'more' or lowered in ('more', 'next', 'another', '\ub2e4\ub978 \ucd94\ucc9c', '\ub2e4\uc74c')
        workflow_changes = intent == 'whats_new' or lowered in ("what's new", 'whats new', '\uc0c8 \uc18c\uc2dd', '\uc0c8\ub85c\uc6b4 \uc18c\uc2dd')
        workflow_details = intent == 'details' or bool(re.fullmatch(r'(?:details?\s*#?[1-3]|[1-3]\s*\ubc88\s*\uc790\uc138\ud788|\uc790\uc138\ud788)', lowered))
        workflow_follow = workflow_context and (workflow_more or workflow_changes or workflow_details)
        if wants_workflow(text, data) or workflow_follow:
            if AUTHORING.search(text):
                return Reply('Use Workspace to review and authorize workflow creation or editing.', 'workflow_authoring',
                    {'resource_type': 'workflow', 'status': 'authorization_required', 'recommendations': [],
                     'workspace_path': '/customer/sign-in'})
            workflow_data = dict(data)
            if workflow_follow and not explicit and inferred is None:
                workflow_data['protocol'] = previous[0].get('protocol_filter') or 'any'
            reply = self._workflow_recommend(v, last_task if workflow_follow else str(data.get('task') or text),
                workflow_data, offset=offset if workflow_follow and workflow_more and stored_protocol == last_protocol else 0,
                previous=previous[0] if workflow_context else None, changes=workflow_changes)
            if workflow_follow and workflow_details:
                index = int(next(iter(re.findall(r'[1-3]', lowered)), '1'))-1
                reply.data['workflows'] = reply.data['workflows'][index:index+1]
                reply.text = ('\n'.join([display_label(item['name'], 'Published workflow')+' [WORKFLOW]', display_label(item['description'], ''), 'Open: https://agentconcierge.biz'+item['page_path']]) if (item := next(iter(reply.data['workflows']), None)) else 'Choose one of the displayed workflow recommendations.')
            return reply
        if workflow_context and (intent == 'outcome' or re.fullmatch(r'(?:worked|failed|success|fail)\s*#?[1-3]', lowered)):
            return Reply('Use the workflow run key to inspect its recorded execution outcome.', 'outcome',
                         {'resource_type': 'workflow', 'status': 'run_key_required', 'recommendations': []})
        details = re.fullmatch(r'(?:details?\s*#?[1-3]|[1-3]\s*\ubc88\s*\uc790\uc138\ud788|\uc790\uc138\ud788)',lowered)
        if intent == 'details' or details:
            if not previous:
                return Reply('Describe the task first.','details')
            item = previous[0]
            # Re-read evidence: never echo a recommendation that has since failed or gone inactive.
            visitor_excluded = self.book.failed_resources(v.id)
            circuit_excluded = self.book.global_failing_resources()
            fresh = self.rec.search(last_task,kind=last_protocol,limit=3,exclude=visitor_excluded | circuit_excluded)
            if not fresh:
                return Reply('No currently active, relevant agent found.','details',{'recommendations':[],'status':'no_match'})
            index = int(next(iter(re.findall(r'[1-3]', lowered)), '1'))-1
            if index >= len(previous):
                return Reply('Choose one of the displayed recommendations.', 'details', {'recommendations':[]})
            if last_protocol != stored_protocol:
                item = fresh[index] if index < len(fresh) else None
                self.book.save_results(v,[{**candidate,'task':last_task,'protocol_filter':last_protocol} for candidate in fresh],len(fresh))
            else:
                item = next((candidate for candidate in fresh if candidate['id']==previous[index]['id']),None)
                if item is None and index < len(previous):
                    prev_candidate = previous[index]
                    resource=self.store.resource(prev_candidate.get('id')) if prev_candidate.get('id') else None
                    from .recommendation_security import usable_endpoint
                    from .task_requirements import input_requirements_match
                    current_contract=(prev_candidate.get('capability_contract') or {}).get('connection_version_id')
                    from ..capability_registry import Registry
                    version=Registry(self.store).current(resource,create=False) if resource else None
                    if (resource and resource.get('active') and resource.get('health_status') in ('healthy','reachable')
                            and resource.get('eval_security') not in ('quarantine','review') and resource.get('eval_grade')!='F'
                            and usable_endpoint(resource.get('url')) and input_requirements_match(last_task,resource)
                            and (not current_contract or version and version['id']==current_contract)
                            and prev_candidate['id'] not in (visitor_excluded | circuit_excluded)):
                        item=prev_candidate
            if item is None:
                return Reply('This recommendation is no longer eligible. Search again for current options.', 'details', {'recommendations':[], 'status':'no_match'})
            check = None
            if condition_query:
                from .chat_task_spec import parse
                from .task_conditions import assess, explanation, requested
                from .selection import _advertised_tools
                question = requested(text)
                known_condition = bool(question['regions'] or question['languages'] or question['forecast'])
                try:
                    last_task = parse(last_task.rstrip(' .')+'. '+text if known_condition else last_task, operation='refine').original
                except ValueError as exc:
                    return Reply(str(exc), 'clarify', {'status':'needs_task','recommendations':[]})
                resource = self.store.resource(item['id'])
                if not resource:
                    return Reply('This agent is no longer available. Choose a current recommendation.', 'details', {'recommendations':[],'status':'no_match'})
                tool_name = next(iter(item.get('tools') or []), None)
                tool = next((tool for tool in _advertised_tools(resource)
                             if (tool.get('name') or tool.get('id')) == tool_name), {})
                check = assess(last_task, resource, tool)
                if not known_condition:
                    check['unknown'].append('requested_condition')
                    if check['status'] != 'mismatch':
                        check['status'] = 'unknown'
                item['condition_check'] = check
            current, _ = self.book.last_results(v.id)
            self.book.save_results(v,[{**{k:val for k,val in entry.items() if k!='conversation_focus'},
                                       **({'task':last_task} if condition_query else {}),
                                       **({'conversation_focus':True} if entry.get('id')==item['id'] else {})} for entry in current],offset)
            item['display_name'] = agent_display_name(item)
            summary = (explanation(check)+' These are recorded declarations, not a new execution check. No action was run.\n\n') if check else ''
            return Reply(summary+self._brief(item),'details',{'task':last_task,'watch_task':' '.join(search_terms(last_task))[:160],
                         'protocol':last_protocol,'recommendations':[item],'recommendation':item,
                         **({'condition_check':check} if check else {})})
        if intent == 'more' or lowered in ('more','next','another','\ub2e4\ub978 \ucd94\ucc9c','\ub2e4\ub978 \uc5d0\uc774\uc804\ud2b8','\ub2e4\uc74c'):
            return self._recommend(v,last_task,offset=offset if stored_protocol==last_protocol else 0,protocol=last_protocol) if last_task else self.greeting(v)
        outcome = re.fullmatch(r'(worked|failed|success|fail)\s*#?[1-3]|[1-3]\s*(worked|failed|\uc131\uacf5|\uc2e4\ud328)',lowered)
        if intent == 'outcome' or outcome:
            if intent == 'outcome' and type(data.get('success')) is not bool:
                return Reply('success must be a boolean.','error',{'status':'invalid_request'})
            if not previous:
                return Reply('Describe the task first.','outcome')
            index = int(next(iter(re.findall(r'[1-3]', lowered)), '1'))-1
            if intent == 'outcome' and 'resource_id' in data:
                rid=data['resource_id']
                if type(rid) is not int or not any(item.get('id')==rid for item in previous):
                    return Reply('Choose one of the displayed recommendations.','outcome',{'status':'invalid_request'})
                index=next(i for i,item in enumerate(previous) if item.get('id')==rid)
            if index >= len(previous):
                return Reply('Choose one of the displayed recommendations.', 'outcome', {'status':'invalid_request'})
            reported = previous[index]
            success = bool(data.get('success')) if intent == 'outcome' else any(x in lowered for x in ('worked','success','\uc131\uacf5'))
            self.book.record_outcome(v,reported['id'],success)
            if not success:
                reply = self._recommend(v,last_task,exclude={reported['id']},protocol=last_protocol)
                reply.intent = 'outcome'
                reply.data.update(resource_id=reported['id'],success=False)
                return reply
            from .security import public_metadata
            name = public_metadata(str(reported.get('name') or 'this agent'))[:120]
            return Reply('Thanks. Recorded that '+name+' worked for this task.','outcome',{'resource_id':reported['id'],'success':True})
        if intent == 'whats_new' or lowered in ("what's new",'whats new','\uc0c8 \uc18c\uc2dd','\uc0c8\ub85c\uc6b4 \uc18c\uc2dd'):
            return self._recommend(v,last_task,protocol=last_protocol) if last_task else self.greeting(v)
        if intent == 'help' or lowered in ('help','\ub3c4\uc6c0\ub9d0','pricing','plans','pro sla','what are the pro sla tiers and pricing'):
            from .chat_guidance import EXAMPLES
            return Reply('Describe the task; up to three relevant agents will be returned. For example: '+'; '.join(EXAMPLES)+'.',
                         'help',{'examples':list(EXAMPLES)})
        if lowered in ('hi','hello','hey','\uc548\ub155','\uc548\ub155\ud558\uc138\uc694') or not text and not data.get('task'):
            return self.greeting(v)
        task = str(data.get('task') or clean_task(text,name))
        if name and task.lower().strip(' ,.!~') in ('hi','hello','hey',''):
            return self.greeting(v)
        from .chat_task_spec import merge
        try:
            spec, follow_task = merge(last_task, task)
        except ValueError as exc:
            return Reply(str(exc), 'clarify', {'status':'needs_task','recommendations':[]})
        task = spec.original
        protocol = requested_protocol(text or data.get('task'),data)
        if follow_task and not explicit and inferred is None:
            protocol = last_protocol
        if protocol and last_task and re.fullmatch(r'(?:a2a|mcp|x402)(?:\s+protocol)?', task.strip(), re.I):
            task = last_task
        from .hybrid_explore import ERC8004_QUERY
        if re.fullmatch(r'(?:(?:find|show|list|search|browse|give)\s+(?:me\s+)?(?:the\s+|all\s+)?)?(?:'
                        + ERC8004_QUERY.pattern + r')\s*[?.!]*', task.strip(), re.I):
            # A registry name is not a task; Explore lists every agent registered there.
            return Reply('ERC-8004 is an on-chain agent registry, not a task. Search 8004 in Explore to browse '
                         'registered agents, or describe the task an agent should do, such as '
                         '"ERC-8004 agents for token swaps".', 'clarify',
                         {'status':'needs_task','recommendations':[],'explore_query':'8004'})
        from .explore_search import corrected_task
        corrected = corrected_task(task)
        if corrected:
            # Search the corrected spelling and say so; the visitor sees what was searched.
            task = corrected
        task_terms=search_terms(task)
        # Normalize an unknown language when local extraction has no terms, or when
        # Korean content words are not covered by the alias tables (their subject
        # would otherwise be dropped). Fully known tasks keep the zero-generation path.
        rewriter = getattr(self, 'query_rewriter', None)
        from .selection import untranslated_words
        # Uncovered words (a Korean subject beside a covered capability) need normalization;
        # requests the alias tables fully cover keep the zero-generation path.
        if callable(rewriter) and (not task_terms or untranslated_words(task)):
            rewritten = rewriter(task)
            if isinstance(rewritten,str) and rewritten:
                combined = rewritten + ' for ' + task
                if len(combined) <= 2000:
                    task = combined
                    task_terms = search_terms(task)
            elif not task_terms and untranslated_words(task):
                with self.book.batch():
                    self.book.save_results(v,[],0)
                    self.book.remember_interest(v,task,classify(' '.join(task_terms)),protocol,None,[])
                return Reply('Your task is kept. Please restate it briefly in English; language normalization is unavailable.',
                             'clarify',{'status':'needs_language','recommendations':[],'task':task,'protocol':protocol})
        if not task_terms or set(task_terms).issubset({'artificial','intelligence','assistant','bot','chatbot'}):
            # Choices let a person tap one and let an agent pick one without writing a new task (11-04 review B6).
            return Reply('What should the agent do? Describe a task, such as finding research papers or searching technology news.',
                         'clarify', {'status':'needs_task','recommendations':[],'examples':list(CLARIFY_EXAMPLES)},
                         list(CLARIFY_EXAMPLES))
        reply = self._recommend(v,task,protocol=protocol,operation=spec.operation)
        if corrected and isinstance(getattr(reply,'text',None),str):
            reply.text = 'Searched for "' + corrected[:200] + '". ' + reply.text
            if isinstance(reply.data,dict):
                reply.data['corrected_task'] = corrected[:200]
        return reply


def _timed_entry(method):
    """Server-Timing thread_wait (request start to this worker thread) and cpu (this thread's CPU time)."""
    from functools import wraps
    from .retrieval_metrics import entered, left

    @wraps(method)
    def call(self, *args, **kwargs):
        entered()
        try:
            return method(self, *args, **kwargs)
        finally:
            left()
    return call


FastConcierge.handle = _timed_entry(FastConcierge.handle)
FastConcierge.lookup = _timed_entry(FastConcierge.lookup)
