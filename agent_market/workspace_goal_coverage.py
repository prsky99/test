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


def _actions(objective):
    """The requested action of each clause, without its topic ("papers about payments" asks for papers)."""
    for clause in re.split(r'\b(?:and|then)\b|[,;.]', objective, flags=re.I):
        yield re.split(r'\b(?:about|regarding|concerning|on|related to|for)\b', clause, maxsplit=1, flags=re.I)[0]


def requirements(objective):
    stages=set(_mentions(objective))
    return [(contract,label) for contract,label,pattern in FAMILIES if (contract in stages if contract in ('docs.search.v1','news.search.v1') else re.search(pattern,positive_text(objective),re.I))]


def missing(objective, contracts):
    unavailable=[label for contract,label in requirements(objective) if contract not in contracts]
    unavailable+=[label for label,pattern in ACTIONS if any(re.search(pattern,action,re.I) for action in _actions(positive_text(objective)))]
    if any(re.search(r'\b(?:summari[sz]e|summari[sz]ation|summary|digest|translate|translation)\b',action,re.I) for action in _actions(positive_text(objective))):
        unavailable.append('Written synthesis or translation (supported search steps return sources only)')
    return unavailable


def incomplete(labels, model_calls):
    return {'state':'needs_details','missing_requirements':labels,
        'message':'This goal needs capabilities that are not available in the reviewed workflow. Narrow the goal or choose supported tasks.',
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
