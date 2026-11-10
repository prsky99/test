"""A search that finds nothing tries shorter forms of the query (11-10 research design 4)."""
from agent_market.concierge import hybrid_explore as hx


def test_relaxed_forms_drop_modifiers_and_numbers_first_then_trailing_words():
    assert hx.relaxed_queries('crypto price json output 714') == ['crypto price', 'crypto']
    assert hx.relaxed_queries('what time is it in seoul') == ['time seoul', 'time']
    assert hx.relaxed_queries('weather') == []


def test_an_empty_search_returns_the_first_relaxed_form_that_finds_something(monkeypatch):
    asked = []

    def fake(source, engine, query, *args):
        asked.append(query)
        return {'items': [{'id': 1}] if query == 'crypto price' else [], 'total': 0}
    monkeypatch.setattr(hx, '_scoped_explore', fake)
    result = hx.scoped_explore(None, None, 'crypto price json output 714', None, None, False, False, 45)
    assert result['items'] == [{'id': 1}] and result['relaxed_query'] == 'crypto price'
    assert asked == ['crypto price json output 714', 'crypto price']
    asked.clear()
    found = hx.scoped_explore(None, None, 'crypto price', None, None, False, False, 45)
    assert 'relaxed_query' not in found and asked == ['crypto price']
