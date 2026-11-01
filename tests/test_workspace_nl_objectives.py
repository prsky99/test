"""Workspace natural-language objectives (2026-10-27): non-English goals and mixed independent searches."""
import json

import httpx
import pytest

from agent_market.concierge.chat_query_rewrite import validate
from agent_market.workflow_goal_policy import _mentions
from agent_market.workspace_goal_coverage import topics

KOREAN = '최근 AI 반도체 뉴스를 찾고, 첫 번째 기사 제목으로 관련 논문을 검색해줘'


def test_translation_segments_may_drop_the_spaces_between_them():
    gap = KOREAN.index(', ') + 1  # the space after the comma is dropped between segments
    segments = [{'source': KOREAN[:gap], 'english': 'Find recent AI semiconductor news, and'},
                {'source': KOREAN[gap + 1:], 'english': 'search related papers with the first article title'}]
    assert KOREAN[gap] == ' '
    assert validate(KOREAN, json.dumps({'segments': segments})).startswith('Find recent AI semiconductor news')
    missing = [{'source': KOREAN[:gap], 'english': 'Find recent AI semiconductor news'}]
    assert validate(KOREAN, json.dumps({'segments': missing})) is None  # uncovered text still fails


@pytest.mark.parametrize('objective,expected', [
    ('Search news about climate policy and research on carbon capture separately', ['climate policy', 'carbon capture']),
    ('Please find research on quantum computing and fusion separately', ['quantum computing research', 'fusion research']),
    ('Find the latest news about chips, then search research papers about the first headline', []),  # a chain
])
def test_independent_subjects_per_task(objective, expected):
    assert topics(objective) == expected


def test_a_second_task_word_after_and_is_a_second_task():
    assert _mentions('Search news about climate policy and research on carbon capture separately') == ['news.search.v1', 'docs.search.v1']
    assert _mentions('Find recent news about AI agents') == ['news.search.v1']


def _proposer(reply):
    from agent_market.workflow_model_proposer import OllamaGraphProposer
    def handler(request):
        if reply is None:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(reply)}}],
                                         'model': 'gemma4-e4b-mlx'})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaGraphProposer(endpoint='http://model.test:8000/v1', model='gemma4-e4b-mlx', provider='openai',
                               allow_http=True, http=client), client


def test_non_english_objective_is_translated_once_and_validated():
    objective = '배터리 재활용에 관한 논문을 찾아줘'
    proposer, client = _proposer({'segments': [{'source': objective, 'english': 'Find a paper about battery recycling'}]})
    with client:
        assert proposer.normalize_objective(objective) == 'Find a paper about battery recycling'
        assert proposer.normalize_objective('Find recent news about AI agents') == 'Find recent news about AI agents'


@pytest.mark.parametrize('reply', [None, {'segments': [{'source': 'other text', 'english': 'Book a hotel'}]}])
def test_unvalidated_or_unavailable_translation_keeps_the_original(reply):
    objective = '배터리 재활용 논문'
    proposer, client = _proposer(reply)
    with client:
        assert proposer.normalize_objective(objective) == objective
