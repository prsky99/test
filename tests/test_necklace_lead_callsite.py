"""The open necklace's run line leads Chat and find_agents answers in its scope; A2A gets 'run necklace' (PM 11-16 C).

Nothing changes while no necklace is offered (necklace_surface.live is empty)."""
import json
import re

from agent_market.concierge import a2a_run, necklace_lead
from agent_market.concierge import necklace_surface as ns
from tests.test_fast_single_recommendation import ask, catalog  # noqa: F401

TOPIC = {'slug': 'topic-evidence-brief', 'name': 'Topic evidence brief', 'status': 'live', 'pricing': {'mode': 'free'},
         'input_schema': {'required': ['topic'], 'properties': {'topic': {'type': 'string'}}}}


def opened(monkeypatch, phrase):
    monkeypatch.setattr(ns, 'live', lambda snapshot=None, now=None: [TOPIC])
    monkeypatch.setattr(necklace_lead, '_PHRASES', {'topic-evidence-brief': [re.compile(r'(?<![\w])' + phrase + r'(?![\w])')]})


def test_nothing_changes_while_no_necklace_is_open(catalog):  # noqa: F811
    _, _, client, add, now = catalog
    add('Weather', report_at=now - 1)
    body = ask(client)
    assert 'Free to run now' not in body['reply'] and 'necklace_lead' not in body['data']


def test_chat_and_find_agents_lead_with_the_line_in_scope(catalog, monkeypatch):  # noqa: F811
    _, _, client, add, now = catalog
    add('Weather', report_at=now - 1)
    opened(monkeypatch, 'weather forecast')
    body = ask(client)
    first = body['reply'].splitlines()[0]
    assert first.startswith('Free to run now: Topic evidence brief (a necklace of tested agents): call tool '
                            '`necklace_topic_evidence_brief` with {"topic":"<topic>"}.')
    assert body['data']['necklace_lead'] == first and body['data']['recommendations']   # the list still follows
    response = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                         'params': {'name': 'find_agents', 'arguments': {'task': 'find an MCP weather forecast API'}}},
                           headers={'Accept': 'application/json, text/event-stream'})
    assert response.json()['result']['content'][0]['text'].startswith('Free to run now: Topic evidence brief')


def test_out_of_scope_tasks_get_no_line(catalog, monkeypatch):  # noqa: F811
    _, _, client, add, now = catalog
    add('Weather', report_at=now - 1)
    opened(monkeypatch, 'research papers about')
    assert 'Free to run now' not in ask(client)['reply']


def test_a2a_gets_the_run_necklace_form():
    line = ('Free to run now: Topic evidence brief (a necklace of tested agents): call tool `necklace_topic_evidence_brief` '
            'with {"topic":"battery recycling"}. https://agentconcierge.biz/necklaces/topic-evidence-brief')
    from agent_market.concierge.engine import Reply
    converted = a2a_run.a2a_wording(Reply(line + '\n\n1. Agent', 'find', {'recommendations': []}))
    assert converted.text.splitlines()[0] == ('Free to run now: Topic evidence brief (a necklace of tested agents): '
                                              'run necklace topic-evidence-brief {"topic":"battery recycling"}. '
                                              'https://agentconcierge.biz/necklaces/topic-evidence-brief')
    assert json.loads(converted.text.splitlines()[0].split('topic-evidence-brief ', 1)[1].split('. https', 1)[0])
