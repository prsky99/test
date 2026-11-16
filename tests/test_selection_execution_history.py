"""Gateway call history ranks recommendations ahead of the most recent unrelated check (real-task p04/a06, 11-17)."""
import json
import time
from pathlib import Path

import pytest

import agent_market.concierge.selection as selection
from agent_market.concierge.selection import ExecutionHistory, execution_standing
from tests.test_fast_single_recommendation import catalog, chosen  # noqa: F401

# AION's answer to read_web_page in real task p04 (11-17 04:10): payment terms only, counted as a success.
PAID_TERMS = {'kind': 'message', 'role': 'agent', 'parts': [{'kind': 'data', 'data': {
    'skill': 'read_web_page', 'paid': True, 'endpoint': 'https://agentconcierge.biz/api/gateway/a2a/60416',
    'method': 'POST', 'price': '$0.002', 'inputSchema': 'aion.pageRead.input.v1'}}]}


def test_standing_order():
    # p04: WebRead completed for two callers (capped 10 + 1, 1 failed); the newer pick for one caller, 2 of 2.
    assert execution_standing((11, 1, 2600, 2, 1)) > execution_standing((2, 0, 600, 1, 1))
    # One caller's many runs do not beat two callers with fewer; then the rate, then speed.
    assert execution_standing((3, 0, 3000, 2, 0)) > execution_standing((10, 0, 1000, 1, 0))
    assert execution_standing((10, 0, 1000, 1, 0)) > execution_standing((3, 1, 1000, 1, 0))
    assert execution_standing((20, 0, 1500, 1)) > execution_standing((20, 0, 12000, 1)) > execution_standing((20, 0, None, 1))
    # More failures than completions, or answers that were only errors or payment terms, rank below no calls.
    assert execution_standing((1, 4, 3000, 1, 0)) < execution_standing(None) == (0, 0, 0.0, 0)
    assert execution_standing((9, 0, 500, 3, -1))[0] == -1
    assert execution_standing((0, 0, None, 0)) == (0, 0, 0.0, 0) and execution_standing(('x', None)) == (0, 0, 0.0, 0)
    assert execution_standing((5, 5, 1000, 1))[0] == 1


def test_paid_terms_answer_counts_as_a_paywall_at_origin_and_edge(monkeypatch):
    from agent_market.concierge import task_outcomes
    from agent_market.edge_gateway.service import Service
    assert task_outcomes.classify(PAID_TERMS) == 'needs_key'
    # A result with a paid upgrade beside it still counts as a success.
    result = {'content': [{'type': 'text', 'text': 'Found 3 results. Page 1 of 1. Upgrade per call $0.01 via x402.'}]}
    assert task_outcomes.classify(result) == 'succeeded'
    counted = []
    monkeypatch.setattr(task_outcomes, 'count', lambda rid, outcome, tool=None, now=None: counted.append((rid, outcome)))
    row = {'resource_id': 60416, 'state': 'succeeded', 'error_code': None}
    Service.count_outcome(row, PAID_TERMS)
    Service.count_outcome(row, result)
    Service.count_outcome(row)                                      # no answer: the state, as before
    Service.count_outcome(row, {'managed': {'protocol': 'x402'}})   # x402 terms are not read
    Service.count_outcome({**row, 'state': 'failed', 'error_code': 'EXECUTION_FAILED'}, result)
    assert counted == [(60416, 'needs_key'), (60416, 'succeeded'), (60416, 'succeeded'), (60416, 'succeeded'),
                       (60416, 'failed')]


def test_history_is_read_in_the_background_and_ignored_when_stale():
    clock = [1000.0]
    calls = []

    class Source:
        def execution_history(self, since):
            calls.append(since)
            return {7: (3, 0, 900, 1)}
    history = ExecutionHistory(clock=lambda: clock[0])
    assert history.read(Source()) == {}          # nothing yet: the old order; one refresh started
    for _ in range(200):
        if history.at:
            break
        time.sleep(0.01)
    assert calls == [1000.0 - 7 * 86400] and history.read(Source())[7][:4] == (3, 0, 900, 1)
    assert len(calls) == 1                       # fresh: no further read
    clock[0] += ExecutionHistory.STALE + 1
    history.job = True                           # a refresh in flight does not start another
    assert history.read(Source()) == {} and len(calls) == 1

    class Broken:
        def execution_history(self, since):
            raise RuntimeError('down')
    failing = ExecutionHistory(clock=lambda: clock[0])
    failing.refresh(Broken())
    assert failing.value == {} and failing.retry_at == clock[0] + ExecutionHistory.RETRY and not failing.job


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
    asked = iter(('mcp stock news', 'mcp stock market news'))
    ask = lambda: client.post('/chat', json={'message': next(asked)}).json()  # new wording: no answer cache
    read = []
    monkeypatch.setattr(store, 'execution_history',
                        lambda since: read.append(since) or {old: (10, 1, 2000, 2), new: (1, 3, 9000, 1)}, raising=False)
    empty = ExecutionHistory()
    monkeypatch.setattr(empty, 'read', lambda store: {})     # no table yet
    monkeypatch.setattr(selection, 'EXECUTION_HISTORY', empty)
    assert chosen(ask())['id'] == new  # the most recent verification leads, as before
    filled = ExecutionHistory()
    filled.refresh(store)                                    # what the background thread does
    assert read and abs(read[-1] - (time.time() - 7 * 86400)) < 120
    monkeypatch.setattr(selection, 'EXECUTION_HISTORY', filled)
    assert chosen(ask())['id'] == old
    from agent_market.concierge.retrieval_metrics import _STAGES
    assert 'execution_history' in _STAGES  # an unknown stage name raises inside the request


def test_postgres_execution_history_caps_each_caller():
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
            runs = [('us', 7, 'succeeded', 100 + i, 2) for i in range(14)]           # one caller: 14, counted 10
            runs += [('them', 7, 'succeeded', 50, 4), ('us', 7, 'failed', 30, 31), ('us', 7, 'outcome_unknown', 40, None),
                     ('us', 7, 'prepared', 45, None), ('us', 8, 'succeeded', 9 * 86400, 1), ('us', 9, 'failed', 20, 1)]
            for n, (who, rid, state, age, took) in enumerate(runs):
                conn.execute("INSERT INTO edge_gateway_runs VALUES(%s,%s,%s,'h',%s,'v','o',%s,'b',NULL,%s,%s,%s,NULL)",
                             ('run%d' % n, who, 'i%d' % n, rid, state, now - age, now + 60,
                              None if took is None else now - age + took))
            got = store.execution_history(now - 7 * 86400)
            assert set(got) == {7, 9}  # resource 8 ran only before the window
            ok, bad, ms, callers = got[7]
            assert (ok, bad, callers) == (11, 2, 2) and abs(ms - 32000 / 15) < 1  # mean of all 15 completed runs
            assert got[9][:2] == (0, 1) and got[9][3] == 0
            assert store.execution_history(now + 60) == {}
