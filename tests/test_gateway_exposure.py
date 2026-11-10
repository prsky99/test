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
