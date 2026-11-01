"""Conservative capability coverage for advisory workflow proposals.

This is a guard for explicit task families, not a claim of general natural
language understanding. It never creates a new execution or external call.
"""
import re
from .workflow_goal_policy import positive_text, _mentions, GoalNeedsDetails

FAMILIES = (
    ('news.search.v1', 'News search', r'\b(?:news|headlines|newsletters?)\b'),
    ('docs.search.v1', 'Research and document search', r'\b(?:papers?|research|documentation|documents?)\b'),
    ('products.compare.v1', 'Product comparison', r'\b(?:compare products|product comparisons?|compare (?:the )?prices?|price comparisons?|cheapest)\b'),
)

# Workflows only read public sources. A search step must never stand in for an
# action such as booking or sending (2026-10-21: "Book a flight" became a search).
ACTIONS = (
    ('Booking, purchasing or payments', r'\b(?:book|booking|reserve|reservations?|buy|purchase|checkout|pay for|payments?|place an order)\b'),
    ('Sending messages or publishing', r'\b(?:e-?mail|send|notify|tweet|publish)\b'),
)


# Capabilities a reviewed search workflow does not have, named by what the request asks it to do
# (2026-11-01: weather, prices and device requests only heard "An explicit supported ... objective").
UNSUPPORTED = (
    ('Weather data', r'\b(?:weather|forecasts?|temperatures?|rainfall)\b'),
    ('Prices, quotes or market data', r'\b(?:prices?|stocks?|quotes?|bitcoin|ethereum|crypto\w*|exchange rates?|currenc(?:y|ies))\b'),
    ('File conversion or data extraction (PDF, JSON, spreadsheets)', r'\b(?:pdfs?|json|csv|excel|spreadsheets?|invoices?)\b'),
    ('Calculations', r'\b(?:calculat\w*|compute|sum(?: up)?|totals?|averages?)\b'),
    ('Image, audio or video generation', r'\b(?:generate|create|draw|make|render)\b.{0,30}\b(?:images?|pictures?|photos?|illustrations?|videos?|audio|music)\b'),
    ('Device or smart-home control', r'\b(?:thermostats?|fridges?|refrigerators?|lights?|smart home|devices?|appliances?)\b'),
    ('Monitoring with alerts', r'\b(?:alert|notify|warn)\b.{0,60}\b(?:when|if|whenever)\b|\b(?:when|if|whenever)\b.{0,60}\b(?:alert|notify|let me know|tell me)\b'),
)
# Korean and Japanese kind words too: an untranslated goal still names what it wants found.
SEARCH_KINDS = re.compile(r'\b(?:news|headlines|papers?|research|studies|documentation|docs|documents?|articles?|literature|sources?|references?)\b'
                          r'|\ub274\uc2a4|\ub17c\ubb38|\ubb38\uc11c|\uc5f0\uad6c|\u30cb\u30e5\u30fc\u30b9|\u8ad6\u6587|\u6587\u66f8|\u30c9\u30ad\u30e5\u30e1\u30f3\u30c8', re.I)
CLARIFY = ('What should the workflow find? Name a topic and news, research papers or documentation, '
           'for example "Find recent news about AI chips, then research papers on chip design".')
