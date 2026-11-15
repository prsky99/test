"""Pearl queue order (PM 11-15 13:53): roles whose next pearl opens a necklace come first, in the PM's order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_v2 as V  # noqa: E402
import role_tool_test as RT  # noqa: E402


def test_priority_roles_follow_the_pm_order_and_others_come_after():
    # PM 11-15 16:07: due diligence, topic brief, CVE, package risk, new necklaces, then website/time/holiday
    assert V.PRIORITY_ROLES[:3] == ('company.registry.v1', 'encyclopedia.summary.v1', 'sec.filings.v1')
    assert V.PRIORITY_ROLES[-3:] == ('website.ai_readiness.v1', 'timezone.time.v1', 'holiday.calendar.v1')
    candidates = [(role, i * 10 + n, 'tool', f'h{i}-{n}.example') for i, role in enumerate(
        ['weather.forecast.v1', 'holiday.calendar.v1', 'website.ai_readiness.v1', 'company.registry.v1']) for n in range(6)]
    out = V.new_queue([], candidates, limit=10, terms={})
    roles = [x['role'] for x in out]
    assert roles[:4] == ['company.registry.v1'] * V.PRIORITY_PICKS
    assert roles[4:8] == ['website.ai_readiness.v1'] * V.PRIORITY_PICKS
    assert roles[8] == 'holiday.calendar.v1'
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


def test_grade_b_trials_are_listed_not_counted(monkeypatch):
    monkeypatch.setattr(V, 'success_days', lambda rid, role, tool, now, ref=None: {1: 2, 2: 1}.get(rid, 0))
    trial = lambda rid, score: {'resource_id': rid, 'role': 'web.grounding.v1', 'tool': 'answer_question',
                                'quality': {'score': score}}
    out = V.grade_trials([trial(1, 90), trial(2, 88), trial(3, 60)], {1: 'B', 2: 'B', 3: 'B'})
    assert out['versions'] == 3
    assert [x['resource_id'] for x in out['reevaluate']] == [1, 2]
    assert [x['resource_id'] for x in out['passed_twice_not_a']] == [1]


def test_web_grounding_seeds_follow_the_pm_decision():
    import json
    seeds = json.loads((Path(__file__).resolve().parents[1] / 'reports/pearls-2026-11-14/role_candidates_1115.json').read_text())
    web = [s for s in seeds if V.canonical(s['role']) == 'web.grounding.v1']
    assert [s['id'] for s in web[:2]] == [276982, 36279]
    assert len([s for s in web if 'web search' in s.get('note', '')]) == 8
    assert len([s for s in web if s.get('grade') == 'B']) == 19


def test_build_queue_never_retests_a_member_whose_terms_prohibit(monkeypatch):
    monkeypatch.setattr(V, 'latest_versions', lambda: [])
    monkeypatch.setattr(V, 'retest_queue', lambda versions: [{'role': 'web.grounding.v1', 'id': 50972, 'kind': 'retest'},
                                                              {'role': 'web.grounding.v1', 'id': 7, 'kind': 'retest'}])
    monkeypatch.setattr(V, 'catalog_candidates', lambda: [])
    monkeypatch.setattr(V, 'member_terms', lambda: {50972: 'prohibits'})
    q = V.build_queue(seed_file='/nonexistent.json')
    assert [x['id'] for x in q] == [7]


def test_tool_names_that_were_left_out_now_reach_their_role():
    import role_catalog
    want = {'check_agent_readiness': 'website.ai_readiness.v1', 'list_public_holidays': 'holiday.calendar.v1',
            'convert_timezone': 'timezone.time.v1', 'resolve_company': 'company.registry.v1',
            'company_filings': 'sec.filings.v1', 'get_latest_news': 'news.search.v1',
            'osv_get_vulnerability': 'cve.record.v1', 'latest_kev': 'cve.exploited.v1'}
    for name, role in want.items():
        assert role in role_catalog.roles_for_tool(name), name
    assert role_catalog.roles_for_tool('get_booking_link') == [] and role_catalog.roles_for_tool('list_books') == []


def test_usable_pearls_leave_out_prohibited_members(monkeypatch):
    monkeypatch.setattr(V, 'success_days', lambda rid, role, tool, now, ref=None: 2)
    m = lambda rid, rank, score=90: {'resource_id': rid, 'tool': 't', 'rank': rank, 'score': score,
                                     'best_recent_score': score, 'recent_pass_rate': 1.0, 'stale': False, 'success_days': 2}
    ranked = {'a.v1': {'final_pearl': 1, 'members': [m(1, 1), m(2, 2)]},
              'b.v1': {'final_pearl': 3, 'members': [m(3, 1), m(4, 2, 60)]},
              'c.v1': {'final_pearl': 5, 'members': [m(5, 1)]}}
    versions = [{'resource_id': i, 'role': r, 'tool': 't', 'quality': {'score': 90}} for i, r in
                ((1, 'a.v1'), (3, 'b.v1'), (5, 'c.v1'))]
    out = V.usable_pearls(versions, ranked, terms={1: 'prohibits', 3: 'prohibits', 5: 'allowed'})
    assert out['verified_usable'] == 1 and [x['resource_id'] for x in out['verified_prohibited']] == [1, 3]
    assert out['final_usable'] == 1
    assert out['final_prohibited']['a.v1']['usable_first']['resource_id'] == 2
    assert out['final_prohibited']['a.v1']['usable_first']['final_pearl_by_itself'] is True
    assert out['final_prohibited']['b.v1']['usable_first']['final_pearl_by_itself'] is False
    assert out['roles_with_a_usable_final_pearl'] == 2


def test_provisional_members_follow_the_floor():
    now = 1_800_000_000
    def v(rid, score, ago=1, outcome='succeeded', acc=10, role='news.search.v1'):
        return {'resource_id': rid, 'role': role, 'tool': 't', 'outcome': outcome, 'tested': now - ago * V.DAY,
                'case_id': 'c', 'quality': {'score': score}, 'data_quality': {'accuracy': {'points': acc}, 'clean': {'points': 5}}}
    versions = [v(1, 72), v(2, 69), v(3, 90, ago=8), v(4, 95, acc=0), v(5, 88), v(6, 80), v(7, 99, outcome='failed'),
                v('avc:news', 90), v(8, 91, role='weather.forecast.v1')]
    status = {1: (1, 'A', 'healthy'), 5: (1, 'B', 'healthy'), 6: (0, 'A', 'down')}
    out = V.provisional_members(status, terms={5: 'prohibits'}, roles={'news.search.v1': ['topic-evidence-brief']},
                                now=now, versions=versions)
    role = out['roles']['news.search.v1']
    assert [m['resource_id'] for m in role['members']] == [1]
    assert {m['resource_id']: m['why_out'] for m in role['left_out']} == {5: 'terms prohibit', 6: 'not active'}
    assert [m['resource_id'] for m in role['own_fallbacks']] == ['avc:news']
    assert list(out['roles']) == ['news.search.v1'] and out['roles_with_a_member'] == 1
    assert V.provisional_members(None, terms={}, roles={'news.search.v1': []}, now=now,
                                 versions=versions)['roles']['news.search.v1']['members'] == []


def test_necklace_roles_read_the_definitions():
    roles = V.necklace_roles()
    assert 'topic-evidence-brief' in roles['web.grounding.v1'] and 'website-trust-brief' in roles['domain.lookup.v1']
