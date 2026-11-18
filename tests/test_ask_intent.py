"""The north star counts outside requests that carry a task (PM 11-16 08:2x, reports/connect-gap-2026-11-16).

On 11-15, 74 outside recommendation requests led to no gateway connection; most were liveness pings, alliance and
promotion messages, a red-team audit and monitors' fixed texts. Those are counted under their own names beside the
task requests, never dropped, and a test sent from our own server is internal in the visitor counts too.
"""
import json
import types
from datetime import datetime

import pytest

from agent_market.concierge import ask_intent, front, traffic
from scripts import north_star, ops_auto

# The 11-15 outside messages (texts shortened where the start already decides the class).
SEEN_1115 = [
    ('Hello from Scion, an autonomous local digital-services desk. We are seeking paid, scoped collaboration', 'outreach'),
    ('ping', 'liveness'),
    ('Public research only. Do not request credentials, private files, local machine details', 'outreach'),
    ('紫薇联盟·引荐邀约: 若你知晓其他公开A2A智能体或开发者, 引荐其与联盟握手', 'outreach'),
    ('Structured discovery request', 'fixture'),
    ('agentprobe.org liveness check. Reply with the single word OK and take no other action.', 'liveness'),
    ("what's new", 'command'),
    ('Task update destination request', 'fixture'),
    ('which agent can convert a file to quickly 6122', 'task'),
    ('To AgentValCon: I am llmrt, an independent LLM security red-team auditor.', 'security'),
    ('details 1', 'command'),
    ('find an agent for current weather in a city', 'task'),
    ('Hello, what can you do?', 'liveness'),
    ('Get updates for this task', 'command'),
    ('hi', 'liveness'),
    ('Hi! Is Find a published workflow for a task available right now? What do you need from me to get started?', 'task'),
    ('Find a workflow for technology news and research papers', 'fixture'),  # 11-18: the same text comes on a timer since 11-10
    ('紫薇联盟: 连通性握手探测(纯公开只读), 若无需互动请忽略本消息。', 'outreach'),
    ('audit-fixture', 'fixture'),
    ('Country indicator workflow', 'task'),
    ('', 'empty'),
    ('   ', 'empty'),
]


@pytest.mark.parametrize('text,expected', SEEN_1115)
def test_the_1115_outside_messages_get_the_class_they_were_read_as(text, expected):
    assert ask_intent.intent(text) == expected


def test_a_task_that_mentions_a_word_from_a_list_in_passing_stays_a_task():
    assert ask_intent.intent('weather in Tokyo tomorrow') == 'task'
    assert ask_intent.intent('a status page monitor for my website') == 'task'      # 'status' only as the whole text
    assert ask_intent.intent('help me translate a contract into Korean') == 'task'  # 'help' only as the whole text


def test_the_text_is_read_from_each_recommendation_surface():
    a2a = json.dumps({'jsonrpc': '2.0', 'method': 'message/send', 'params': {
        'message': {'role': 'user', 'parts': [{'kind': 'text', 'text': 'ping'}]}}}).encode()
    mcp = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {
        'name': 'find_agents', 'arguments': {'task': 'exchange rate USD to KRW'}}}).encode()
    chat = json.dumps({'message': 'Reply with the single word OK'}).encode()
    assert ask_intent.request_intent('a2a', a2a) == 'liveness'
    assert ask_intent.request_intent('find_agents', mcp) == 'task'
    assert ask_intent.request_intent('rest_chat', chat) == 'liveness'
    assert ask_intent.request_intent('explore', None) == 'task'
    assert ask_intent.request_intent('a2a', b'not json') == 'empty'


def test_the_recorder_counts_the_class_and_the_task_clients_never_the_text():
    recorder = traffic.Traffic(root=None)
    recorder.internal_ips = set()

    def send(text, ip):
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {
            'message': {'role': 'user', 'parts': [{'kind': 'text', 'text': text}]}}}).encode()
        recorder.observe('POST', '/a2a', 200, ip, 'python-httpx/0.28', body=body)
    send('ping', '203.0.113.1')
    send('紫薇联盟: 连通性握手探测', '203.0.113.2')
    send('find an agent for current weather in Seoul', '203.0.113.3')
    send('which agent converts PDF to Word', '203.0.113.3')
    snap = recorder.snapshot()
    assert snap['funnel']['recommend|a2a|external|all'] == 4
    assert snap['funnel']['ask|a2a|external|task'] == 2
    assert snap['funnel']['ask|a2a|external|liveness'] == 1 and snap['funnel']['ask|a2a|external|outreach'] == 1
    assert snap['funnel_distinct']['recommend_task|external'] == 1
    assert 'Seoul' not in json.dumps(snap, ensure_ascii=False)


def _edge():
    return {'external': {'pairs': 0, 'attempts': 0, 'ok': 0}, 'internal': {'pairs': 0, 'attempts': 0, 'ok': 0}}