# A workflow only reads public sources; these purposes are refused before any model call.
OTHERS = r"(?:my neighbou?r'?s?|someone else'?s?|another person'?s?|other people'?s?|my ex'?s?|ex-?(?:wife|husband|girlfriend|boyfriend|partner)'?s?)"
DEFENSIVE = re.compile(r'\b(?:my own|authori[sz]ed|pen(?:etration)?[- ]?test\w*|defen[cs]\w*|protect\w*|secur(?:e|ing|ity)|prevent\w*|detect\w*|research|papers?|stud(?:y|ies))\b', re.I)
REFUSED = (
    # Unauthorized access: always when aimed at another person; otherwise unless the goal is defensive study.
    (r'\b(?:hack(?:ing)?|crack(?:ing)?|break(?:ing)? into|bypass(?:ing)?|exploit(?:ing)?)\b.{0,60}\b' + OTHERS, None,
     'An authorized purpose: accessing networks, devices or accounts without permission is not supported'),
    (r'\b(?:hack(?:ing)?|crack(?:ing)?|break(?:ing)? into|bypass(?:ing)?)\b.{0,60}\b(?:wi-?fi|wireless|networks?|routers?|phones?|accounts?|passwords?|e-?mails?|cameras?)\b', DEFENSIVE,
     'An authorized purpose: accessing networks, devices or accounts without permission is not supported'),
    (r'\b(?:steal|harvest|exfiltrate|phish)\w*\b.{0,80}\b(?:passwords?|credentials?|card numbers?|logins?)\b', DEFENSIVE,
     'An authorized purpose: accessing networks, devices or accounts without permission is not supported'),
    (r'\b(?:locate|track(?:ing)?|stalk\w*|home address of|address of)\b.{0,40}\b(?:' + OTHERS + r'|someone|a person|this person|a private person)'
     r'|\b(?:where|find)\b.{0,40}\b(?:' + OTHERS + r'|this person)\b.{0,30}\b(?:lives?|living|address|located|is now)\b', None,
     'A lawful purpose: locating or tracking a private person is not supported'),
    (r'\b(?:make|making|build|building|synthesi[sz]e|synthesi[sz]ing|produce|producing)\b.{0,40}\b(?:explosives?|bombs?|weapons?|nerve agents?|poisons?|meth(?:amphetamine)?)\b', None,
     'A safe purpose: instructions for weapons, explosives or dangerous substances are not supported'),
    (r'\bignore\b.{0,30}\b(?:previous|prior|all|above|your)\b.{0,20}\binstructions?\b|\b(?:delete|erase|remove)\s+(?:everything|all (?:my |your |the )?(?:data|files|records|workflows))\b', None,
     'A search goal: instructions to override the workflow or delete data are not followed'),
)
REFUSAL_LABELS = frozenset(label for _, _, label in REFUSED) | {'A goal without credentials, card numbers or unauthorized access'}


VERB = re.compile(r'\b(?:check|convert|turn|calculate|compute|sum|average|notify|alert|warn|tell|activate|switch|draw|generate|create|make|render|'
                  r'buy|book|pay|purchase|send|e-?mail|monitor|track|translate|summari[sz]e|get|find|search|fetch|look|show|give|list|watch)\b', re.I)


def unsupported(objective):
    """Labels of requested capabilities that no reviewed workflow step provides.

    A clause without a verb continues a list ("documentation for the prices API and the
    invoices API"), so it names a subject, not a capability."""
    text = re.sub(r'\b(?:turn|switch)\s+(?:on|off)\b', 'activate', positive_text(objective), flags=re.I)
    actions = [action for index, action in enumerate(_actions(text)) if index == 0 or VERB.search(action)]
    return [label for label, pattern in UNSUPPORTED if any(re.search(pattern, action, re.I) for action in actions)]


def refused(objective):
    """The reason a goal is refused outright, or None."""
    from .concierge.chat_guidance import review
    text = str(objective or '')
    for pattern, exempt, label in REFUSED:
        if re.search(pattern, text, re.I) and not (exempt is not None and exempt.search(text)):
            return label
    if review(text) == 'needs_redaction':
        return 'A goal without credentials, card numbers or unauthorized access'
    return None


RESTATE = ('An English goal: the request could not be translated reliably. Restate it in English, for example '
           '"Find recent news about quantum computing, then related research papers".')


def unverifiable(objective):
    """A goal whose subject has no English words: a generated query could not be checked against it."""
    from .workflow_goal_policy import search_topic
    words = {word.lower() for word in re.findall(r'[A-Za-z][A-Za-z0-9+#.-]{2,}', search_topic(str(objective or '')))}
    return None if words - KIND_WORDS else RESTATE


