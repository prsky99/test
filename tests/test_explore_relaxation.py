"""Explore never answers nothing for a query that only carries extra words (11-10/11 research design 4)."""
from agent_market.concierge import hybrid_explore as hx


def test_numbers_and_delivery_words_are_removed_before_the_first_search():
    assert hx.cleaned_query('book flights json output 981') == 'book flights'
    assert hx.cleaned_query('legal contract review small business 180') == 'legal contract review small business'
    # Function words go first; real conditions stay (11-11 PM review).
    assert hx.cleaned_query('speech to text in korea') == 'speech to text korea'  # "to" keeps the direction
    assert hx.cleaned_query('how to convert pdf') == 'convert pdf'
    assert hx.cleaned_query('shipping tracking with history') == 'shipping tracking history'
    assert hx.cleaned_query('weather forecast') is None  # nothing to remove


def test_relaxed_forms_drop_conditions_then_a_leading_and_a_trailing_word():
    assert hx.relaxed_queries('book flights') == ['flights', 'book']
    assert hx.relaxed_queries('speech to text korea')[:2] == ['speech to text', 'text']
    assert 'to' not in ' '.join(hx.relaxed_queries('send email to customers')).split()
    assert hx.relaxed_queries('invoice ocr agents')[0] == 'invoice ocr'
    assert hx.relaxed_queries('weather') == []
    # A middle word alone is tried too (11-11: "lithuanian invoice parser" found nothing).
    assert hx.relaxed_queries('lithuanian invoice parser') == [
        'invoice parser', 'invoice']  # the language is a condition and goes first; "parser" alone is generic
    # Longer phrases keep their subject first: "bird", not "song" (11-11 public check).
    assert hx.relaxed_queries('bird song identification')[2:] == ['bird', 'song']
    # A generic word alone is never the task.
    assert 'advisory' not in hx.relaxed_queries('volcanic ash advisory')


def _fake(found, engines=None):
    asked = []

    def search(source, engine, query, *args, near=False):
        asked.append(query + (' ~near' if near else ''))
        if engines is not None:
            engines.append(engine)
        return {'items': [{'id': 1}] if query in found or near and 'near' in found else [], 'total': 0}
    return asked, search


def test_the_cleaned_query_is_searched_first_and_named(monkeypatch):
    asked, search = _fake({'speech to text korea'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, None, 'speech to text in korea', None, None, False, False, 45)
    assert result['items'] and result['relaxed_query'] == 'speech to text korea'
    assert asked == ['speech to text korea']  # one search, no extra time
    asked2, search2 = _fake({'speech to text'})
    monkeypatch.setattr(hx, '_scoped_explore', search2)
    found = hx.scoped_explore(None, None, 'speech to text in korea', None, None, False, False, 45)
    assert found['relaxed_query'] == 'speech to text' and asked2 == ['speech to text korea', 'speech to text']


def test_an_empty_search_tries_the_object_before_the_verb(monkeypatch):
    asked, search = _fake({'flights'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, None, 'book flights json output 981', None, None, False, False, 45)
    assert result['relaxed_query'] == 'flights' and asked == ['book flights', 'flights']
    asked.clear()
    plain = hx.scoped_explore(None, None, 'flights', None, None, False, False, 45)
    assert 'relaxed_query' not in plain and asked == ['flights']


def test_retries_read_the_text_index_only(monkeypatch):
    engines = []
    asked, search = _fake({'invoice'}, engines)
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, 'engine', 'lithuanian invoice parser', None, None, False, False, 45)
    assert result['relaxed_query'] == 'invoice'
    assert asked == ['lithuanian invoice parser', 'invoice parser', 'invoice']
    assert engines == ['engine', None, None]
    assert result['match'] == 'relaxed' and '"invoice"' in result['search_notice']


def test_nothing_matched_shows_the_closest_listings_and_says_so(monkeypatch):
    asked, search = _fake({'near'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    result = hx.scoped_explore(None, 'engine', 'volcanic ash advisory', None, None, False, False, 45)
    assert result['items'] and result['match'] == 'near'
    assert 'exactly' in result['search_notice'] and 'volcanic ash advisory' in result['search_notice']
    assert asked[-1] == 'volcanic ash advisory ~near' and 'advisory' not in asked
    # Without an embedding engine there is no meaning to be near; the empty answer stays honest.
    asked.clear()
    plain = hx.scoped_explore(None, None, 'volcanic ash advisory', None, None, False, False, 45)
    assert not plain['items'] and not any(q.endswith('~near') for q in asked)


def test_past_the_budget_the_closest_listings_come_without_more_retries(monkeypatch):
    asked, search = _fake({'near'})
    monkeypatch.setattr(hx, '_scoped_explore', search)
    clock = iter([0.0, 2.5, 2.5, 2.5, 2.5])
    monkeypatch.setattr(hx.time, 'monotonic', lambda: next(clock))
    result = hx.scoped_explore(None, 'engine', 'bird song identification', None, None, False, False, 45)
    assert result['match'] == 'near' and asked == ['bird song identification', 'bird song identification ~near']
