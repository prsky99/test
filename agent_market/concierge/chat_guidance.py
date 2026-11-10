"""Bounded interaction guidance; never execute a task or grant authority."""
import re

PAN = re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)')
# "my password is hunter2" discloses a secret as plainly as "password: hunter2" (2026-11-01 evaluation).
SECRET = re.compile(r'(?i)\b(?:api[_ -]?key|password|passcode|access[_ -]?token|secret)\s*[:=]\s*[^\s,;]+|\bBearer\s+\S+|\bvt_[A-Za-z0-9_-]{16,96}'
                    r'|\b(?:password|passcode|passphrase|pin(?: code)?)\s+is\s+[^\s,;.]+|(?:\ube44\ubc00\ubc88\ud638|\uc554\ud638)\s*(?:\ub294|\uc740|:|=)\s*[^\s,;.]{4,}')
MESSAGES = {
    'needs_redaction': 'Remove card numbers, passwords and access keys before describing your task. No action was run.',
    'needs_authorized_task': 'I cannot help access a network, device or account without permission, or steal credentials. Describe an authorized security test or a defensive task instead.',
    'unsupported_guarantee': 'Lottery results cannot be guaranteed. I can help find probability or statistics tools instead.',
    'needs_scope': 'What would you like to do, and what result do you need? For example, summarize meeting notes or compare two documents.',
    'needs_goal': 'What should an agent do for you? For example: answer customer emails, analyze sales data, or monitor your website.',
    'out_of_scope': 'I recommend agents and published workflows rather than answering questions directly. Describe a task, such as searching the web or looking up country facts.',
    'needs_workflow': 'This request contains separate tasks. Which should come first? You can also ask for a workflow that connects the steps.',
    'action_review_required': 'I can recommend an agent, but no message, reservation or purchase has been made. Review the agent in Workspace before authorizing an action.',
}


def _card(value):
    digits = re.sub(r'\D', '', value)
    if not 13 <= len(digits) <= 19:return False
    values = [int(n) for n in digits]
    return sum(n if i % 2 else n*2-9 if n*2>9 else n*2 for i,n in enumerate(values[::-1],1)) % 10 == 0


def redacted(text):
    return SECRET.sub('[Sensitive information removed]',PAN.sub(
        lambda m:'[Card number removed]' if _card(m.group()) else m.group(),str(text)))


def review(text):
    if redacted(text) != text:return 'needs_redaction'
    if re.search(r'\b(?:steal|harvest|exfiltrate)\b.{0,80}\b(?:passwords?|credentials?|card numbers?)\b|\bhack\b.{0,40}\b(?:someone|another person)\b',text,re.I):
        return 'needs_authorized_task'
    if (re.search(r'\b(?:hack|crack|break into|bypass)\b.{0,40}\b(?:wi-?fi|wireless|network|router|phone|account|password|email|camera)s?\b|\ud574\ud0b9',text,re.I)
            and not re.search(r'\b(?:my own|authori[sz]ed|pen(?:etration)?[- ]?test\w*|security audit|defen[cs]\w*|protect)\b',text,re.I)):
        return 'needs_authorized_task'
    if VAGUE_GOAL.fullmatch(text.strip()):
        return 'needs_goal'
    if re.search(r'\b(?:lottery|lotto)\b',text,re.I) and re.search(r'100\s*(?:%|percent)|guarantee|always win|winning numbers',text,re.I):
        return 'unsupported_guarantee'
    if re.fullmatch(r'(?:please\s+)?(?:compare|send|summari[sz]e|translate|search|find|help me|do it|something|anything|recommend)(?:\s+it)?[.!?]*',text.strip(),re.I):
        return 'needs_scope'
    if not re.search(r'\bworkflow\b',text,re.I) and re.search(r'\b(?:and|then)\b',text,re.I):
        domains = (r'\bweather\b',r'\bnews\b',r'\b(?:email|mail)\b',r'\b(?:generate|create)\b.{0,20}\bimage\b',r'\bresearch papers?\b')
        if sum(bool(re.search(pattern,text,re.I)) for pattern in domains)>1:return 'needs_workflow'
    return None


VAGUE_GOAL = re.compile(r'(?:please\s+)?(?:help\s+(?:me\s+)?)?(?:make|improve|grow|boost|optimi[sz]e|fix|help)\s+(?:my|our)\s+'
                       r'(?:business|company|startup|life|work|team|shop|store|project)(?:\s+(?:better|grow|succeed|more successful|work))?[.!?]*'
                       r'|(?:(?:can|could) you )?help(?: me)? with (?:my|our|the) (?:project|work|business)[.!?]*', re.I)
QUESTION = re.compile(r'^\s*(?:what|who|when|where|why|which|how (?:many|much|old|far|tall|long))\b', re.I)
EXAMPLES = ('Weather forecast for Seoul', 'Translate a document into Spanish', 'Search GitHub issues', 'Summarize meeting notes')
PRONOUN = re.compile(
    r'(?:it|this one|that one|this agent|that agent)[.!?]*'
    r'|(?:how (?:do|can|should) i |how to |can i |help me |show me how to )?(?:connect(?: to)?|call|use|access|integrate|set ?up|try)\s+'
    r'(?:it|this|that|this one|that one|this agent|that agent)(?:\s+(?:agent|one))?[.!?]*'
    r'|(?:(?:can|could) you )?(?:tell me )?more about (?:it|this|that)[.!?]*'
    r'|(?:what about|explain) (?:it|this one|that one)[.!?]*'
    r'|(?:calling|connection)\s+details(?: for (?:it|this|that))?[.!?]*'
    r'|how to (?:call|connect|use|integrate|reach)(?: (?:it|this|that))?[.!?]*'
    r'|(?:\uadf8(?:\uac70|\uac83)?\s*)?(?:\uc5b4\ub5bb\uac8c\s*(?:\uc5f0\uacb0|\ud638\ucd9c|\uc0ac\uc6a9|\uc811\uad7c|\uc2e4\ud589|\uc368)|\uc5f0\uacb0\s*\ubc29\ubc95|\ud638\ucd9c\s*\ubc29\ubc95|\uc0ac\uc6a9\s*\ubc95|\uc0ac\uc6a9\ubc29\ubc95|\uc0c1\uc138\s*\uc815\ubcf4|\uc790\uc138\ud788|\uc790\uc138\ud55c\s*\uc815\ubcf4).*',
    re.I
)


