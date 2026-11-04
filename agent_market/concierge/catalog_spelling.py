"""Correct one-letter typos in a request against the words listings actually use (2026-11-04).

Stage 1 of the 99% plan: of 161 Chat misses that a canonical phrase would have answered, 37
were one-letter typos ("dierctions", "sttaus", "liuqidity") that then became required capability
words, so retrieval and admission both failed. A word is changed only when it appears in no
listing vocabulary (catalog_vocabulary.json, built by scripts/build_catalog_vocabulary.py) and
exactly one edit away there is a word that at least MIN_REPLACEMENT listings use, ten times
more common than any other such word. The first letter is never changed ("jingle" stays, not
"single"), and neither are capitalized words inside a sentence ("Downing Street"), acronyms,
short words or words with digits.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 5
MIN_REPLACEMENT = 50
AMBIGUITY = 10
LETTERS = 'abcdefghijklmnopqrstuvwxyz'
WORD = re.compile(r'(?<![\w.@/-])[A-Za-z]{%d,20}(?![\w@/-])' % MIN_LENGTH)


@lru_cache(maxsize=1)
def vocabulary():
    path = Path(__file__).with_name('catalog_vocabulary.json')
    try:
        return json.loads(path.read_text(encoding='utf-8'))['words']
    except (OSError, ValueError, KeyError):
        return {}


def _edits(word):
    # Edits after the first letter only: typos there were rare, and changes there renamed real words.
    splits = [(word[:i], word[i:]) for i in range(1, len(word) + 1)]
    deletes = (a + b[1:] for a, b in splits if b)
    swaps = (a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1)
    replaces = (a + c + b[1:] for a, b in splits if b for c in LETTERS if c != b[0])
    inserts = (a + c + b for a, b in splits for c in LETTERS)
    return set(deletes) | set(swaps) | set(replaces) | set(inserts)


@lru_cache(maxsize=4096)
def corrected_word(word):
    """The listing word one edit from WORD, or None when WORD is known or nothing common is close."""
    words = vocabulary()
    lower = word.lower()
    if not words or lower in words or word.isupper():
        return None
    near = sorted(((words[w], w) for w in _edits(lower) if words.get(w, 0) >= MIN_REPLACEMENT), reverse=True)
    # "wether" is weather or whether: a correction must be clearly the likelier word.
    if not near or len(near) > 1 and near[0][0] < AMBIGUITY * near[1][0]:
        return None
    return near[0][1]


def respell(text):
    """TEXT with each correctable typo replaced; everything else, including case, is kept."""
    if type(text) is not str or not text:
        return text
    def fix(match):
        word = match.group(0)
        start = match.start()
        if word[0].isupper() and text[:start].strip() and not re.search(r'[.!?:]\s*$', text[:start]):
            return word  # a capitalized word inside a sentence is a name
        better = corrected_word(word)
        if not better:
            return word
        return better.capitalize() if word[0].isupper() else better
    return WORD.sub(fix, text)
