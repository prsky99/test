"""Chat answers stream the steps under way before the answer itself (2026-11-01)."""
# ruff: noqa: F811 -- pytest fixtures imported for dependency injection.
import json

from agent_market.concierge import chat_progress
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def events(response):
    return [json.loads(block[6:]) for block in response.text.split('\n\n') if block.startswith('data: ')]


def test_stream_names_each_step_then_returns_the_plain_answer(catalog):
    _, _, client, add, _ = catalog
    add('Weather')
    plain = client.post('/chat', json={'message': 'MCP weather forecast'})
    streamed = client.post('/chat', json={'message': 'MCP weather forecast'}, headers={'Accept': 'text/event-stream'})
    assert streamed.status_code == 200 and streamed.headers['content-type'].startswith('text/event-stream')
    assert streamed.headers['cache-control'] == 'no-store'
    found = events(streamed)
    steps = [event['step'] for event in found if event['type'] == 'progress']
    assert steps[:3] == ['review', 'understand', 'search'] and steps[-1] == 'prepare'
    assert all(event['label'] == chat_progress.LABELS[event['step']] for event in found if event['type'] == 'progress')
    elapsed = [event['elapsed_ms'] for event in found if event['type'] == 'progress']
    assert elapsed == sorted(elapsed)
    result = found[-1]
    assert result['type'] == 'result' and result['visitor_token'].startswith('vt_')  # the plain answer sends it as a header
    body, expected = result['body'], plain.json()
    assert [item['id'] for item in body['data']['recommendations']] == [item['id'] for item in expected['data']['recommendations']]
    assert body['intent'] == expected['intent']


def test_stream_reports_a_busy_store_as_an_error_event(catalog, monkeypatch):
    import sqlite3
    _, front, client, _, _ = catalog
    monkeypatch.setattr(front, 'chat_payload', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('locked')))
    found = events(client.post('/chat', json={'message': 'weather'}, headers={'Accept': 'text/event-stream'}))
    assert found == [{'type': 'error', 'status': 503, 'error': 'The service is busy. Please try again shortly.',
                      'error_code': 'SERVICE_BUSY'}]


def test_steps_are_silent_without_a_listener():
    chat_progress.step('search')  # no stream: nothing to report and nothing raised
    seen = []
    run = chat_progress.listening(seen.append, lambda: chat_progress.step('search') or 'done')
    assert run() == 'done' and seen[0]['step'] == 'search' and seen[0]['label'] == 'Searching active agents'
    chat_progress.step('prepare')
    assert len(seen) == 1  # the listener ends with its request
