"""The ways an outside agent reaches an offered necklace (11-17, before the first necklace opens on 11-18).

With one necklace live: llms.txt, skill.md, the MCP manifest and tools/list, the A2A card and /api/necklaces name it;
a recommendation in its scope leads with the run line even when no single listing passes the gates; MCP, A2A (with or
without a contextId) and the web run reach the one run entry. Nothing changes while no necklace is offered."""
import json
from datetime import datetime, timedelta, timezone

from agent_market.concierge import necklace_surface as ns
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_necklace_surface import iso, necklace, pearl

TASK = 'Find recent research papers about retrieval augmented generation'
H = {'Accept': 'application/json, text/event-stream'}


def open_topic(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    entry = necklace('topic-evidence-brief', summary='A cited brief on one topic.',
                     input_schema={'type': 'object', 'properties': {'topic': {'type': 'string'}}, 'required': ['topic']},
                     example_input={'topic': 'retrieval augmented generation'}, pricing={'mode': 'free'},
                     gate_passed_at=iso(now - timedelta(hours=2)))
    entry['quality']['tested_at'] = iso(now - timedelta(hours=1))
    entry['pearls'] = [pearl(241601, 'web'), pearl(58183, 'papers'), pearl(900001, 'background')]
    root = tmp_path / 'root'
    (root / 'gateway-data/necklaces').mkdir(parents=True)
    (root / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps(
        {'schema': ns.SCHEMA, 'generated_at': iso(now), 'necklaces': [entry], 'events': []}))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(root))
    calls = []
    monkeypatch.setattr(ns, 'RUN', lambda front, e, args, source, meta=None: calls.append((e['slug'], source)) or
                        {'ok': True, 'output': {'brief': 'fake'}, 'stages': []})
    return calls


def test_every_agent_document_names_the_open_necklace(catalog, monkeypatch, tmp_path):  # noqa: F811
    _, _, client, _, _ = catalog
    open_topic(monkeypatch, tmp_path)
    assert 'necklace_topic_evidence_brief' in client.get('/llms.txt').text
    assert 'necklace_topic_evidence_brief' in client.get('/skill.md').text
    assert 'necklace-topic-evidence-brief' in client.get('/.well-known/agent-card.json').text
    listed = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, headers=H).json()['result']['tools']
    manifest = client.get('/.well-known/mcp.json').json()['tools']
    assert 'necklace_topic_evidence_brief' in [t['name'] for t in listed] and listed == manifest


def test_a_task_in_scope_gets_the_run_line_even_without_a_matching_listing(catalog, monkeypatch, tmp_path):  # noqa: F811
    _, _, client, _, _ = catalog
    open_topic(monkeypatch, tmp_path)
    found = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                      'params': {'name': 'find_agents', 'arguments': {'task': TASK}}}, headers=H).json()
    first = found['result']['content'][0]['text'].splitlines()[0]
    assert first.startswith('Free to run now: Topic Evidence Brief') and 'necklace_topic_evidence_brief' in first
    message = {'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': TASK}]}
    a2a = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 3, 'method': 'message/send', 'params': {'message': message}}).json()
    assert 'run necklace topic-evidence-brief {"topic":"retrieval augmented generation"}' in a2a['result']['parts'][0]['text']


def test_mcp_a2a_and_web_runs_reach_the_run_entry(catalog, monkeypatch, tmp_path):  # noqa: F811
    _, _, client, _, _ = catalog
    calls = open_topic(monkeypatch, tmp_path)
    client.post('/mcp', json={'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                              'params': {'name': 'necklace_topic_evidence_brief', 'arguments': {'topic': 'rag'}}}, headers=H)
    message = {'role': 'user', 'messageId': 'm2', 'parts': [{'kind': 'text', 'text': 'run necklace topic-evidence-brief {"topic":"rag"}'}]}
    a2a = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 5, 'method': 'message/send', 'params': {'message': message}}).json()
    assert a2a['result']['parts'][0]['text'].startswith('Ran necklace topic-evidence-brief')
    client.post('/api/necklaces/topic-evidence-brief/run', json={'topic': 'rag', 'necklace_notice': 'necklace-v1'})
    assert [source for _, source in calls] == ['mcp', 'a2a', 'web']


def test_nothing_changes_while_no_necklace_is_open(catalog):  # noqa: F811
    _, _, client, _, _ = catalog
    assert 'Necklaces you can run' not in client.get('/skill.md').text
    listed = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, headers=H).json()['result']['tools']
    assert listed == client.get('/.well-known/mcp.json').json()['tools'] and not any(t['name'].startswith('necklace_') for t in listed)
