"""Explore "Recorded reports" from the in-memory snapshot (response-time policy 2026-11-01)."""
import time

from agent_market.concierge import report_snapshot as rs

DOCS = [
    ('x402tap.com/api/weather', 'Live current weather conditions for any city, sourced from Open-Meteo'),
    ('Weather MCP', 'Real-time weather forecast. See acme/weather-mcp and https://api.x.io/v1/agent-weather/current'),
    ('Café Translator', 'Translate Japanese 日本語で翻訳 and Spanish text; nip-19 keys, v1.2 PDF_tools'),
    ('Flight search', 'Search flights, compare fares. Flight status flight flight.'),
    ('Unrelated', 'Stock prices and market data.'),
]
QUERIES = [['weather'], ['flight', 'search'], ['translate', 'japanese'], ['weather-mcp'], ['pdf', 'convert'], ['stock', 'price']]


def test_tokens_follow_the_default_parser_rules():
    assert rs.lexemes('x402tap.com/api/weather') == ['x402tap.com/api/weather', 'x402tap.com', '/api/weather']
    assert rs.lexemes('real-time data') == ['real-time', 'real', 'time', 'data']
    assert rs.lexemes('acme/weather-mcp') == ['acme/weather-mcp']
    assert rs.lexemes('Café PDF_tools v1.2') == ['cafe', 'pdf', 'tools', 'v1.2']
    assert rs.lexemes('で') == ['で']  # kana keep their voicing mark


def test_matching_and_rank_equal_postgresql():
    from pathlib import Path
    import pytest
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.postgres_lexical import MATCH_PREFIX
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE EXTENSION unaccent')
            conn.execute('CREATE SCHEMA agentcon_search')
            from agent_market.postgres_lexical import BODY
            conn.execute('CREATE FUNCTION agentcon_search.lexical_document(text,text) RETURNS tsvector LANGUAGE sql IMMUTABLE AS $$' + BODY + '$$')
            conn.execute('CREATE TABLE resources_fts(rowid bigint primary key,name text,description text)')
            for rowid, (name, description) in enumerate(DOCS, 1):
                conn.execute('INSERT INTO resources_fts VALUES(%s,%s,%s)', (rowid, name, description))
            for terms in QUERIES:
                match = ' OR '.join('"' + term + '"' for term in terms)
                expected = {row[0]: row[1] for row in conn.execute(
                    MATCH_PREFIX + 'SELECT id,rank FROM matches', (match,)).fetchall()}
                operands = rs.query(terms)
                found = {}
                for rowid, (name, description) in enumerate(DOCS, 1):
                    vec = rs.vector(name, description)
                    value = rs.rank(vec, sum(len(p) for p in vec.values()), operands)
                    if value is not None:
                        found[rowid] = value
                assert set(found) == set(expected), terms
                for rowid, value in expected.items():
                    assert abs(found[rowid] - value) < 1e-5, (terms, rowid)


def entry(rid, kind='mcp', name='Weather', description='weather forecast', **flags):
    row = {'id': rid, 'kind': kind, 'name': name, 'url': f'https://h{rid}.example/mcp', 'category': flags.get('category'),
           'eval_score': flags.get('eval_score', 50), 'trial_ok': 0, 'report_count': 1,
           'catalog_status': 'live', 'auth_required': 0}
    vec = rs.vector(name, description)
    return {'row': row, 'card': {'id': rid, 'name': name}, 'vector': vec, 'length': sum(len(p) for p in vec.values()),
            'verified': flags.get('verified', False), 'no_auth': flags.get('no_auth', True),
            'adult': flags.get('adult', False), 'name': name}


