"""MCP servers whose gateway tools/list is empty are left out while another choice remains (2026-11-10)."""
import json
from copy import copy

from agent_market.concierge.gateway_exposure import ExposedFirstRecommender

SAFE = {'name': 'get_weather', 'description': 'Read the forecast for a city', 'required': ['city'],
        'params': {'city': {'type': 'string'}}, 'annotations': {'readOnlyHint': True}}
UNSAFE = {'name': 'delete_file', 'description': 'Delete a stored file', 'required': ['path'],
          'params': {'path': {'type': 'string'}}, 'annotations': {}}


class Store:
    def __init__(self, rows):
        self.rows, self.reads = rows, 0

    def resource(self, rid):
        self.reads += 1
        return self.rows.get(rid)


class Recommender:
    def __init__(self, items):
        self.items, self.store, self.asked = items, None, []
        self.rag_engine = 'engine'

    def search(self, task, kind=None, auth_pref=None, limit=1, offset=0, exclude=None, hint=None, category=None):
        self.asked.append(limit)
        return self.items[offset:offset + limit]


def _row(rid, tools):
    return {'id': rid, 'kind': 'mcp', 'active': 1, 'usage_tools': json.dumps(tools)}


def test_an_empty_gateway_server_moves_last_and_is_replaced():
    store = Store({1: _row(1, [UNSAFE]), 2: _row(2, [SAFE]), 3: _row(3, [])})
    items = [{'id': 1, 'kind': 'mcp'}, {'id': 2, 'kind': 'mcp'}, {'id': 4, 'kind': 'a2a'}, {'id': 3, 'kind': 'mcp'}]
    rec = ExposedFirstRecommender(Recommender(items), store)
    assert [i['id'] for i in rec.search('pdf to text', limit=1)] == [2]
    assert [i['id'] for i in rec.search('pdf to text', limit=4)] == [2, 4]  # left out while others remain
    only_hidden = ExposedFirstRecommender(Recommender([{'id': 1, 'kind': 'mcp'}]), store)
    assert [i['id'] for i in only_hidden.search('x', limit=1)] == [1]  # nothing callable: keep the answer
    assert rec._recommender.asked == [4, 7]  # looked EXTRA further
    reads = store.reads
    rec.search('pdf to text', limit=1)
    assert store.reads == reads  # cached


def test_copy_binds_a_request_store_and_forwards_attributes():
    first, second = Store({2: _row(2, [SAFE])}), Store({2: _row(2, [])})
    rec = ExposedFirstRecommender(Recommender([{'id': 2, 'kind': 'mcp'}, {'id': 5, 'kind': 'a2a'}]), first)
    scoped = copy(rec)
    scoped.store = second
    assert scoped._recommender is not rec._recommender and scoped._recommender.store is second
    assert rec.store is first and rec.rag_engine == 'engine'
    assert [i['id'] for i in scoped.search('x', limit=1)] == [5]
    assert [i['id'] for i in rec.search('x', limit=1)] == [2]


def test_a_tool_that_needs_a_paid_plan_or_an_account_follows_free_choices():
    """11-11 PM: extract_invoice_data ("Requires Team tier or above") was first for a PDF invoice task."""
    from agent_market.concierge import gateway_exposure as ge
    paid = {'id': 1, 'kind': 'mcp', 'tools': ['extract_invoice_data'], 'description': 'PDF tools',
            'tools_schema': [{'name': 'extract_invoice_data', 'description': 'Extract an invoice. Requires Team tier or above.'}]}
    keyed = {'id': 2, 'kind': 'mcp', 'tools': ['lookup'], 'description': 'Recalls. Requires an API key.'}
    free = {'id': 3, 'kind': 'mcp', 'tools': ['invoice_parse'], 'description': 'Invoice fields from a PDF'}
    other_paid_tool = {'id': 4, 'kind': 'mcp', 'tools': ['free_tool'], 'description': 'Tools',
                       'tools_schema': [{'name': 'free_tool', 'description': 'Free'}, {'name': 'pro', 'description': 'Requires a pro plan'}]}

    class Inner:
        store = None

        def search(self, task, *args):
            return [dict(paid), dict(keyed), dict(free), dict(other_paid_tool)]
    wrapper = ge.ExposedFirstRecommender(Inner(), None)
    wrapper.callable = lambda item: True
    wrapper.tool_texts = lambda item: None
    ranked = wrapper.search('invoice', limit=4)
    # Two free choices are fewer than the three a visitor sees: the restricted ones follow, marked.
    assert [item['id'] for item in ranked] == [3, 4, 1, 2]  # only the selected tool's own text counts
    assert ranked[2]['access_note'] == ge.PAID_NOTE and ranked[3]['access_note'] == ge.ACCOUNT_NOTE
    assert 'access_note' not in ranked[0]
    # Free choices that fill what is shown leave the restricted ones out (Chat re-ranks by meaning).
    assert [item['id'] for item in wrapper.search('invoice', limit=2)] == [3, 4]
    more = dict(free, id=5)
    Inner.search = lambda self, task, *a: [dict(paid), dict(free), dict(other_paid_tool), dict(more), dict(keyed)]
    assert [item['id'] for item in wrapper.search('invoice', limit=10)] == [3, 4, 5]
    # With no free choice the restricted ones stay, marked.
    Inner.search = lambda self, task, *a: [dict(paid)]
    assert wrapper.search('invoice', limit=2)[0]['access_note'] == ge.PAID_NOTE


