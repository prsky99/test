"""A registry host that is most of a kind and rarely passes a trial resolves at most THROTTLE_HOURLY
registrations an hour; other hosts keep their pace (11-12 PM decision (다): one host sent ~1,900 A2A
listings an hour, 97% of active A2A, 3.8% trial_ok)."""
from agent_market.collector import registries
from agent_market.collector.registries import Erc8004Crawler, throttled_hosts


def test_the_rule_needs_both_a_large_share_and_a_low_trial_rate():
    shares = {'kinds': {'a2a': 1000, 'mcp': 100},
              'hosts': [('big.example', 'a2a', 970, 30),      # 97%, 3% trial -> throttled
                        ('good.example', 'a2a', 300, 200),    # 30% but 67% trial -> not
                        ('mcp.example', 'mcp', 15, 0)]}       # 15% of mcp -> not
    assert throttled_hosts(shares) == {'big.example'}
    assert throttled_hosts(shares, share=0.10) == {'big.example', 'mcp.example'}
    assert throttled_hosts({'kinds': {}, 'hosts': []}) == set()


class Store:
    def __init__(self, shares):
        self.shares, self.picks = shares, []

    def host_kind_shares(self, min_rows):
        assert min_rows == registries.THROTTLE_MIN_ROWS
        return self.shares

    def query(self, sql, params=()):
        if 'GROUP BY host' in sql:
            return [{'host': 'big.example'}, {'host': 'small.example'}]
        host, now, take = params
        self.picks.append((host, take))
        return [{'host': host, 'next_at': None, 'chain': 1, 'agent_id': i} for i in range(take)]


def _crawler(store):
    crawler = object.__new__(Erc8004Crawler)
    crawler.store, crawler.per_host = store, 5
    return crawler


def test_a_throttled_host_stops_at_the_hourly_cap_and_others_keep_their_pace(monkeypatch):
    monkeypatch.setattr(registries, 'THROTTLE_HOURLY', 12)
    store = Store({'kinds': {'a2a': 100}, 'hosts': [('big.example', 'a2a', 97, 3)]})
    crawler = _crawler(store)
    now = 10_000.0
    for _ in range(4):
        crawler._pending_rows(now, 200)
    big = sum(take for host, take in store.picks if host == 'big.example')
    small = sum(take for host, take in store.picks if host == 'small.example')
    assert big == 12 and small == 20   # 5 + 5 + 2, then nothing; the other host 5 every round
    crawler._pending_rows(now + 3601, 200)  # an hour later there is room again
    assert store.picks[-2] == ('big.example', 5)


class NoRuleStore(Store):
    host_kind_shares = None  # a store without the method (older SQLite fixtures)


def test_no_rule_answer_means_no_throttle():
    store = NoRuleStore({})
    crawler = _crawler(store)
    crawler._pending_rows(1.0, 200)
    assert ('big.example', 5) in store.picks


def test_sqlite_store_counts_active_rows_per_host_and_kind():
    from agent_market.gateway.store import Store as Catalog
    store = Catalog(':memory:')
    for i in range(4):
        store.upsert_resource({'key': f'k{i}', 'source': 'fixture', 'kind': 'a2a', 'name': f'A{i}',
                               'url': f'https://big.example/a{i}', 'description': 'x', 'category': 'research',
                               'networks': [], 'details': {}}, now=1)
    store.upsert_resource({'key': 'm', 'source': 'fixture', 'kind': 'mcp', 'name': 'M', 'url': 'https://other.example/mcp',
                           'description': 'x', 'category': 'research', 'networks': [], 'details': {}}, now=1)
    shares = store.host_kind_shares(2)
    assert shares['kinds'] == {'a2a': 4, 'mcp': 1}
    assert shares['hosts'] == [('big.example', 'a2a', 4, 0)]
