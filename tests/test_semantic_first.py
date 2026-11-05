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


def test_a_single_candidate_needs_no_embedding_and_rank_reports_closeness():
    from agent_market.concierge.fast_chat import semantic_rank
    engine = Engine([[1, 0], [0.6, 0.8]])
    assert semantic_first(engine, 'task', ITEMS[:1]) == ITEMS[:1] and engine.calls == []
    ranked, closeness = semantic_rank(engine, 'task', ITEMS[:1])
    assert ranked == ITEMS[:1] and abs(closeness - 0.6) < 1e-9
    assert semantic_rank(Engine(None), 'task', ITEMS) == (ITEMS, None)


class Http:
    def __init__(self, vectors=None, status=200, error=None):
        self.vectors, self.status, self.error, self.calls = vectors, status, error, []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        if self.error:
            raise self.error
        vectors, status = self.vectors, self.status
        class Response:
            status_code = status
            def json(self):
                return {'embeddings': vectors}
        return Response()


def test_closeness_uses_the_stronger_model_and_is_optional():
    from agent_market.concierge.fast_chat import strong_closeness, STRONG_BUDGET, STRONG_MODEL
    engine = Engine(); engine.ollama_url = 'http://127.0.0.1:11434'; engine.http = Http([[1, 0], [0.8, 0.6]])
    assert abs(strong_closeness(engine, 'task', ITEMS[0]) - 0.8) < 1e-9
    url, body, timeout = engine.http.calls[0]
    assert url.endswith('/api/embed') and body['model'] == STRONG_MODEL and timeout == STRONG_BUDGET
    for http in (Http(error=TimeoutError()), Http(status=404), Http([[1, 0]])):
        engine.http = http
        assert strong_closeness(engine, 'task', ITEMS[0]) is None  # unmeasured: Chat answers as before
