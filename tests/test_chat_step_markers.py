"""PM 11-17: step_search counted the checks after the search (condition admission, relay, the auto_run offer,
the no-match answer), so a slower step_search could not say which part grew. Those parts get their own steps, and
user_slo keeps every step_* stage, not only the slowest eight.
"""
# ruff: noqa: F401,F811 -- reuse the isolated catalog fixture
import types

from scripts import user_slo
from tests.test_fast_single_recommendation import catalog


def _steps(response):
    timing = response.headers.get('server-timing', '')
    return {part.split(';')[0].strip() for part in timing.split(',') if part.strip().startswith('step_')}


def test_the_checks_after_the_search_have_their_own_steps(catalog):
    _, _, client, add, now = catalog
    add('Weather Forecasts', report_at=now - 10)
    found = client.post('/chat', json={'message': 'find an MCP weather forecast API'})
    assert found.status_code == 200 and found.json()['data']['recommendations']
    steps = _steps(found)
    assert {'step_search', 'step_admit', 'step_offer'} <= steps and 'step_no_match' not in steps
    empty = client.post('/chat', json={'message': 'find an MCP agent for quantum tea leaf reading'})
    assert empty.status_code == 200 and not empty.json()['data'].get('recommendations')
    assert 'step_no_match' in _steps(empty)


def test_user_slo_keeps_every_step_stage():
    timing = ('server;dur=1683, step_search;dur=1060, step_prepare;dur=591, prefetch_hit;dur=464, '
              'admission_loop;dur=351, ann;dur=253, projection;dur=198, semantic;dur=176, cpu;dur=150, '
              'lexical;dur=120, step_admit;dur=12, step_offer;dur=3, gc_all;dur=2')
    phases = user_slo._Phases()
    phases.dns_s = None
    stages = phases.summary(types.SimpleNamespace(headers={'server-timing': timing}))['stages']
    assert stages['step_admit'] == 12 and stages['step_offer'] == 3      # small, still kept
    assert stages['gc_all'] == 2 and 'lexical' not in stages             # other small stages stay out