def pronoun_reference(text):
    """'how do I connect to it?' refers to the recommendation last discussed."""
    return bool(PRONOUN.fullmatch(str(text or '').strip()))


def condition_question(text):
    """A question about the selected agent is not a new discovery request."""
    return bool(re.match(r'^(?:does|can|will|would|is)\s+(?:it|this (?:one|agent)|that (?:one|agent))\b',
                         str(text or '').strip(), re.I))


LIST_SPLIT = re.compile(r'\s*(?:,|;|\band also\b|\bas well as\b|\bplus\b|\band\b)\s*', re.I)
LEAD = re.compile(r'^\s*(?:i\s+(?:need|want|am looking for|would like)|(?:please\s+)?(?:find|get|give|show)(?: me)?|recommend)\s+', re.I)


def separate_requests(task):
    """'weather data, a translator and a stock price feed' names three separate capabilities.

    Returns [] unless every part names its own capability; a phrase such as
    'weather forecast and alerts' is one capability with a condition."""
    from .selection import capability_terms
    parts = [part.strip(' .!?') for part in LIST_SPLIT.split(LEAD.sub('', str(task or ''))) if part and part.strip(' .!?')]
    if not 2 <= len(parts) <= 3:
        return []
    # "A, B and C" is a list; without one, each part must be a phrase of its own.
    if not re.search(r'[,;]', str(task)) and any(len(re.findall(r'[^\W\d_]{2,}', part)) < 2 for part in parts):
        return []
    cores = [set(capability_terms(part)) for part in parts]
    if any(not core or len(core) > 3 for core in cores):
        return []
    if any(cores[i] & cores[j] for i in range(len(cores)) for j in range(i + 1, len(cores))):
        return []
    if all(core <= {'weather','forecast','temperature'} for core in cores):
        return []  # Current weather and tomorrow's forecast share the same region.
    return parts


def action_request(text):
    return bool(re.search(r'\b(?:send\b.{0,30}\b(?:email|message)|book\b.{0,30}\b(?:flight|hotel|ticket)|purchase\b)',text,re.I))


def ordinal(text):
    value = text.lower().strip(' .!?')
    mapping = {
        'first': 1, 'second': 2, 'third': 3, '1st': 1, '2nd': 2, '3rd': 3,
        '\uccab \ubc88\uc9f8': 1, '\ub450 \ubc88\uc9f8': 2, '\uc138 \ubc88\uc9f8': 3,
        '\uccab\ubc88\uc9f8': 1, '\ub450\ubc88\uc9f8': 2, '\uc138\ubc88\uc9f8': 3,
        '1\ubc88\uc9f8': 1, '2\ubc88\uc9f8': 2, '3\ubc88\uc9f8': 3,
        '1\ubc88': 1, '2\ubc88': 2, '3\ubc88': 3,
    }
    value = re.sub(r'^(?:(?:can|could) you |please )?', '', value)
    value = re.sub(r'^(?:what about |show (?:me )?|tell me (?:more )?about )?(?:the |that |this )?', '', value)
    value = re.sub(r'^(?:\uadf8|\uc774|\uc800)\s*', '', value)
    value = re.sub(r'\s+(?:one|option|agent|result)$', '', value)
    value = re.sub(r'\s*(?:\uac83|\uac70|\ubc88\uc9f8|\ubc88)$', '', value)
    if value in mapping:
        return mapping[value]
    if value in ('\uccab', '1'):
        return 1
    if value in ('\ub450', '2'):
        return 2
    if value in ('\uc138', '3'):
        return 3
    # Follow-ups that point at a listed result inside a longer sentence.
    words = {'first': 1, 'second': 2, 'third': 3, '1st': 1, '2nd': 2, '3rd': 3}
    lowered = text.lower()
    found = (re.search(r'\b(first|second|third|1st|2nd|3rd)\s+(?:one|option|agent|result|recommendation|pick|choice)s?\b', lowered)
           or re.search(r'\b(?:about|on|with|to|me|use|try|pick|choose|want|open|connect)\s+(?:the|that)\s+(first|second|third|1st|2nd|3rd)\s*[?.!]*$', lowered)
           or re.search(r'(?:^|\s)(?:option|number|no\.|#)\s*([123])\b', lowered))
    if found:
        return words.get(found.group(1)) or int(found.group(1))
    korean = (re.search(r'(?:\uadf8\s*)?([123]|\uccab|\ub450|\uc138)\s?\ubc88(?:\s?\uc9f8)?', text)
              or re.search(r'([123])\s*\ubc88\s*\uc5d0\uc774\uc804\ud2b8', text))
    if korean:
        k_map = {'\uccab': 1, '\ub450': 2, '\uc138': 3, '1': 1, '2': 2, '3': 3}
        return k_map.get(korean.group(1))
    return None