KIND_WORDS = frozenset('news headlines papers paper research studies study documentation docs document documents articles article '
                       'literature sources source references find search latest recent newest related supporting the and then'.split())


def unclear(objective):
    """The requirement to show when a goal names neither a search kind nor a missing capability."""
    return None if SEARCH_KINDS.search(positive_text(objective)) else CLARIFY


def explain(objective, fallback):
    """The most specific reason a goal produced no plan: what is missing, or what to describe."""
    return unsupported(objective) or [unclear(objective) or fallback]


def _actions(objective):
    """The requested action of each clause, without its topic ("papers about payments" asks for papers)."""
    for clause in re.split(r'\b(?:and|then)\b|[,;.]', objective, flags=re.I):
        yield re.split(r'\b(?:about|regarding|concerning|on|related to|for)\b', clause, maxsplit=1, flags=re.I)[0]


def requirements(objective):
    stages=set(_mentions(objective))
    return [(contract,label) for contract,label,pattern in FAMILIES if (contract in stages if contract in ('docs.search.v1','news.search.v1') else re.search(pattern,positive_text(objective),re.I))]


def missing(objective, contracts):
    unavailable=[label for contract,label in requirements(objective) if contract not in contracts]
    # "Compare prices of A and B" is already the product comparison it names.
    unavailable+=[label for label in unsupported(objective)
                  if not (label == 'Prices, quotes or market data' and 'Product comparison' in unavailable)]
    unavailable+=[label for label,pattern in ACTIONS if any(re.search(pattern,action,re.I) for action in _actions(positive_text(objective)))]
    if any(re.search(r'\b(?:summari[sz]e|summari[sz]ation|summary|digest|translate|translation)\b',action,re.I) for action in _actions(positive_text(objective))):
        unavailable.append('Written synthesis or translation (supported search steps return sources only)')
    return unavailable


def incomplete(labels, model_calls):
    message = ('Describe what the workflow should find before a plan is proposed.' if labels == [CLARIFY] else
               'This goal is not supported. No plan was proposed.' if any(label in REFUSAL_LABELS for label in labels) else
               'This goal needs capabilities that are not available in the reviewed workflow. Narrow the goal or choose supported tasks.')
    return {'state':'needs_details','missing_requirements':labels,
        'message':message,
        'model_calls':model_calls,'agent_calls':0,'automatic_execution':False}


_LEAD = re.compile(r'^(?:please\s+)?(?:look\s+up|find|search(?:\s+for)?|get|fetch|collect|gather|check)\s+', re.I)
_TAIL = re.compile(r'\s+(?:documentation|docs|documents?|papers?|research|guides?|references?)$', re.I)
_SUBJECT = re.compile(r'^.*?\b(?:documentation|docs|papers?|research)\s+(?:for|about|on)\s+', re.I)
_KINDS = r'(?:news|research|papers?|documentation|docs)'
_MIXED = re.compile(r'^(?:please\s+)?(?:look\s+up|find|search(?:\s+for)?|get)?\s*(?:the\s+)?(?:(?:latest|recent)\s+)?'+_KINDS+r'\s+(?:about|on|for)\s+(?P<first>.+?)'
                    r'\s+and\s+(?:(?:the\s+)?(?:latest|recent)\s+)?'+_KINDS+r'\s+(?:about|on|for)\s+(?P<second>.+?)\.?$', re.I)
_OWNER_NOISE = re.compile(r'\b(?:the|a|an|some|any|latest|recent|current|official|public|relevant|english|online|'
                          r'technical|academic|scientific|research|papers?|documentation|docs|news)\b', re.I)
