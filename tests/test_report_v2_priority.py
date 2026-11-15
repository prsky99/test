"""Pearl queue order (PM 11-15 13:53): roles whose next pearl opens a necklace come first, in the PM's order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_v2 as V  # noqa: E402
import role_tool_test as RT  # noqa: E402


def test_priority_roles_follow_the_pm_order_and_others_come_after():
    assert V.PRIORITY_ROLES[:3] == ('website.ai_readiness.v1', 'web.grounding.v1', 'timezone.time.v1')
    candidates = [(role, i * 10 + n, 'tool', f'h{i}-{n}.example') for i, role in enumerate(
        ['weather.forecast.v1', 'news.search.v1', 'holiday.calendar.v1', 'website.ai_readiness.v1']) for n in range(6)]
    out = V.new_queue([], candidates, limit=10, terms={})
    roles = [x['role'] for x in out]
    assert roles[:4] == ['website.ai_readiness.v1'] * V.PRIORITY_PICKS
    assert roles[4:8] == ['holiday.calendar.v1'] * V.PRIORITY_PICKS
    assert roles[8:10] == ['news.search.v1', 'news.search.v1'] or roles[8] == 'news.search.v1'
    assert 'weather.forecast.v1' not in roles[:9]


def test_timezone_case_gives_coordinates_to_point_tools_and_names_to_the_rest():
    case = next(c for c in V.role_tasks_rag() if c['case_id'] == 'time-new-york')
    point = {'params': {'lat': {'type': 'number'}, 'lng': {'type': 'number'}}, 'required': ['lat', 'lng']}
    assert RT.case_arguments(point, case['input']) == ({'lat': 40.7128, 'lng': -74.006}, [])
    named = {'params': {'timezone': {'type': 'string'}}, 'required': ['timezone']}
    assert RT.case_arguments(named, case['input']) == ({'timezone': 'America/New_York'}, [])


def test_terms_order_within_a_role_and_prohibited_members_never_queued():
    candidates = [('web.grounding.v1', rid, 'ask_web', f'h{rid}.example') for rid in (1, 2, 3, 4)]
    terms = {1: 'prohibits', 2: 'silent', 4: 'allowed'}
    out = V.new_queue([], candidates, limit=10, terms=terms)
    assert [x['id'] for x in out if x['role'] == 'web.grounding.v1'] == [4, 2, 3]


def test_grounding_tool_names_reach_the_web_role():
    import role_catalog
    for name in ('agent_clean_web_grounding', 'aitwire_grounding', 'ask_pipeworx_grounded', 'answer_question'):
        assert 'web.grounding.v1' in role_catalog.roles_for_tool(name), name
    assert 'web.grounding.v1' not in role_catalog.roles_for_tool('grounding')
