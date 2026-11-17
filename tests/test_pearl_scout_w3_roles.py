"""Pearl scout W3 review (검색과 RAG with the workflow team, PM 11-17): six new roles a necklace draft or plan uses.

Each role task's expectation is a fact its public source states (re-read 11-17), never only the input's own words,
and the tool-name patterns leave out the wrong tools the Antigravity patterns matched in the grade A snapshot.
"""
import re

from agent_market.necklaces import role_tasks
from scripts import role_catalog

NEW = ('sanctions.screen.v1', 'court.case.v1', 'cve.epss.v1', 'http.headers.v1', 'email.deliverability.v1',
       'wikidata.entity.v1')


def _cases():
    return [c for c in role_tasks.load(role_tasks.FILE.parent / 'role-tasks-rag-v1.jsonl') if c['role'] in NEW]


def test_every_new_role_has_tasks_that_check_a_fact():
    cases = _cases()
    assert {c['role'] for c in cases} == set(NEW) and len(cases) == 16
    for case in cases:
        assert role_tasks.fact_checks(case) >= 1, case['case_id']
        assert case['truth_sources'] and case['truth_sources'][0].get('confirmed') is True


def test_the_patterns_keep_the_right_tools_and_leave_out_the_wrong_ones():
    match = lambda role, name: bool(re.match(role_catalog.ROLES[role]['tools'], name, re.I))
    assert match('sanctions.screen.v1', 'screen_sanctions') and match('sanctions.screen.v1', 'sanctions_screen_name')
    assert not match('sanctions.screen.v1', 'screen_address') and not match('sanctions.screen.v1', 'screen_agent_wallet')
    assert not match('sanctions.screen.v1', 'screen_sanctions_wallet')
    assert match('court.case.v1', 'courtlistener_search_opinions') and not match('court.case.v1', 'courtlistener_get_judge')
    assert match('cve.epss.v1', 'get_epss_score') and not match('cve.epss.v1', 'get_epss_movers')
    assert not match('cve.epss.v1', 'kev_by_vendor')
    assert match('http.headers.v1', 'check_security_headers') and match('email.deliverability.v1', 'check_mx')
    assert match('wikidata.entity.v1', 'wikidata_get_entity') and not match('wikidata.entity.v1', 'get_entity_record')


def test_a_generic_word_no_longer_passes_a_task():
    cloud = next(c for c in _cases() if c['case_id'] == 'email-mx-cloudflare-com')
    assert role_tasks.score(cloud, 'MX records for cloudflare.com: 10 mxa.global.inbound.cf-emailsecurity.net')[0]
    assert not role_tasks.score(cloud, 'MX lookup done for cloudflare.com, status ok')[0]   # 'MX' alone passed before
    epss = next(c for c in _cases() if c['case_id'] == 'epss-log4shell')
    assert not role_tasks.score(epss, 'CVE-2021-44228 epss percentile available')[0]
    assert role_tasks.score(epss, 'CVE-2021-44228: EPSS 0.99999 (percentile 1.0)')[0]