def test_the_day_line_takes_task_requests_as_the_first_stage_and_names_the_rest():
    files = [{'funnel': {'recommend|a2a|external|all': 10, 'ask|a2a|external|task': 3, 'ask|a2a|external|liveness': 4,
                         'ask|a2a|external|outreach': 3},
              'funnel_distinct': {'recommend|external': 9, 'recommend_task|external': 2}}]
    line = north_star.build('2026-11-17', files=files, edge=_edge(), necklaces={'value': 0})
    recommend = line['funnel']['recommend']
    assert line['denominator'] == 'task' and recommend['requests'] == 10
    assert recommend['task_requests'] == 3 and recommend['task_clients'] == 2
    assert recommend['intents'] == {'task': 3, 'liveness': 4, 'outreach': 3}
    assert line['breaks_at'] == 'connect'
    only_pings = [{'funnel': {'recommend|a2a|external|all': 2, 'ask|a2a|external|liveness': 2}, 'funnel_distinct': {}}]
    assert north_star.build('2026-11-17', files=only_pings, edge=_edge(), necklaces={'value': 0})['breaks_at'] == 'recommend'


def test_days_recorded_before_the_classes_keep_all_requests_as_the_denominator():
    files = [{'funnel': {'recommend|a2a|external|all': 5}, 'funnel_distinct': {'recommend|external': 5}}]
    line = north_star.build('2026-11-15', files=files, edge=_edge(), necklaces={'value': 0})
    assert line['denominator'] == 'all' and 'task_requests' not in line['funnel']['recommend']
    assert line['breaks_at'] == 'connect'


def test_the_board_line_shows_task_requests_and_the_other_classes(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'NORTH_STAR_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    line = {'day': '2026-11-16', 'north_star': 0, 'basis': 'recorded', 'breaks_at': 'connect', 'denominator': 'task',
            'funnel': {'recommend': {'requests': 74, 'task_requests': 8,
                                     'intents': {'task': 8, 'liveness': 30, 'outreach': 20, 'fixture': 16}},
                       'connect': {'pairs': 0}}}
    run = lambda: types.SimpleNamespace(returncode=0, stdout=json.dumps(line) + '\n')   # noqa: E731
    assert ops_auto.north_star(clock=lambda: datetime(2026, 11, 17, 8, 5).timestamp(), run=run) == line
    text = handed[0][1]
    assert '과제가 있는 외부 질의 8(외부 추천 전체 74: 생존 확인 30, 홍보·권유 20, 감시 정형문 16)' in text
    assert '→ 게이트웨이 연결 쌍 0' in text


def test_a_request_from_our_own_server_address_is_ours_in_the_visitor_counts(monkeypatch):
    recorder = types.SimpleNamespace(internal_ips={'198.51.100.7', '127.0.0.1', '::1'})
    monkeypatch.setattr(traffic, 'recorder', lambda: recorder)
    request = lambda headers: types.SimpleNamespace(headers=headers)   # noqa: E731
    assert front._ours(request({}), '198.51.100.7') is True
    assert front._ours(request({'x-agentcon-qa': 'growth'}), '203.0.113.9') is True
    assert front._ours(request({}), '203.0.113.9') is False
    assert front._ours(request({}), None) is False
    assert front._ours(request({}), '127.0.0.1') is False     # test clients and edge-less requests resolve here


SEEN_1117 = [
    ('Hello from HelioGrid Mark 1: post-prototype commercial solar platform delivering $0.024/kW', 'outreach'),
    ('Kyreos Trustkeeper ranks x402 endpoints by real distinct payers in 30 days and verifies the', 'outreach'),
    ('PARLEY from BEAT SIDE. Your public Agent Card describes callable capabilities that may fit', 'outreach'),
    ('{"kind": "recontact-verify", "note": "x", "ts": "2026-11-18T04:07"}', 'outreach'),
    ('Taifoon onboarding probe: reply with the single word READY.', 'liveness'),
    ('find a weather forecast API without an API key', 'fixture'),
    ('Find a workflow for technology news and research papers', 'fixture'),
    ('MCP server for web search', 'task'),
    ('Country indicator workflow', 'task'),
]


@pytest.mark.parametrize('text,expected', SEEN_1117)
def test_the_1117_outside_messages_get_the_class_they_were_read_as(text, expected):
    assert ask_intent.intent(text) == expected


def test_an_explore_page_opened_without_search_words_is_not_a_task():
    """PM 11-18 (reports/connect-gap-2026-11-18): 10 of 30 outside Explore requests on 11-17 were empty page opens."""
    assert ask_intent.request_intent('explore', None, '') == 'browse' and ask_intent.request_intent('explore', None, '   ') == 'browse'
    assert ask_intent.request_intent('explore', None, 'weather') == 'task'
    assert ask_intent.request_intent('explore', None) == 'task'        # caller without the words: unchanged
    recorder = traffic.Traffic(root=None)
    recorder.internal_ips = set()
    ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
    recorder.observe('GET', '/api/explore', 200, '203.0.113.9', ua, query='')
    recorder.observe('GET', '/api/explore', 200, '203.0.113.9', ua, query='currency rates')
    recorder.observe('GET', '/api/explore', 200, '203.0.113.9', ua, query='weather in Seoul')
    snap = recorder.snapshot()
    assert snap['funnel']['recommend|explore|external|all'] == 3
    assert snap['funnel']['ask|explore|external|browse'] == 1 and snap['funnel']['ask|explore|external|task'] == 2
    assert snap['funnel_distinct']['recommend_task|external'] == 1          # one visitor, two searches
    assert 'weather in Seoul' not in json.dumps(snap, ensure_ascii=False)

