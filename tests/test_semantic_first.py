"""Stage 2 (2026-11-04): the candidate whose chosen tool is closest in meaning leads."""
from agent_market.concierge.fast_chat import semantic_first


class Engine:
    embeddings_enabled = True

    def __init__(self, vectors=None, error=None):
        self.vectors, self.error, self.calls = vectors, error, []

    def embed_texts(self, texts, timeout_seconds=None):
        self.calls.append((texts, timeout_seconds))
        if self.error:
            raise self.error
        return self.vectors


def item(name, tool):
    return {'name': name, 'tools_schema': [{'name': tool, 'description': tool.replace('_', ' ')}]}


ITEMS = [item('Airline info', 'get_airline_info'), item('Town', 'town_status'), item('Flightstats', 'flight_status')]


def test_the_closest_tool_moves_first_and_the_rest_keep_their_order():
    engine = Engine([[1, 0], [0.2, 1], [0, 1], [0.9, 0.1]])  # task, then the three tools
    assert [i['name'] for i in semantic_first(engine, 'check flight status', ITEMS)] == ['Flightstats', 'Airline info', 'Town']
    assert engine.calls[0][1] <= 1.0  # bounded by the latency budget


def test_the_ranked_order_stands_when_embeddings_fail_or_are_off():
    assert semantic_first(Engine(None), 'task', ITEMS) == ITEMS
    assert semantic_first(Engine(error=TimeoutError()), 'task', ITEMS) == ITEMS
    off = Engine([[1, 0]] * 4); off.embeddings_enabled = False
    assert semantic_first(off, 'task', ITEMS) == ITEMS and off.calls == []
    assert semantic_first(None, 'task', ITEMS) == ITEMS


def test_the_first_stays_when_it_is_already_closest():
    engine = Engine([[1, 0], [1, 0], [0, 1], [0.5, 0.5]])
    assert semantic_first(engine, 'task', ITEMS) == ITEMS
