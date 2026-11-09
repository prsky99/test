import io
import json

import pytest

from agent_concierge import AgentConcierge
from agent_concierge.tools import _run


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(items, seen):
    def opener(request, timeout):
        seen.append(request.full_url)
        return Response(json.dumps({'items': items}).encode())
    return opener


ITEM = {'id': 7, 'kind': 'mcp', 'name': 'Weather', 'description': 'Forecasts', 'eval_grade': 'A', 'health_status': 'healthy',
        'last_check_at': 1794222227, 'trial_ok': 1, 'auth_required': 0,
        'connection_readiness': {'verified_callable': True, 'evidence_scope': 'execution', 'verified_at': 1794222288}}


def test_search_builds_a_read_only_query_and_parses_evidence():
    seen = []
    agents = AgentConcierge(opener=opener_for([ITEM], seen)).search('weather forecast', protocol='mcp', checked_only=True, limit=99)
    assert '/api/explore?' in seen[0] and 'kind=mcp' in seen[0] and 'verified=1' in seen[0] and 'limit=45' in seen[0]
    agent = agents[0]
    assert agent.execution_checked_at.startswith('2026-11-') and agent.quality_grade == 'A'
    assert 'execution check succeeded' in agent.summary()


def test_validation_and_empty_results():
    client = AgentConcierge(opener=opener_for([], []))
    with pytest.raises(ValueError):
        client.search('  ')
    with pytest.raises(ValueError):
        client.search('x', protocol='grpc')
    assert _run('nothing', client) == 'No listed agent matched this task.'