def test_paid_wording_is_not_found_in_ordinary_text():
    from agent_market.concierge.gateway_exposure import access_note
    for text in ('Works for teams of any size', 'Team collaboration notes', 'Pro tips for pdf conversion',
                 'No API key needed', 'Free tier available'):
        assert access_note({'kind': 'mcp', 'description': text}) is None, text


def test_the_full_tool_text_and_short_paid_wording_count():
    from agent_market.concierge import gateway_exposure as ge
    item = {'kind': 'mcp', 'tools': ['extract_invoice'], 'description': 'German e-invoicing: generate and extract.',
            'tools_schema': [{'name': 'extract_invoice', 'description': 'Extract structured JSON from an e-invoice…'}]}
    assert ge.access_note(item) is None  # the shortened text hides it
    assert ge.access_note(item, {'extract_invoice': 'Extract structured JSON. 5 credits, requires an API key.'}) == ge.PAID_NOTE
    assert ge.access_note(dict(item, description='German e-invoicing. Paid.')) == ge.PAID_NOTE
    assert ge.access_note(dict(item, description='Paid plans are not needed for this')) is None


def test_recent_gateway_outcomes_and_direction_order_the_shortlist(monkeypatch):
    """11-11: failing tools (p10), keys asked by the agent (a07) and reverse tools (a05) follow the rest."""
    from agent_market.concierge import gateway_exposure as ge, task_outcomes
    items = [{'id': 1, 'kind': 'mcp', 'tools': ['translate'], 'description': 'Media toolkit'},
             {'id': 2, 'kind': 'a2a', 'tools': ['quote'], 'description': 'Stock quotes'},
             {'id': 3, 'kind': 'mcp', 'tools': ['reverse_geocode'], 'description': 'Geocoding'},
             {'id': 4, 'kind': 'mcp', 'tools': ['translate_text'], 'description': 'Translator'},
             {'id': 5, 'kind': 'mcp', 'tools': ['geocode'], 'description': 'Geocoding'}]
    counts = {1: {'failed': 2, 'tools': {'translate': {'failed': 2}}}, 2: {'needs_key': 1},
              4: {'succeeded': 3, 'tools': {'translate_text': {'succeeded': 3}}}}
    monkeypatch.setattr(task_outcomes, 'recent', lambda ids: {i: counts[i] for i in ids if i in counts})

    class Inner:
        store = None

        def search(self, task, *args):
            return [dict(item) for item in items]
    wrapper = ge.ExposedFirstRecommender(Inner(), None)
    wrapper.callable = lambda item: True
    wrapper.tool_texts = lambda item: None
    ranked = wrapper.search('Geocode a street address to latitude and longitude', limit=10)
    assert [item['id'] for item in ranked] == [4, 5, 1, 3, 2]  # a key the agent asked for goes last
    assert ranked[4]['access_note'] == ge.ACCOUNT_NOTE and ranked[3]['direction_mismatch'] is True
    # Three good choices fill what is shown: the failing, keyed and reverse ones leave the list.
    items.append({'id': 6, 'kind': 'mcp', 'tools': ['geo'], 'description': 'Geo'})
    assert [item['id'] for item in wrapper.search('Geocode a street address to latitude and longitude', limit=10)] == [4, 5, 6]


def test_answers_are_classified_from_their_own_text():
    from agent_market.concierge.task_outcomes import classify, standing
    assert classify({'content': [{'type': 'text', 'text': '{"error": "translation failed"}'}], 'isError': False}) == 'failed'
    assert classify({'parts': [{'kind': 'text', 'text': 'Provide an API key via Authorization: Bearer <key> for full access.'}]}) == 'needs_key'
    assert classify({'content': [{'type': 'text', 'text': 'Seoul AQI 42, PM2.5 9'}]}) == 'succeeded'
    assert classify({'isError': True, 'content': []}) == 'failed'
    assert standing({'failed': 1, 'tools': {'other': {'failed': 1}}}, 'mine') == 0  # another tool failed
    assert standing({'succeeded': 1, 'failed': 1}) == 1 and standing({'failed': 2}) == -1
