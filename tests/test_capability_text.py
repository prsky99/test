"""Stored capability text: exact-source reuse for the first Explore word check (2026-10-28)."""
import json

from agent_market import postgres_capability_text as pct
from agent_market.concierge.selection import text_may_match


def listing(**changes):
    tools = [{'name': 'get_weather_forecast', 'description': 'Hourly weather forecast for a city.',
              'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string',
                              'description': 'Translate this to any language first'}}}}]
    return {'id': 7, 'kind': 'mcp', 'name': 'Sky Data', 'description': 'Meteorology service.',
            'category': 'travel_maps_weather', 'cap_tool_names': 'get_weather_forecast',
            'usage_tools': json.dumps(tools), 'usage_full_tools': None, 'usage_full_hash': None,
            'usage_guide': None, 'details': None, **changes}


def test_text_holds_names_and_descriptions_but_not_schemas():
    text = pct.build(listing())
    assert 'sky data' in text and 'get weather forecast' in text and 'hourly weather forecast' in text
    assert 'translate this' not in text  # parameter descriptions never make a listing a translator


def test_stored_text_is_a_stricter_first_check_with_the_same_admissions():
    row = listing()
    stored = {**row, '_capability_text': pct.build(row)}
    assert text_may_match(['weather', 'forecast'], row) and text_may_match(['weather', 'forecast'], stored)
    # Only the schema mentions translation: the full text passes the cheap check, the stored text does not.
    assert text_may_match(['translate'], row) and not text_may_match(['translate'], stored)


def test_source_hash_changes_with_any_read_field():
    base = pct.source_hash(listing())
    for field, value in (('name', 'Other'), ('description', 'x'), ('usage_tools', '[]'), ('usage_guide', '{}'),
                         ('details', '{"a":1}'), ('kind', 'a2a'), ('usage_full_hash', 'f' * 64)):
        assert pct.source_hash(listing(**{field: value})) != base
    assert pct.source_hash(listing()) == base


class FakeStore:
    backend = 'postgresql'

    def __init__(self, facts):
        self.facts = facts

    def _execute(self, sql, params=(), **_):
        class Result:
            def __init__(self, rows): self.rows = rows
            def fetchone(self): return self.rows[0] if self.rows else None
            def fetchall(self): return self.rows
        if 'to_regclass' in sql:
            return Result([('agentcon_search.capability_text_configuration',)])
        if 'capability_text_configuration' in sql:
            return Result([(pct.PROFILE,)])
        return Result([(rid, *self.facts[rid]) for rid in json.loads(params[0]) if rid in self.facts])


def test_only_exactly_matching_stored_text_is_attached(monkeypatch):
    monkeypatch.setitem(pct._enabled, 'at', -1e9)
    row, changed, old = listing(id=1), listing(id=2), listing(id=3)
    facts = {1: (pct.source_hash(row), pct.VERSION, 'current text', '{"get_weather_forecast": true}'),
             2: (pct.source_hash(listing(id=2, name='Before')), pct.VERSION, 'stale text', None),
             3: (pct.source_hash(old), pct.VERSION - 1, 'old derivation', None)}
    rows = pct.attach(FakeStore(facts), [dict(row), dict(changed), dict(old)])
    assert rows[0]['_capability_text'] == 'current text'
    assert rows[0]['_tool_support'] == {'get_weather_forecast': True}
    assert '_capability_text' not in rows[1] and '_capability_text' not in rows[2]


def test_other_backends_are_unchanged():
    class Lite:
        backend = 'sqlite'
    rows = [listing()]
    assert pct.attach(Lite(), rows) == [listing()]


