"""PM 11-17 12:2x: user_slo "customer support bulk" took 6.68 s and 5.54 s (server 5.6 and 4.5 s).

The first search found nothing because 'bulk' is a trait, not a capability; the request then spent 1.0 s on the
neighbor words and 1.4 s on their search before the search without the trait could run. The trait search now comes
first, and the neighbor words stop counting once enough are picked.
"""
# ruff: noqa: F401,F811 -- reuse the isolated catalog fixture
import json

import agent_market.concierge.fast_chat as fast_chat
from tests.test_fast_single_recommendation import catalog, ask


def _support(add, now, name, tool, description, seconds):
    spec = {'name': tool, 'description': description,
            'inputSchema': {'type': 'object', 'properties': {'ticket_id': {'type': 'string'}}, 'required': ['ticket_id']},
            'annotations': {'readOnlyHint': True}}
    return add(name, report_at=now - seconds, description=f'{name}: {description}', category='communication',
               usage_guide=json.dumps({'tools': [spec]}))


def test_a_trait_word_is_dropped_before_the_neighbor_words(catalog, monkeypatch):
    _, front, client, add, now = catalog
    desk = _support(add, now, 'Help Desk Reader', 'get_support_ticket', 'Read a customer support ticket and its replies', 60)
    search = front.concierge.rec.search
    asked = []

    def strict(task, *args, **kwargs):          # the production search requires 'bulk' as a capability word
        asked.append(str(task))
        return [] if 'bulk' in str(task) else search(task, *args, **kwargs)
    front.concierge.rec.search = strict
    neighbors = []
    monkeypatch.setattr(fast_chat, 'neighbor_focus', lambda *a, **k: neighbors.append(a) or None)
    recs = ask(client, 'customer support bulk')['data']['recommendations']
    assert recs and recs[0]['id'] == desk and recs[0]['unverified'] == ['bulk']
    assert 'not confirmed (unverified): bulk' in recs[0]['reason']['text']
    assert neighbors == []                      # the trait search answered; the neighbor words never ran
    assert asked[1].startswith('customer support') and 'bulk' not in asked[1]   # the second search is the trait one


def test_a_request_without_a_trait_keeps_its_fallbacks(catalog, monkeypatch):
    _, front, client, _, _ = catalog
    front.concierge.rec.search = lambda *a, **k: []
    neighbors = []
    monkeypatch.setattr(fast_chat, 'neighbor_focus', lambda *a, **k: neighbors.append(a) or None)
    ask(client, 'emotion analysis of reviews')
    assert neighbors                            # no trait word: the neighbor fallback still runs


def test_neighbor_words_stop_counting_once_enough_are_picked(monkeypatch):
    rows = [{'_rank_text': 'sentiment polarity emotion opinion mood tone review'} for _ in range(30)]
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    monkeypatch.setattr('agent_market.concierge.discovery.candidates', lambda *a, **k: rows)
    counted = []
    monkeypatch.setattr(fast_chat, 'catalog_share', lambda store, word: counted.append(word) or 0.0)
    shared = fast_chat.neighbor_focus(object(), object(), 'feelings in texts')
    assert shared and len(shared.split()) == fast_chat.NEIGHBOR_WORDS
    assert len(counted) == fast_chat.NEIGHBOR_WORDS           # before: every shared word (up to 12) was counted
