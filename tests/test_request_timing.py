"""Public recommendation requests carry Server-Timing stages (2026-11-10)."""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agent_market.concierge.request_timing import RequestTiming, timed_path
from agent_market.concierge.retrieval_metrics import stage


def _slow(request):
    from agent_market.concierge.chat_progress import step
    step('understand')
    step('search')
    with stage('exposure'):
        sum(range(1000))
    return JSONResponse({'ok': True}, headers={'Server-Timing': 'concierge;dur=1'})


def test_recommendation_paths_report_their_stages_and_others_do_not():
    app = Starlette(routes=[Route('/mcp', _slow, methods=['POST']), Route('/other', _slow)])
    app.add_middleware(RequestTiming)
    client = TestClient(app)
    timing = client.post('/mcp').headers['server-timing']
    assert timing.startswith('concierge;dur=1, server;dur=') and 'exposure;dur=' in timing
    assert 'step_understand;dur=' in timing and 'step_search;dur=' in timing
    assert client.get('/other').headers['server-timing'] == 'concierge;dur=1'
    assert timed_path('/a2a') and timed_path('/agents/best/data') and not timed_path('/mcpx')


def test_a_nested_capture_adds_its_stages_to_the_request():
    """search_quality.observed opens its own capture inside Explore; the request still sees the stages (11-11)."""
    from agent_market.concierge.retrieval_metrics import capture, stage
    with capture() as outer:
        with capture() as inner:
            with stage('ann'):
                pass
            with stage('relax'):
                pass
        assert set(inner['stages_ms']) == {'ann', 'relax'}
    assert {'ann', 'relax'} <= set(outer['stages_ms'])
