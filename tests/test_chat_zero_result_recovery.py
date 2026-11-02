"""Chat requests whose own words found nothing get bounded, verified second searches (2026-11-01)."""
import time

import pytest

from agent_market.concierge import fast_chat as fc
from agent_market.concierge.chat_guidance import review


def tool(name, description):
    return {'name': name, 'tools': [name], 'tools_schema': [{'name': name, 'description': description}]}


def test_shared_words_replace_subject_words(monkeypatch):
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    texts = ['remote jobs board'] * 6 + ['remote work jobs api'] * 4 + ['software engineering jobs digest']
    monkeypatch.setattr('agent_market.concierge.discovery.candidates',
                        lambda *a, **k: [{'_rank_text': text} for text in texts])
    monkeypatch.setattr(fc, 'catalog_share', lambda store, term: 0.01)
    assert fc.capability_focus(object(), None, 'find remote software engineering jobs') == 'remote jobs'


def test_subjects_qualifiers_and_generic_words_never_lead(monkeypatch):
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    rows = [{'_rank_text': 'restaurants near times square guide'}] * 4 + [{'_rank_text': 'restaurants nearby'}] * 6
    monkeypatch.setattr('agent_market.concierge.discovery.candidates', lambda *a, **k: rows)
    monkeypatch.setattr(fc, 'catalog_share', lambda store, term: 0.001)
    # "Times Square" is a capitalized subject and "near" a qualifier; restaurants remains.
    assert fc.capability_focus(object(), None, 'find restaurants near Times Square') == 'restaurants'
    # A remaining word that most of the catalog contains cannot stand alone.
    monkeypatch.setattr(fc, 'catalog_share', lambda store, term: 0.3)
    assert fc.capability_focus(object(), None, 'find restaurants near Times Square') is None


def test_one_word_needs_the_shortlist_to_converge(monkeypatch):
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    rows = [{'_rank_text': 'landscape survey'}] * 2 + [{'_rank_text': 'unrelated'}] * 18
    monkeypatch.setattr('agent_market.concierge.discovery.candidates', lambda *a, **k: rows)
    monkeypatch.setattr(fc, 'catalog_share', lambda store, term: 0.0001)
    assert fc.capability_focus(object(), None, 'create an illustration of a mountain landscape') is None


def test_too_few_candidates_or_one_core_word_change_nothing(monkeypatch):
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    monkeypatch.setattr('agent_market.concierge.discovery.candidates', lambda *a, **k: [{'_rank_text': 'jobs'}] * 3)
    assert fc.capability_focus(object(), None, 'find remote software engineering jobs') is None
    assert fc.capability_focus(object(), None, 'weather') is None


def test_a_narrowed_result_must_state_every_word():
    assert fc.states_every_word(tool('find_restaurants', 'Find restaurants by city'), ['restaurants'])
    assert not fc.states_every_word(tool('about', 'Public Adjusters Directory listings'), ['directions'])
    assert fc.states_every_word(tool('get_route', 'Driving directions between two points'), ['directions'])


def test_unknown_words_are_the_ones_no_listing_contains(monkeypatch):
    monkeypatch.setattr(fc, 'catalog_share', lambda store, term: 0.0 if term in ('wheather', 'pariss') else 0.01)
    assert set(fc.unknown_words(object(), 'wheather in pariss')) <= {'wheather', 'pariss'}
    assert fc.unknown_words(object(), 'wheather in pariss')
    assert fc.unknown_words(object(), 'weather in Paris') == []


def test_catalog_share_is_cached_and_read_through_the_index():
    calls = []

    class Store:
        backend = 'sqlite'

        def query(self, sql, params=()):
            calls.append(sql)
            return [{'c': 200}] if 'MATCH' not in sql else [{'c': 2}]
    store = Store()
    fc._catalog_counts.clear()
    assert fc.catalog_share(store, 'weather') == 0.01
    assert fc.catalog_share(store, 'weather') == 0.01 and len(calls) == 2
    fc._catalog_counts[(id(store), 'weather')] = (time.monotonic() - 7200, 0.5)
    assert fc.catalog_share(store, 'weather') == 0.01  # an hour-old count is read again
    fc._catalog_counts.clear()


def test_stated_passwords_are_redacted_but_password_tasks_are_not():
    assert review('my password is hunter2, log in to my bank') == 'needs_redaction'
    assert review('비밀번호는 abcd1234 이야') == 'needs_redaction'
    assert review('암호: qwerty12') == 'needs_redaction'
    for task in ('password reset tool for my app', 'what is a strong password', '비밀번호 변경하는 방법 알려줘'):
        assert review(task) != 'needs_redaction'


def test_questions_and_long_requests_skip_narrowing():
    assert fc.QUESTION_FORM.match('who won the world cup in 2018')
    assert not fc.QUESTION_FORM.match('find remote software engineering jobs')
    from agent_market.concierge.chat_query_rewrite import SUMMARY_MIN_CHARS
    assert SUMMARY_MIN_CHARS == 100


def test_no_second_retrieval_without_an_enabled_engine(monkeypatch):
    calls = []
    monkeypatch.setattr('agent_market.concierge.discovery.candidates', lambda *a, **k: calls.append(1) or [])
    assert fc.capability_focus(object(), None, 'find remote software engineering jobs') is None
    assert calls == []


@pytest.mark.parametrize('task,terms', [
    ('convert text to speech', ['speech']),
    ('speech to text for meetings', ['speech']),
    ('look up a topic on Wikipedia', ['wikipedia']),
    ('search Wikipedia for black holes', ['wikipedia']),
    ('movie recommendations similar to Inception', ['movie']),
    ('text summarization', ['summarization']),
    ('find popular open source repositories for vector databases', ['repositories']),
    ('create an illustration of a mountain landscape', ['illustration']),
    ('plan a route by bicycle across Amsterdam', ['route', 'bicycle']),
    ('find open source license compliance tools', ['source', 'license', 'compliance']),
])
def test_capability_terms_keep_the_capability_a_boundary_would_drop(task, terms):
    from agent_market.concierge.selection import capability_terms
    assert capability_terms(task) == terms