def test_actual_postgres_install_refresh_attach_and_cleanup():
    from pathlib import Path
    import pytest
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
            ids = []
            for n in range(3):
                ids.append(store.upsert_resource({'key': f'fixture:cap{n}', 'source': 'fixture', 'kind': 'mcp',
                    'name': f'Forecast {n}', 'url': f'https://cap{n}.example/mcp', 'description': 'Weather forecast API',
                    'category': 'travel_maps_weather', 'networks': [], 'details': {}}, now=10))
            with store.tx():
                store._execute("UPDATE resources SET active=1,health_status='healthy'")
            assert not pct.available(store)
            pct.install(store)
            assert pct.available(store)
            refresher = pct.Refresher(store, batch=2, rounds=5)
            assert refresher.due() and refresher.run() == {'checked': 3, 'written': 3}
            assert not refresher.due()  # a full pass rests until the interval
            pct._enabled['at'] = -1e9
            from agent_market.application_store_resource_batches import resources
            with store.tx(readonly=True):
                rows = [dict(row) for row in resources(store, ids, 'active=1', (), allow_partial=True, hydrate_contracts=True)]
                attached = pct.attach(store, rows)
            assert all('forecast' in row['_capability_text'] for row in attached)
            # A changed listing is rewritten; a listing that leaves the searchable set is removed.
            with store.tx():
                store._execute("UPDATE resources SET description='Tide tables' WHERE id=%s", (ids[0],))
                store._execute("UPDATE resources SET active=0 WHERE id=%s", (ids[2],))
            refresher.rest_until = 0
            seen, execute = [], store._execute
            store._execute = lambda sql, params=(), **k: seen.append(sql) or execute(sql, params, **k)
            assert refresher.run() == {'checked': 2, 'written': 1}
            store._execute = execute
            # The searchable-set scan runs outside the writer lock; the delete only re-checks the found ids.
            deletes = [sql for sql in seen if sql.lstrip().startswith('DELETE FROM agentcon_search.capability_text')]
            assert deletes and all('jsonb_array_elements_text' in sql for sql in deletes)
            with store.tx(readonly=True):
                left = dict(store._execute('SELECT resource_id,body FROM agentcon_search.capability_text').fetchall())
            assert set(left) == set(ids[:2]) and 'tide tables' in left[ids[0]]
            # Ranking rows: the stored text equals the live derivation, and a changed column drops it.
            from agent_market.concierge.discovery import ranking_text, RANKING_COLUMNS
            with store.tx(readonly=True):
                compact = pct.ranking_rows(store, ids)
                live = {row['id']: dict(row) for row in resources(store, ids, 'active=1', (), allow_partial=True,
                                                                     columns=RANKING_COLUMNS)}
            assert set(compact) == set(ids[:2])
            assert all(compact[rid]['_rank_text'] == ranking_text(live[rid]) for rid in compact)
            with store.tx():
                store._execute("UPDATE resources SET usage_tools='[]' WHERE id=%s", (ids[1],))
            with store.tx(readonly=True):
                assert set(pct.ranking_rows(store, ids)) == {ids[0]}
            # A row confirmed at its current generation is not hashed again (the stale ids[1] is,
            # every time); one without a generation row is always hashed and never confirmed.
            hashed = []
            execute = store._execute
            def recording(sql, params=(), **k):
                if 'md5(' in sql:
                    hashed.append(set(json.loads(params[0])))
                return execute(sql, params, **k)
            store._execute = recording
            with store.tx(readonly=True):
                assert set(pct.ranking_rows(store, ids)) == {ids[0]}
            assert hashed == [{ids[1]}]
            store._execute = execute
            with store.tx():
                store._execute('DELETE FROM resource_observation_generations WHERE resource_id=%s', (ids[0],))
            pct._confirmed.clear()
            store._execute = recording
            for _ in range(2):
                hashed.clear()
                with store.tx(readonly=True):
                    assert set(pct.ranking_rows(store, ids)) == {ids[0]}
                assert hashed == [{ids[0], ids[1]}]
            store._execute = execute
            assert ids[0] not in pct._confirmed


def test_rank_hash_matches_the_database_digest():
    from pathlib import Path
    import pytest
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    rows = [listing(), listing(description=None, usage_guide='{"tools":[]}'), listing(name='Wetter \u00fc\U0001f600 |:')]
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE TABLE r(kind text,name text,description text,usage_guide text,usage_tools text)')
            for row in rows:
                conn.execute('INSERT INTO r VALUES(%s,%s,%s,%s,%s)', tuple(row.get(f) for f in pct.RANK_FIELDS))
            digests = [value for (value,) in conn.execute('SELECT ' + pct.RANK_HASH_SQL + ' FROM r').fetchall()]
    assert digests == [pct.rank_hash(row) for row in rows]


def test_version_one_projection_migrates_in_place():
    from pathlib import Path
    import pytest
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
            with store.tx():
                store._execute('CREATE SCHEMA agentcon_search')
                store._execute('CREATE TABLE agentcon_search.capability_text_configuration(id BIGINT PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL)')
                store._execute('''CREATE TABLE agentcon_search.capability_text(resource_id BIGINT PRIMARY KEY,
                    source_hash TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL)''')
                store._execute("INSERT INTO agentcon_search.capability_text_configuration VALUES(1,'agentcon-capability-text-v1')")
                store._execute("INSERT INTO agentcon_search.capability_text VALUES(1,'x',1,'old',0)")
            assert not pct.available(store)
            pct.migrate(store)
            assert pct.available(store)
            with store.tx(readonly=True):
                assert tuple(store._execute('SELECT version,rank_text FROM agentcon_search.capability_text').fetchall()[0]) == (1, None)


def test_refresher_notices_a_later_installation(monkeypatch):
    now = [0.0]
    state = {'installed': False}
    monkeypatch.setattr(pct, 'available', lambda store: state['installed'])
    refresher = pct.Refresher(object(), clock=lambda: now[0])
    assert not refresher.due()
    state['installed'] = True
    now[0] = 599
    assert not refresher.due()  # the next check waits ten minutes
    now[0] = 600
    assert refresher.due()


def test_text_never_holds_nul_bytes():
    assert '\x00' not in pct.build(listing(description='Weather\x00forecast'))
    assert 'weather forecast' in pct.build(listing(description='Weather\x00forecast'))
