"""Bounded, local query interpretation; never grants execution authority.

Keep the original request for admission. Positive retrieval text and exclusions
are separate so a prohibition cannot become a requested capability.
"""
from dataclasses import dataclass
import re

_NEGATIVE = re.compile(
    r"\b(?:do\s+not|don't|never|without|exclud(?:e|ing)|except|no(?!\s+(?:less|more|later|earlier)\b)|not(?!\s+only\b)|avoid)\b"
    r"[^.;!\n]*?(?=\b(?:but|instead|using|with|then)\b|[.;!\n]|$)", re.I)
_KOREAN_NEGATIVE = re.compile(
    r'(?P<phrase>[A-Za-z0-9_-]+|\ub274\uc2a4|\ubc88\uc5ed|\uc694\uc57d|\ubb38\uc11c|\ub17c\ubb38|\uacbd\uc81c\uc9c0\ud45c)'
    r'(?:\uc740|\ub294|\uc744|\ub97c)?\s*\uc81c\uc678(?:\ud558\uace0|\ud574\uc918|\ud574|\ud55c)?')
_SUBJECT_ALIASES = {'\ud30c\uc774\uc36c': 'Python', '\uc790\ubc14\uc2a4\ud06c\ub9bd\ud2b8': 'JavaScript',
                    '\ub3c4\ucee4': 'Docker', '\ucfe0\ubc84\ub124\ud2f0\uc2a4': 'Kubernetes'}
_GENERIC = frozenset('find search get fetch collect show tell please recommend use using create generate build workflow workflows template templates agent agents named called the a an only in then next first second third documentation docs document documents news headlines research papers paper references reference public api apis mcp a2a json pdf csv english korean japanese spanish french german ai'.split())
_REQUEST_VERBS = frozenset('necesito busca buscar quiero encuentra buscarme puedes'.split())


@dataclass(frozen=True)
class QueryIntent:
    original: str
    positive: str
    excluded: tuple[str, ...]

    def retrieval_text(self, canonical):
        """Keep canonical capability aliases and the entire positive request."""
        if canonical.casefold() == self.positive.casefold():
            return self.positive
        return canonical + ' for ' + self.positive


def interpret(query):
    original = str(query or '').replace('\0', ' ').strip()[:16384]
    excluded = []

    def korean(match):
        excluded.append(match['phrase'])
        return ' '

    positive = _KOREAN_NEGATIVE.sub(korean, original)

    def english(match):
        phrase = re.sub(r"^(?:do\s+not|don't|never|without|exclud(?:e|ing)|except|no|not|avoid)\b", '', match[0], flags=re.I).strip()
        if phrase:
            excluded.append(phrase)
        return ' '

    positive = _NEGATIVE.sub(english, positive)
    return QueryIntent(original, ' '.join(positive.split()).strip(' ,;'), tuple(excluded))


def subject_text(text):
    for alias, name in _SUBJECT_ALIASES.items():
        text = text.replace(alias, name)
    return text


def named_subjects(text):
    """Protect literal named subjects; this is deliberately not a general NER."""
    text = subject_text(interpret(text).positive)
    return tuple(dict.fromkeys(word.casefold() for word in re.findall(
        r'(?<![\w])(?:[A-Z][A-Za-z0-9+#_.-]{1,79})(?![\w])', text)
        if word.casefold().rstrip('.') not in _GENERIC | _REQUEST_VERBS))


def missing_subjects(original, proposed):
    text = subject_text(str(proposed)).casefold()
    return tuple(word for word in named_subjects(original)
                 if not re.search(r'(?<![\w])' + re.escape(word.rstrip('.')) + r'(?![\w])', text))


def explicit_name(query):
    """Only explicit name requests or short proper-name literals take a shortcut."""
    text = interpret(query).positive
    match = re.fullmatch(r'(?:find|show|look up)\s+(?:the\s+)?(?:agent|tool)\s+(?:named|called)\s+["\']?(.+?)["\']?[.!]?', text, re.I)
    if match:
        return match[1].strip(' \"\'.!')[:120]
    if 0 < len(text) <= 80 and re.fullmatch(r'["\'][^"\']+["\']', text):
        return text[1:-1]
    words = text.split()
    if (1 <= len(words) <= 5 and words[0].casefold() not in _GENERIC
            and all(re.fullmatch(r'[A-Z][A-Za-z0-9_-]+', word) for word in words)
            and any(word.casefold() not in _GENERIC for word in words)):
        return text
    return None