_SEPARATE = re.compile(r'\b(?:separately|independently|respectively|in parallel|individually)\b|\uac01\uac01', re.I)
_ADVERB = re.compile(r'\s*\b(?:separately|independently|respectively|in parallel|individually|each)\b\s*$', re.I)
# "then find supporting documentation" continues the first subject; it names no subject of its own.
_FOLLOW_UP = re.compile(r'^(?:cross-?check|compare|verify|validate|summari[sz]e|combine|merge|review|confirm)\b|\b(?:second|another|previous|prior|results?|sources?)\b'
                        r'|^(?:(?:please\s+)?(?:look\s+up|find|search(?:\s+for)?|get|fetch|collect|gather|check)\s+)?(?:the\s+)?(?:supporting|related|relevant|additional|further|more|background|matching|corresponding|follow-?up)\b', re.I)
_KIND = re.compile(r'\b(documentation|docs|papers?|research)\b', re.I)


_STEP_SPLIT = re.compile(r'\s*(?:,?\s*\bthen\b|\bfollowed by\b|;|,?\s*\band\b(?=\s+(?:also\s+)?(?:find\s+|search\s+(?:for\s+)?)?(?:the\s+)?'
                         r'(?:(?:latest|recent|newest|current|top\s+\d+)\s+)*(?:news|headlines|research|papers?|academic|scholarly|documentation|docs)\b))\s*', re.I)
_STEP_KIND = re.compile(r'\b(?:the\s+)?(?:(?:latest|recent|newest|current|top\s+\d+)\s+)*(?:news(?:\s+stories)?|headlines|(?:academic\s+|scholarly\s+)?'
                        r'(?:research\s+)?papers?|research|studies|documentation|docs|articles)\b', re.I)


def step_subjects(objective, count):
    """The subject each step of "news about X, then papers on Y" names, aligned with its steps.

    The model returns one query for the first subject; without this, later steps searched
    it again (2026-11-01: "then research papers on cryptocurrency volatility" searched
    "Bitcoin prices research"). A follow-up step without its own subject ("then supporting
    sources") is None and keeps the first subject. None when the clauses do not line up."""
    text = _ADVERB.sub('', ' '.join(positive_text(str(objective or '')).split())).strip(' .')
    text = _SEPARATE.sub(' ', text)
    clauses = [clause for clause in _STEP_SPLIT.split(text) if clause.strip(' .,;')]
    if count < 2 or len(clauses) != count:
        return None
    subjects = []
    for index, clause in enumerate(clauses):
        clause = clause.strip(' .,;')
        if index and _FOLLOW_UP.search(re.sub(r'^(?:also|and)\s+', '', clause, flags=re.I)):
            subjects.append(None)
            continue
        subject = _STEP_KIND.sub(' ', _LEAD.sub('', re.sub(r'^(?:also|and)\s+', '', clause, flags=re.I)))
        subject = re.sub(r'\b(?:about|on|regarding|concerning|for|of)\b', ' ', subject, flags=re.I)
        subject = ' '.join(subject.split()).strip(' .,;')
        subjects.append(subject if len(subject) >= 3 else None)
    # "news and research papers on X": the subject stated once at the end belongs to every step.
    if subjects[0] is None and subjects[-1] and all(subject in (None, subjects[-1]) for subject in subjects):
        subjects = [subjects[-1]] * len(subjects)
    return subjects if subjects[0] else None


_OTHER_KIND = {'news.search.v1': re.compile(r'\b(?:research|papers?|studies|documentation|docs|literature)\b', re.I),
               'docs.search.v1': re.compile(r'\b(?:news|headlines)\b', re.I)}


def apply_step_subjects(objective, nodes, listed=()):
    """Write each step's own subject into its literal query; returns NODES.

    A follow-up step ("then related papers") keeps the proposed query. The first step is
    rewritten only when later steps name their own subjects, or when its query carries the
    other step's request ("latest news and research papers on X" for the news step)."""
    subjects = step_subjects(objective, len(nodes))
    if not subjects or len(listed) >= 2 and not all(subjects):
        return nodes  # an explicit list already gave every step its subject
    later = any(subjects[1:])
    for index, (node, subject) in enumerate(zip(nodes, subjects)):
        if not subject or 'query' in (node.get('bindings') or {}) or type(node.get('input')) is not dict:
            continue
        query = str(node['input'].get('query') or '')
        mixed = _OTHER_KIND.get(node.get('contract_id'))
        if index == 0 and not later and not (mixed and mixed.search(query)):
            continue
        node['input'] = {**node['input'], 'query': subject}
    return nodes


