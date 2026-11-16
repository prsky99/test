"""Gateway call history ranks recommendations ahead of the most recent unrelated check (real-task p04/a06, 11-17)."""
import json
import time
from pathlib import Path

import pytest

from agent_market.concierge.selection import execution_standing
from tests.test_fast_single_recommendation import catalog, chosen  # noqa: F401


def test_standing_prefers_a_long_record_over_a_short_fast_one():
    # p04: WebRead completed 33 of 34 calls in 2.6 s; the newer pick completed 2 of 2 in 0.6 s.
    assert execution_standing((33, 1, 2600)) > execution_standing((2, 0, 600))
    # More failures than completions ranks below a listing nobody has called yet.
    assert execution_standing((1, 4, 3000)) < execution_standing(None) == (0, 0.0, 0)
    assert execution_standing((0, 0, None)) == (0, 0.0, 0)
    # Within one success bucket a faster listing goes first; a missing duration counts as slowest.
    assert execution_standing((20, 0, 1500)) > execution_standing((20, 0, 12000)) > execution_standing((20, 0, None))
    assert execution_standing((5, 5, 1000))[0] == 1 and execution_standing(('x', None)) == (0, 0.0, 0)


def news_pair(add, now):
    tools = json.dumps({'tools': [{'name': 'stock_news', 'description': 'Stock news and market headlines'}]})
    old = add('Steady Stock News', kind='mcp', report_at=now - 7200, category='finance_crypto',
              description='Stock news financial market headlines equities news', usage_guide=tools)
    new = add('Fresh Stock News', kind='mcp', report_at=now - 10, category='finance_crypto',
              description='Stock news financial market headlines equities news', usage_guide=tools)
    return old, new


def test_call_history_outranks_the_latest_check(catalog, monkeypatch):
    store, _, client, add, now = catalog
    old, new = news_pair(add, now)
    asked = iter(('mcp stock news', 'mcp stock market news', 'mcp stock news headlines'))
    ask = lambda: client.post('/chat', json={'message': next(asked)}).json()  # new wording: no answer cache
    assert chosen(ask())['id'] == new  # without history the most recent verification leads
    seen = []
    def history(since):
        seen.append(since)
        return {old: (30, 1, 2000), new: (1, 3, 9000)}
    monkeypatch.setattr(store, 'execution_history', history, raising=False)
    assert chosen(ask())['id'] == old
    from agent_market.concierge.retrieval_metrics import _STAGES
    assert 'execution_history' in _STAGES  # an unknown stage name raised and was swallowed (history ignored)
    assert seen and abs(seen[-1] - (time.time() - 7 * 86400)) < 120
    # A failing read leaves the previous ordering instead of failing the answer.
    monkeypatch.setattr(store, 'execution_history', lambda since: 1 / 0, raising=False)
    assert chosen(ask())['id'] == new


def test_postgres_execution_history_counts_runs_in_the_window():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.edge_gateway.state import SCHEMA
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    now = time.time()
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'h' * 32)
            ddl = next(s for s in SCHEMA if 'TABLE IF NOT EXISTS edge_gateway_runs' in s)
            conn.execute(ddl.replace(' REAL', ' DOUBLE PRECISION').replace(' INTEGER', ' BIGINT'))  # as migrate()
            runs = [(7, 'succeeded', 10, 2), (7, 'succeeded', 20, 4), (7, 'failed', 30, 31),
                    (7, 'outcome_unknown', 40, None), (7, 'prepared', 50, None), (8, 'succeeded', 9 * 86400, 1)]
            for n, (rid, state, age, took) in enumerate(runs):
                conn.execute("INSERT INTO edge_gateway_runs VALUES(%s,'p',%s,'h',%s,'v','o',%s,'b',NULL,%s,%s,%s,NULL)",
                             ('run%d' % n, 'i%d' % n, rid, state, now - age, now + 60,
                              None if took is None else now - age + took))
            got = store.execution_history(now - 7 * 86400)
            assert set(got) == {7}  # resource 8 ran only before the window
            ok, bad, ms = got[7]
            assert (ok, bad) == (2, 2) and abs(ms - 3000) < 1
            assert store.execution_history(now + 60) == {}