def test_snapshot_filters_ranks_and_keeps_the_adult_rule():
    snapshot = rs.Snapshot([entry(1), entry(2, name='Forecast', verified=True), entry(3, kind='a2a'),
                            entry(4, name='Stocks', description='stock prices', no_auth=False),
                            entry(5, name='Adult Weather', adult=True)], time.time())
    result = snapshot.search(None, 'weather', ['weather'], 'mcp', None, False, False, 45)
    assert [item['id'] for item in result['items']] == [1, 2]  # a name match ranks first; adult hidden
    assert result['total'] == 2 and result['matched_report_count'] == 2
    assert [item['id'] for item in snapshot.search(None, '', [], 'mcp', None, True, False, 45)['items']] == [2]
    assert [item['id'] for item in snapshot.search(None, '', [], 'mcp', None, False, True, 45)['items']] == [1, 2]
    assert [item['id'] for item in snapshot.search(None, 'adult weather', ['adult', 'weather'], 'mcp', None, False, False, 45)['items']][0] == 5


def test_front_uses_a_fresh_snapshot_and_falls_back_without_one(monkeypatch):
    from agent_market.concierge import front
    calls = []

    class Fake:
        def search(self, *args):
            calls.append(args[1:])
            return {'items': [], 'total': 0, 'report_scope': 'history'}
    monkeypatch.setattr(rs, 'current', lambda store: Fake())
    monkeypatch.setattr(front, 'revalidated_page', lambda store, result: {**result, 'revalidated': True})
    result = front.get_front_explore(object(), 'weather', 'mcp', None, False, False, 46, has_report=True)
    assert result['revalidated'] and calls and calls[0][0] == 'weather'
    monkeypatch.undo()
    rs._snapshots.clear()
    assert rs.current(object()) is None
    store = object()
    rs._snapshots[id(store)] = rs.Snapshot([], time.time() - 3 * rs.REFRESH_SECONDS)
    assert rs.current(store) is None  # a snapshot older than two refresh periods is not used
    rs._snapshots.clear()



def test_rebuild_releases_the_front_store_lock_between_short_chunks(monkeypatch):
    """Visitor requests share the front store lock; the rebuild must not hold it for long stretches."""
    import contextlib
    import threading
    from agent_market.concierge import front, content_policy

    class Store:
        _lock = threading.RLock()

        def tx(self, readonly=False):
            assert readonly
            return contextlib.nullcontext()
    store, held_while_pausing, chunk_sizes = Store(), [], []
    rows = [{'id': i, 'kind': 'mcp', 'name': f'n{i}', 'description': 'd'} for i in range(60)]
    monkeypatch.setattr(rs, 'KINDS', ('mcp',))
    monkeypatch.setattr(front, '_report_candidate_sql', lambda *a: ('', []))
    monkeypatch.setattr(front, '_report_candidates', lambda *a: (list(rows), len(rows)))
    monkeypatch.setattr(rs, '_all_candidates', lambda *a: (list(rows), len(rows)))  # the snapshot's own window
    monkeypatch.setattr(front, '_report_prefetch', lambda s, ids: chunk_sizes.append(len(ids)) or ({}, {}))
    monkeypatch.setattr(front, '_report_listing', lambda s, row, current, reports: (row, {'name': row['name']}))
    monkeypatch.setattr(front, '_card_data', lambda row, s, create_connections=True: {})
    monkeypatch.setattr(rs, '_indexed_text', lambda s, ids: {})
    monkeypatch.setattr(content_policy, 'adult_listing', lambda resource: False)

    def pause(seconds):
        # A lock another thread can take is free; the rebuild thread itself must not be holding it.
        got = []
        t = threading.Thread(target=lambda: got.append(store._lock.acquire(timeout=0.5)) or store._lock.release())
        t.start(); t.join()
        held_while_pausing.append(not got[0])
    monkeypatch.setattr(rs.time, 'sleep', pause)
    snapshot = rs.build(store)
    assert len(snapshot.entries) == 60
    assert max(chunk_sizes) <= rs.CHUNK <= 50
    assert held_while_pausing == [False] * (len(chunk_sizes) - 1)  # a pause between every pair of chunks


