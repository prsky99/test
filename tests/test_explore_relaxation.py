"""Explore never answers nothing for a query that only carries extra words (11-10/11 research design 4)."""
from agent_market.concierge import hybrid_explore as hx


def test_numbers_and_delivery_words_are_removed_before_the_first_search():
    assert hx.cleaned_query('book flights json output 981') == 'book flights'
    assert hx.cleaned_query('legal contract review small business 180') == 'legal contract review small business'
    # Function words go first; real conditions stay (11-11 PM review).
    assert hx.cleaned_query('speech to text in korea') == 'speech text korea'
    assert hx.cleaned_query('shipping tracking with history') == 'shipping tracking history'
    assert hx.cleaned_query('weather forecast') is None  # nothing to remove


def test_relaxed_forms_drop_conditions_then_a_leading_and_a_trailing_word():
    assert hx.relaxed_queries('book flights') == ['flights', 'book']
    assert hx.relaxed_queries('speech text korea')[:2] == ['speech text', 'text']
    assert hx.relaxed_queries('invoice ocr agents')[0] == 'invoice ocr'
    assert hx.relaxed_queries('weather') == []


def _fake(found):
    asked = []

    def search(source, engine, query, *args):
        asked.append(query)
        return {'items': [{'id': 1}] if query in found else [], 'total': 0}
    return asked, search


def test_the_cleaned_query_is_searched_first_and_named(monkeypatch):
    asked, search = _fake({'speech text korea'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, None, 'speech to text in korea', None, None, False, False, 45)
    assert result['items'] and result['relaxed_query'] == 'speech text korea'
    assert asked == ['speech text korea']  # one search, no extra time
    asked2, search2 = _fake({'speech text'})
    monkeypatch.setattr(hx, '_scoped_explore', search2)
    found = hx.scoped_explore(None, None, 'speech to text in korea', None, None, False, False, 45)
    assert found['relaxed_query'] == 'speech text' and asked2 == ['speech text korea', 'speech text']


def test_an_empty_search_tries_the_object_before_the_verb(monkeypatch):
    asked, search = _fake({'flights'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, None, 'book flights json output 981', None, None, False, False, 45)
    assert result['relaxed_query'] == 'flights' and asked == ['book flights', 'flights']
    asked.clear()
    plain = hx.scoped_explore(None, None, 'flights', None, None, False, False, 45)
    assert 'relaxed_query' not in plain and asked == ['flights']
