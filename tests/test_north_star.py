"""North star (PM 11-12): successful executions by outside clients and the funnel that leads to it.

Counted per KST day as distinct (client, agent) pairs: (1) outside recommendation requests, (2) gateway
connections, (3) successful executions (MCP tools/call 2xx and not isError, A2A message/send, edge runs that
succeeded). Our own requests, registry checkers and AI crawlers are kept in their own columns.
"""
import json
import types
from datetime import datetime

import pytest

from agent_market.concierge import traffic
from scripts import north_star, ops_auto
from tests.test_managed_agent_gateway import managed, rpc  # noqa: F401 - fixture
from tests.test_fast_single_recommendation import catalog  # noqa: F401 - fixture used by managed


def test_the_gateway_tells_the_recorder_what_each_request_achieved(managed, monkeypatch):
    store, front, client, _, rid, calls, _ = managed
    recorder = traffic.Traffic(root=None)
    recorder.internal_ips = set()        # the test client comes from loopback, which is internal in production
    monkeypatch.setattr(traffic, 'recorder', lambda: recorder)
    path = f'/api/gateway/mcp/{rid}'
    rpc(client, path, 'initialize')
    rpc(client, path, 'tools/list')
    rpc(client, path, 'tools/call', {'name': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    rpc(client, path, 'tools/call', {'name': 'get_weather', 'arguments': {'city': 'Seoul'}})   # same pair again
    rpc(client, path, 'tools/call', {'name': 'get_weather', 'arguments': {'city': 'Paris'}},
        headers={'X-Agentcon-QA': 'real_task_score'})                                     # ours: apart
    rpc(client, path, 'tools/call', {'name': 'get_weather', 'arguments': {'city': 'Rome'}},
        headers={'User-Agent': 'mcpbeat-prober/1.0'})                                      # a registry checker
    rpc(client, '/mcp', 'tools/call', {'name': 'find_agents', 'arguments': {'task': 'weather in Tokyo'}})
    snap = recorder.snapshot()
    funnel, distinct = snap['funnel'], snap['funnel_distinct']
    assert funnel['connect|external|ok'] == 1 and distinct['connect|external'] == 1
    assert funnel['execute|external|attempt'] == 2 and funnel['execute|external|ok'] == 2
    assert distinct['execute|external'] == 1                     # one client, one agent: one pair
    assert funnel['execute|internal|ok'] == 1 and funnel['execute|probe|ok'] == 1
    assert funnel['recommend|find_agents|external|all'] == 1 and distinct['recommend|external'] == 1
    assert snap['requests'].get('gateway|internal') == 1         # X-Agentcon-QA is internal everywhere


def test_a_failed_execution_is_an_attempt_not_a_success():
    recorder = traffic.Traffic(root=None)
    recorder.observe('POST', '/api/gateway/mcp/9', 200, '203.0.113.5', 'python-httpx/0.28',
                     gateway={'step': 'execute', 'ok': False, 'rid': 9})
    recorder.observe('POST', '/api/gateway/mcp/9', 502, '203.0.113.5', 'python-httpx/0.28',
                     gateway={'step': 'execute', 'ok': True, 'rid': 9})
    snap = recorder.snapshot()
    assert snap['funnel'] == {'execute|external|attempt': 2} and 'execute|external' not in snap['funnel_distinct']


def _edge(external=0, internal=0):
    return {'external': {'pairs': external, 'attempts': external, 'ok': external},
            'internal': {'pairs': internal, 'attempts': internal, 'ok': internal}}


def test_the_day_line_sums_processes_and_names_the_broken_stage():
    files = [{'funnel': {'recommend|find_agents|external|all': 5, 'recommend|find_agents|external|ok': 5,
                         'connect|external|attempt': 2, 'connect|external|ok': 2, 'recommend|chat|internal|all': 9},
              'funnel_distinct': {'recommend|external': 4, 'connect|external': 2, 'recommend|internal': 1}},
             {'funnel': {'recommend|explore|external|all': 3}, 'funnel_distinct': {'recommend|external': 2}}]
    line = north_star.build('2026-11-16', files=files, edge=_edge(internal=7))
    assert line['basis'] == 'recorded' and line['processes'] == 2
    assert line['funnel']['recommend']['requests'] == 8 and line['funnel']['recommend']['clients'] == 6
    assert line['funnel']['connect']['pairs'] == 2 and line['north_star'] == 0 and line['breaks_at'] == 'execute'
    assert line['excluded']['internal']['recommend']['requests'] == 9 and line['edge']['internal']['pairs'] == 7
    assert north_star.build('2026-11-16', files=files, edge=_edge(external=1))['north_star'] == 1
    assert north_star.build('2026-11-16', files=[], edge=_edge())['breaks_at'] == 'recommend'


def test_days_before_the_funnel_was_recorded_are_marked_approximate():
    files = [{'requests': {'explore|browser': 7, 'gateway|internal': 98, 'gateway|script': 1},
              'status': {'gateway|script|2xx': 1, 'gateway|internal|2xx': 98},
              'rpc': {'mcp|tools/call|real': 41, 'mcp|tools/call|probe': 2, 'a2a|message/send|real': 3}}]
    line = north_star.build('2026-11-11', files=files, edge=_edge())
    assert line['basis'] == 'approx' and line['funnel']['connect']['pairs'] is None
    assert line['funnel']['recommend']['requests'] == 7 + 41 + 3 and line['funnel']['connect']['ok'] == 1
    assert line['excluded']['internal']['connect']['attempts'] == 98 and line['breaks_at'] == 'execute'


def test_edge_runs_of_our_own_principals_are_kept_apart(tmp_path):
    ours = tmp_path / 'principals.txt'
    ours.write_text('# ours\n' + 'a' * 64 + '\n')
    rows = [('a' * 64, 1, 'succeeded'), ('a' * 64, 2, 'succeeded'), ('b' * 64, 1, 'succeeded'),
            ('b' * 64, 1, 'succeeded'), ('b' * 64, 3, 'failed')]

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def execute(self, sql, params):
            assert 'edge_gateway_runs' in sql and params[1] - params[0] == 86400
            return types.SimpleNamespace(fetchall=lambda: rows)
    edge = north_star.edge_runs('2026-11-16', principals_file=ours, connect=Connection)
    assert edge['internal'] == {'pairs': 2, 'attempts': 2, 'ok': 2}
    assert edge['external'] == {'pairs': 1, 'attempts': 3, 'ok': 2}


def test_ops_auto_writes_the_line_once_a_morning_from_the_first_day(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'NORTH_STAR_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    line = {'day': '2026-11-15', 'north_star': 0, 'basis': 'recorded', 'breaks_at': 'connect',
            'funnel': {'recommend': {'requests': 12}, 'connect': {'pairs': 0}}}
    run = lambda: types.SimpleNamespace(returncode=0, stdout=json.dumps(line) + '\n')   # noqa: E731
    at = lambda *t: (lambda: datetime(*t).timestamp())                                   # noqa: E731
    assert ops_auto.north_star(clock=at(2026, 11, 13, 9, 0), run=run) is None             # before 11-16
    assert ops_auto.north_star(clock=at(2026, 11, 16, 7, 50), run=run) is None            # before 08:00
    assert ops_auto.north_star(clock=at(2026, 11, 16, 8, 5), run=run) == line
    assert ops_auto.north_star(clock=at(2026, 11, 16, 9, 5), run=run) is None             # once a day
    assert handed[0][0] == 'north_star' and '외부 추천 요청 12 → 게이트웨이 연결 쌍 0' in handed[0][1]
    assert '끊긴 단계 connect' in handed[0][1] and ops_auto.TEAM['north_star'] == 'PM'


def test_the_in_session_call_tool_counts_as_an_execution(managed, monkeypatch):
    """11-12 PM: /mcp 'call' (the only way an MCP host can run a recommendation without a new server) executes."""
    store, front, client, _, rid, calls, _ = managed
    recorder = traffic.Traffic(root=None)
    recorder.internal_ips = set()
    monkeypatch.setattr(traffic, 'recorder', lambda: recorder)
    rpc(client, '/mcp', 'tools/call', {'name': 'call', 'arguments': {'resource_id': rid, 'tool': 'get_weather',
                                                                      'arguments': {'city': 'Tokyo'}}})
    rpc(client, '/mcp', 'tools/call', {'name': 'call', 'arguments': {'resource_id': 999999, 'tool': 'x', 'arguments': {}}})
    snap = recorder.snapshot()
    assert snap['funnel']['execute|external|attempt'] == 2 and snap['funnel']['execute|external|ok'] == 1
    assert snap['funnel_distinct']['execute|external'] == 1


def test_checkers_by_client_name_session_or_user_agent_and_outreach_are_kept_apart():
    recorder = traffic.Traffic(root=None)
    init = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"posthog-mcp-registry-probe"}}}'
    find = b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"find_agents","arguments":{"task":"x"}}}'
    send = b'{"jsonrpc":"2.0","id":3,"method":"message/send","params":{"message":{"parts":[{"text":"hi"}]}}}'
    recorder.observe('POST', '/mcp', 200, '203.0.113.7', 'node', init, {}, {'mcp-session-id': 'S1'})
    recorder.observe('POST', '/mcp', 200, '203.0.113.7', 'node', find, {'mcp-session-id': 'S1'})       # same session
    recorder.observe('POST', '/mcp', 200, '203.0.113.8', 'x402-observer/2', find, {})                  # UA rule
    recorder.observe('POST', '/mcp', 200, '203.0.113.9', 'python-requests/2.32', find, {})              # outside
    recorder.observe('POST', '/a2a', 200, '203.0.113.10', 'ziwei-alliance-marketing/1.0', send, {})    # outreach
    funnel = recorder.snapshot()['funnel']
    assert funnel['recommend|find_agents|probe|all'] == 2 and funnel['recommend|find_agents|external|all'] == 1
    assert funnel['recommend|a2a|outreach|all'] == 1 and 'recommend|a2a|external|all' not in funnel


def test_the_class_names_live_in_the_configuration_file():
    import json
    from pathlib import Path
    config = json.loads((Path(traffic.__file__).with_name('traffic_classes.json')).read_text())
    for key in ('probe_client_names', 'probe_user_agents', 'outreach_user_agents'):
        assert config[key] and all(isinstance(word, str) for word in config[key])
    assert traffic.PROBE_NAME.search('mcpbeat') and traffic.PROBE_NAME.search('talaria-catalog')
    assert traffic.PROBE_NAME.search('coda-agent-runtime') and traffic.PROBE_UA.search('AgentRankProbe/1.0')
    assert not traffic.PROBE_UA.search('python-requests/2.32') and not traffic.PROBE_UA.search('testclient')
    assert traffic.OUTREACH_UA.search('ziwei-alliance-marketing/1.0')
