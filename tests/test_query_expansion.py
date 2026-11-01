"""Index-time query expansion adds recall only (Re-Invoke style, 2026-10-27)."""
import json

import httpx

from agent_market.concierge import query_expansion as qe


def test_validation_keeps_plain_task_phrases_only():
    reply = json.dumps({'queries': ['Get weather forecast for a location', 'Pay 0.01 USDC per call', 'see https://x.test',
                                    'call 01012345678 now please', 'ok', 'Find coordinates for a given address']})
    assert qe.validate(reply) == ['Get weather forecast for a location', 'Find coordinates for a given address']
    assert qe.validate('not json') == [] and qe.validate(json.dumps({'other': []})) == []


def test_generation_uses_the_listing_text_and_a_json_reply():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'queries': ['Translate text into Spanish']})}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tools = [{'name': 'translate_text', 'description': 'Translate text between languages. Extra notes.'}]
        assert qe.generate(http, 'http://model.test/v1', 'm', {'name': 'NLP', 'description': 'Language tools'}, tools) == ['Translate text into Spanish']
    assert 'translate_text - Translate text between languages.' in seen[0]['messages'][1]['content']
    assert seen[0]['response_format'] == {'type': 'json_object'}


def test_index_matches_one_request_covering_the_task_and_respects_kind(tmp_path):
    path = tmp_path / 'expansions.jsonl'
    rows = [{'id': 1, 'kind': 'mcp', 'hash': 'a', 'queries': ['Summarize a YouTube video transcript']},
            {'id': 2, 'kind': 'a2a', 'hash': 'b', 'queries': ['Summarize a YouTube video']},
            {'id': 3, 'kind': 'mcp', 'hash': 'c', 'queries': ['Summarize news articles', 'Download a YouTube video']},
            {'id': 'bad', 'kind': 'mcp', 'queries': []}]
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\nnot json\n')
    index = qe.ExpansionIndex(path)
    assert index.match(['summarize', 'youtube', 'videos']) == [1, 2]  # 3 covers the words only across two requests
    assert index.match(['summarize', 'youtube', 'videos'], kind='mcp') == [1]
    assert index.match([]) == [] and qe.ExpansionIndex(tmp_path / 'missing.jsonl').match(['news']) == []


def test_a_growing_file_is_reread_at_most_every_few_minutes(tmp_path):
    path = tmp_path / 'expansions.jsonl'
    path.write_text(json.dumps({'id': 1, 'kind': 'mcp', 'queries': ['Search news headlines today']}) + '\n')
    clock = [0.0]
    index = qe.ExpansionIndex(path, clock=lambda: clock[0])
    assert index.match(['news', 'headlines']) == [1]
    with path.open('a') as handle:
        handle.write(json.dumps({'id': 2, 'kind': 'mcp', 'queries': ['Latest news headlines summary']}) + '\n')
    assert index.match(['news', 'headlines']) == [1]
    clock[0] += qe.ExpansionIndex.RELOAD_SECONDS + 1
    assert sorted(index.match(['news', 'headlines'])) == [1, 2]