def test_only_the_serving_slot_keeps_refreshing(monkeypatch):
    """Both web slots rebuilt every ten minutes; the standby slot now builds once, at start."""
    builds, clock, waits = [], [1000.0], []
    store = object()

    class Stop:
        def is_set(self):
            return len(waits) >= 6

        def wait(self, seconds):
            waits.append(seconds)
            clock[0] += 400

    def fake_refresh(store, stop):
        builds.append(clock[0])
        rs._snapshots[id(store)] = rs.Snapshot([], clock[0])
    monkeypatch.setattr(rs, 'refresh', fake_refresh)
    monkeypatch.setattr(rs.time, 'time', lambda: clock[0])
    serving = [False]
    rs._snapshots.clear()
    rs.keep_fresh(store, Stop(), interval=600, serving=lambda: serving[0])
    assert builds == [1000.0]  # standby: the start-up build only
    waits.clear(); builds.clear(); serving[0] = True
    rs.keep_fresh(store, Stop(), interval=600, serving=lambda: serving[0])
    assert len(builds) >= 3  # serving: start-up build, then whenever the snapshot is ten minutes old
    waits.clear(); builds.clear()
    rs.keep_fresh(store, Stop(), interval=600, serving=lambda: (_ for _ in ()).throw(OSError('state')))
    assert len(builds) >= 3  # an unreadable state keeps refreshing
    rs._snapshots.clear()


def test_serving_slot_reads_the_deployment_state(tmp_path, monkeypatch):
    import json
    from agent_market.service_host import serving_slot
    monkeypatch.delenv('AGENTCON_SERVICE_STATE_DIR', raising=False)
    assert serving_slot('frontend', 'r1')  # no state: every process serves
    (tmp_path / 'state.json').write_text(json.dumps({'services': {'frontend': {'active': 'a', 'slots': {'a': 'r2', 'b': 'r1'}}}}))
    monkeypatch.setenv('AGENTCON_SERVICE_STATE_DIR', str(tmp_path))
    assert serving_slot('frontend', 'r2') and not serving_slot('frontend', 'r1')
    assert serving_slot('jobs', 'anything')  # a role without slots


def test_explore_keep_warm_skips_rounds_in_a_standby_slot(monkeypatch):
    from agent_market import service_host
    from agent_market.concierge import front as front_module
    rounds = []
    monkeypatch.setattr(front_module, 'warm_explore', lambda front, stop=None, pause=0.0: rounds.append(front))

    class Stop:
        def __init__(self, waits):
            self.left = waits
        def is_set(self):
            return self.left <= 0
        def wait(self, seconds):
            self.left -= 1
            return self.is_set()

    service_host.keep_explore_warm('front', Stop(3), pause=8.0, serving=lambda: False)
    assert rounds == []  # standby: no Explore searches, so no database load
    service_host.keep_explore_warm('front', Stop(3), pause=8.0, serving=lambda: True)
    assert len(rounds) == 3
    rounds.clear()
    service_host.keep_explore_warm('front', Stop(2), pause=8.0, serving=lambda: (_ for _ in ()).throw(OSError('state')))
    assert len(rounds) == 2  # an unreadable state keeps warming
    rounds.clear()
    service_host.keep_explore_warm('front', Stop(2), pause=8.0)
    assert len(rounds) == 2  # no slot check (tests, a direct start): always warm


def test_explore_keep_warm_stops_mid_round_when_the_slot_turns_standby(monkeypatch):
    from agent_market import service_host
    from agent_market.concierge import front as front_module
    serving = [True]
    searched = []

    def fake_warm(front, stop=None, pause=0.0):
        for query in range(24):
            if stop.is_set():
                break
            searched.append(query)
            if query == 2:
                serving[0] = False  # a deploy makes this slot the standby mid-round
            stop.wait(pause)

    monkeypatch.setattr(front_module, 'warm_explore', fake_warm)

    class Stop:
        def __init__(self, waits):
            self.left = waits
        def is_set(self):
            return self.left <= 0
        def wait(self, seconds):
            self.left -= 1
            return self.is_set()

    service_host.keep_explore_warm('front', Stop(30), pause=8.0, serving=lambda: serving[0])
    assert searched == [0, 1, 2]  # the rest of the round is skipped once standby