def topics(objective, limit=10):
    """Explicitly listed subjects, one search step each.

    Only clear lists qualify: "for 3 topics: A, B, C", "documentation for A, B and C"
    or "A documentation, then B documentation". Anything else keeps the model plan.
    """
    text = ' '.join(positive_text(str(objective or '')).split())
    # Independent searches of different kinds ("news about X and research on Y separately")
    # name one subject per task; a connected chain keeps the model plan.
    mixed = _MIXED.match(text)
    if mixed and _SEPARATE.search(text):
        return [_ADVERB.sub('', mixed['first']).strip(' .,;'), _ADVERB.sub('', mixed['second']).strip(' .,;')]
    # A mixed-contract chain is never a list of independent documentation topics.
    if 'news.search.v1' in _mentions(text):return []
    text=re.split(r'\busing\s+(?:exactly\s+)?(?:[0-9]+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:read-only\s+)?steps?\b',text,maxsplit=1,flags=re.I)[0].strip()
    items = None
    if ':' in text:
        head, _, tail = text.partition(':')
        if re.search(r'\b(?:topics?|subjects?|tools?|products?|libraries|frameworks|items?)\b', head, re.I):
            items = re.split(r',\s*|\s+and\s+', tail)
    if items is None and re.search(r',\s*then\b|\bthen\b', text, re.I):
        parts = [part.strip(' ,.') for part in re.split(r',?\s*\bthen\b\s*', text, flags=re.I)]
        # "then cross-check the result" is a follow-up action, not another subject.
        if any(_FOLLOW_UP.search(part) for part in parts[1:]):
            return []
        items = [_TAIL.sub('', _SUBJECT.sub('', _LEAD.sub('', part))) for part in parts]
    if items is None:
        found = re.search(r'^(.*?)\b(?:documentation|docs|papers?|research)\s+(?:for|about|on)\s+(.+)$', text, re.I)
        if found and re.search(r',|\band\b', found.group(2)):
            items = re.split(r',\s*(?:and\s+)?|\s+and\s+', found.group(2))
            # "Kubernetes documentation about rollouts and rollbacks": each item is an aspect
            # of the named product, which a search without that name cannot find.
            owner = ' '.join(_OWNER_NOISE.sub(' ', _LEAD.sub('', found.group(1).lstrip())).split())
            if owner and len(owner) <= 40:
                items = [item if owner.lower() in item.lower() else owner + ' ' + item.strip() for item in items]
    if items is None and _SEPARATE.search(text):
        # "Docker documentation and Kubernetes documentation separately": each part names its own subject.
        body = _ADVERB.sub('', _LEAD.sub('', text.strip(' .'))).strip(' .,;')
        parts = [part.strip() for part in re.split(r',\s*(?:and\s+)?|\s+and\s+', body)]
        if len(parts) >= 2 and all(_TAIL.search(part) for part in parts):
            items = [_TAIL.sub('', part) for part in parts]
    result = []
    for item in items or []:
        item = _ADVERB.sub('', item.strip(' .;')).strip(' .;')
        if 2 <= len(item) <= 80 and item.lower() not in {value.lower() for value in result}:
            result.append(item)
    if len(result) < 2:
        return []
    kind = _KIND.search(text)
    suffix = '' if not kind else ' ' + ('documentation' if kind.group(1).lower() in ('documentation', 'docs') else 'research')
    declared=re.search(r'\b(\d+)\s+(?:topics?|subjects?)\b',text,re.I)
    if len(result)>limit or declared and int(declared[1])!=len(result):
        raise GoalNeedsDetails('List at most ten distinct subjects and make the stated subject count match the list.')
    return [item if item.lower().endswith(suffix.strip().lower()) else item + suffix for item in result]
