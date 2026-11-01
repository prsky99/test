"""Explore results are shared through Redis across frontend slots; Redis only ever adds a cache."""
from agent_market.concierge import front as front_module


class FakeHub:
    def __init__(self, available=True):
        self.available, self.values, self.sets = available, {}, []

    def is_available(self):
        return self.available

    def get_json(self, key):
        return self.values.get(key)

    def set_json(self, key, value, ttl_seconds=60):
        self.sets.append((key, ttl_seconds)); self.values[key] = value; return True


def install(monkeypatch, hub):
    monkeypatch.setattr(front_module.RedisHub, 'get_instance', classmethod(lambda cls: hub))


KEY = (12345, 'weather forecast', None, None, False, False, 46)


def test_a_computed_result_is_shared_and_another_slot_reuses_it(monkeypatch):
    hub = FakeHub(); install(monkeypatch, hub)
    calls = []
    value = {'items': [{'id': 1}], 'complete': False}
    hit = []
    assert front_module._shared_explore(object(), KEY, lambda: calls.append(1) or value, hit)() == value
    assert calls == [1] and hit == [] and hub.sets[0][1] == front_module.SHARED_EXPLORE_TTL
    # Another process: a different store id, the same search.
    other = (99999,) + KEY[1:]
    hit = []
    assert front_module._shared_explore(object(), other, lambda: calls.append(2), hit)() == value
    assert calls == [1] and hit  # served from Redis; the caller revalidates every listing


def test_a_complete_result_answers_a_wider_window_on_another_slot(monkeypatch):
    hub = FakeHub(); install(monkeypatch, hub)
    front_module._shared_explore(object(), KEY, lambda: {'items': [{'id': 1}], 'complete': True}, [])()
    wider = (7,) + KEY[1:-1] + (91,)
    hit = []
    assert front_module._shared_explore(object(), wider, lambda: None, hit)()['complete'] is True and hit


def test_redis_unavailable_or_unencodable_values_only_skip_the_shared_layer(monkeypatch):
    install(monkeypatch, FakeHub(available=False))
    assert front_module._shared_explore(object(), KEY, lambda: {'items': []}, [])() == {'items': []}
    hub = FakeHub(); install(monkeypatch, hub)
    odd = {'items': [{'id': 1, 'when': object()}]}
    assert front_module._shared_explore(object(), KEY, lambda: odd, [])() is odd and hub.sets == []
    big = {'items': [{'id': 1, 'text': 'x' * (front_module.SHARED_EXPLORE_MAX_BYTES + 1)}]}
    assert front_module._shared_explore(object(), KEY, lambda: big, [])() is big and hub.sets == []


def test_a_malformed_shared_value_is_ignored(monkeypatch):
    hub = FakeHub(); install(monkeypatch, hub)
    exact, _ = front_module._shared_explore_keys(object(), KEY)
    hub.values[exact] = ['not', 'a', 'result']
    assert front_module._shared_explore(object(), KEY, lambda: {'items': [{'id': 2}]}, [])() == {'items': [{'id': 2}]}


def test_deployed_postgres_services_share_one_prefix_and_tests_do_not(monkeypatch, tmp_path):
    class PgStore:
        backend = 'postgresql'
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    a, _ = front_module._shared_explore_keys(PgStore(), KEY)
    b, _ = front_module._shared_explore_keys(PgStore(), (777,) + KEY[1:])
    assert a == b and a.startswith('a2a:shared:')
    monkeypatch.delenv('AGENTCON_PROJECT_ROOT')
    c, _ = front_module._shared_explore_keys(PgStore(), KEY)
    assert not c.startswith('a2a:shared:')
