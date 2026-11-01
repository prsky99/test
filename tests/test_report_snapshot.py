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
