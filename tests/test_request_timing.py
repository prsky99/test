"""Public recommendation requests carry Server-Timing stages (2026-11-10)."""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agent_market.concierge.request_timing import RequestTiming, timed_path
from agent_market.concierge.retrieval_metrics import stage


def _slow(request):
    with stage('exposure'):
        sum(range(1000))
    return JSONResponse({'ok': True}, headers={'Server-Timing': 'concierge;dur=1'})


def test_recommendation_paths_report_their_stages_and_others_do_not():
    app = Starlette(routes=[Route('/mcp', _slow, methods=['POST']), Route('/other', _slow)])
    app.add_middleware(RequestTiming)
    client = TestClient(app)
    timing = client.post('/mcp').headers['server-timing']
    assert timing.startswith('concierge;dur=1, server;dur=') and 'exposure;dur=' in timing
    assert client.get('/other').headers['server-timing'] == 'concierge;dur=1'
    assert timed_path('/a2a') and timed_path('/agents/best/data') and not timed_path('/mcpx')
