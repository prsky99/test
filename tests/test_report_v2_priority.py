"""Pearl queue order (PM 11-15 13:53): roles whose next pearl opens a necklace come first, in the PM's order."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_v2 as V  # noqa: E402
import role_tool_test as RT  # noqa: E402


def test_priority_roles_follow_the_pm_order_and_others_come_after():
    # PM 11-16 06:5x, today only: the necklace steps with no outside member first (undo 11-17 morning)
    assert V.PRIORITY_ROLES[:4] == ('sec.filings.v1', 'cve.exploited.v1', 'package.health.v1', 'website.ai_readiness.v1')
    # PM 11-15 16:13: topic brief, website and domain checks, then the roles only outside sources ask for
    assert V.PRIORITY_ROLES[4:7] == ('web.grounding.v1', 'papers.search.v1', 'news.search.v1')
    assert V.PRIORITY_ROLES[7:10] == ('weather.forecast.v1', 'fx.rate.v1', 'translate.text.v1')   # PM 16:42
    assert V.PRIORITY_ROLES[10:13] == ('dns.mail_auth.v1', 'domain.lookup.v1', 'tls.certificate.v1')
    assert len(V.PRIORITY_ROLES) == len(set(V.PRIORITY_ROLES))
    assert not {'holiday.calendar.v1', 'book.search.v1', 'earthquake.feed.v1'} & set(V.PRIORITY_ROLES)
    candidates = [(role, i * 10 + n, 'tool', f'h{i}-{n}.example') for i, role in enumerate(
        ['holiday.calendar.v1', 'company.registry.v1', 'weather.forecast.v1', 'news.search.v1']) for n in range(6)]
    out = V.new_queue([], candidates, limit=12, terms={})
    roles = [x['role'] for x in out]
    assert roles[:4] == ['news.search.v1'] * V.PRIORITY_PICKS
    assert roles[4:10] == ['weather.forecast.v1'] * 6          # all six (PRIORITY_EXTRA 8 a round)
    assert roles[10] == 'company.registry.v1'
    assert 'holiday.calendar.v1' not in roles[:11]


def test_dns_mail_auth_and_tls_roles_have_tools_and_checked_tasks():
    import role_catalog
    from agent_market.necklaces import role_tasks as RT
    for name in ('check_dmarc', 'spf_check', 'dns_lookup', 'dossier_dkim'):
        assert role_catalog.roles_for_tool(name) == ['dns.mail_auth.v1'], name
    for name in ('check_tls_certificate', 'ssl_check', 'get_certificate'):
        assert role_catalog.roles_for_tool(name) == ['tls.certificate.v1'], name
    assert role_catalog.roles_for_tool('birth-certificate') == []
    cases = {c['case_id']: c for c in V.role_tasks_rag()}
    assert RT.score(cases['dns-mail-python-org'], 'v=DMARC1; p=none; pct=100')[0]
    assert not RT.score(cases['dns-mail-github-com'], 'github.com has an SPF record')[0]
    assert RT.score(cases['tls-python-org'], 'Issuer: GlobalSign Atlas R3 DV TLS CA 2025 Q4')[0]
    assert all(c['truth_sources'][0]['confirmed'] and RT.fact_checks(c) for k, c in cases.items()
               if k.startswith(('dns-mail-', 'tls-')))
    assert V.short('dns.mail_auth.v1') == 'dns.mail_auth' and V.domain_of('tls.certificate.v1') == 'internet'


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
    # 11-16 06:3x: wingman research leads (terms read, PM 06:5x); 276982 stays listed but its terms prohibit it
    assert [s['id'] for s in web[:3]] == [41945, 276982, 36279]
    assert len([s for s in web if 'web search' in s.get('note', '')]) == 8
    assert len([s for s in web if s.get('grade') == 'B']) == 19


def test_build_queue_never_retests_a_member_whose_terms_prohibit(monkeypatch):
    monkeypatch.setattr(V, 'latest_versions', lambda: [])
    monkeypatch.setattr(V, 'retest_queue', lambda versions, skip=(): [{'role': 'web.grounding.v1', 'id': 50972, 'kind': 'retest'},
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
    ranked['d.v1'] = {'provisional_pearl': 6, 'members': [m(6, 1)]}
    ranked['e.v1'] = {'provisional_pearl': 7, 'members': [m(7, 1)]}
    out = V.usable_pearls(versions, ranked, terms={6: 'prohibits', 7: 'silent'})
    assert out['provisional_prohibited'] == [{'resource_id': 6, 'role': 'd.v1'}] and out['provisional_usable'] == 1


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


def test_weather_and_fx_get_more_picks_and_translation_names_are_wider():
    import role_catalog
    assert V.PRIORITY_EXTRA == {'weather.forecast.v1': 8, 'fx.rate.v1': 8}
    candidates = [(role, i * 100 + n, 't', f'h{i}-{n}.example') for i, role in
                  enumerate(('weather.forecast.v1', 'holiday.calendar.v1')) for n in range(12)]
    out = V.new_queue([], candidates, limit=9, terms={})
    assert [x['role'] for x in out] == ['weather.forecast.v1'] * 8 + ['holiday.calendar.v1']
    for name in ('translate.text', 'translate_lines', 'translator', 'translate_english_text'):
        assert role_catalog.roles_for_tool(name) == ['translate.text.v1'], name
    assert role_catalog.roles_for_tool('translate_bra_size') == []


def test_old_verdicts_are_rejudged_from_the_new_budget_in_demand_order(monkeypatch):
    v = lambda rid, role, score, ev='dq-2026-11-14b', outcome='succeeded': {
        'resource_id': rid, 'role': role, 'tool': 't', 'outcome': outcome, 'evaluator_version': ev, 'quality': {'score': score},
        'registrable_domain': f'd{rid}.example', 'host': f'd{rid}.example'}
    versions = [v(1, 'holiday.calendar.v1', 90), v(2, 'web.grounding.v1', 60), v(3, 'web.grounding.v1', 80),
                v(4, 'weather.forecast.v1', 70), v(5, 'papers.search.v1', 99, ev=V.EVALUATOR_VERSION),
                v(6, 'papers.search.v1', 50, outcome='failed'), v('avc:x', 'papers.search.v1', 90), v(7, 'news.search.v1', 70)]
    out = V.rejudge_queue(versions, already={(7, 'news.search.v1')}, terms={1: 'allowed'})
    # PM 11-16 17:5x: 85+ (or rank 1-3) first, so holiday 90 leads; then demand order
    assert [x['id'] for x in out] == [1, 3, 2, 4] and {x['kind'] for x in out} == {'rejudge'}
    assert len(V.rejudge_queue(versions, terms={}, limit=2)) == 2
    share = V.current_evaluator_share(versions)
    assert share == {'evaluator_version': V.EVALUATOR_VERSION, 'current': 1, 'of': 7}
    monkeypatch.setattr(V, 'latest_versions', lambda: versions)
    monkeypatch.setattr(V, 'retest_queue', lambda vs, skip=(): [])
    monkeypatch.setattr(V, 'rank', lambda vs: {})          # these short records carry no ranking fields
    monkeypatch.setattr(V, 'catalog_candidates', lambda: [('news.search.v1', 100 + n, 't', f'n{n}.example') for n in range(90)])
    monkeypatch.setattr(V, 'member_terms', lambda: {})
    q = V.build_queue(seed_file='/nonexistent.json')
    assert sum(x['kind'] == 'rejudge' for x in q) == 5 and sum(x['kind'] == 'new' for x in q) <= V.NEW_A_DAY - 5


def test_company_profile_names_reach_their_own_role_only():
    """PM 11-16: company.profile.v1 is its own contract; a profile tool is queued under it, not also as a registry."""
    import role_catalog
    for name in ('get_sec_company_profile', 'company_profile', 'get_company_profile', 'company_overview'):
        assert role_catalog.roles_for_tool(name) == ['company.profile.v1'], name
    for name in ('get_company', 'get_company_info', 'resolve_company', 'lookup_company'):
        assert role_catalog.roles_for_tool(name) == ['company.registry.v1'], name
