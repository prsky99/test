"""One-letter typos are corrected against listing words; names and real words are left alone (2026-11-04)."""
import json
from pathlib import Path

import pytest

from agent_market.concierge import catalog_spelling as spelling


@pytest.fixture(autouse=True)
def small_vocabulary(monkeypatch):
    words = {'directions': 154, 'status': 11231, 'liquidity': 4805, 'weather': 2977, 'whether': 9000,
             'forecast': 2831, 'single': 900, 'owning': 60, 'jingle': 2, 'flight': 3000, 'driving': 300}
    monkeypatch.setattr(spelling, 'vocabulary', lambda: words)
    spelling.corrected_word.cache_clear()
    yield
    spelling.corrected_word.cache_clear()


@pytest.mark.parametrize('typed,expected', [
    ('get driving dierctions from Lyon to Nice', 'get driving directions from Lyon to Nice'),
    ('check the sttaus of flight UA 837', 'check the status of flight UA 837'),
    ('find the deepest liuqidity pools', 'find the deepest liquidity pools'),
    ('weather forcast for tomorrow', 'weather forecast for tomorrow'),
])
def test_one_letter_typos_become_listing_words(typed, expected):
    assert spelling.respell(typed) == expected


@pytest.mark.parametrize('text', [
    'geocode 10 Downing Street London',   # a capitalized word inside a sentence is a name
    'compose a short jingle',              # the first letter is never changed
    'wether report',                        # weather or whether: ambiguous, left as typed
    'look up MSFT quotes',                  # acronyms and short words
])
def test_names_real_words_and_ambiguous_typos_are_kept(text):
    assert spelling.respell(text) == text


def test_the_shipped_vocabulary_is_listing_words_only():
    data = json.loads(Path(spelling.__file__).with_name('catalog_vocabulary.json').read_text(encoding='utf-8'))
    assert data['min_documents'] >= 5 and len(data['words']) > 10000
    assert all(word.isascii() and word.isalpha() and word.islower() for word in data['words'])
