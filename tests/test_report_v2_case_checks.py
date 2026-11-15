"""Scorer fixes from the ops review (11-15 14:2x): case-aware judgement and contract-shaped completeness."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import data_quality as DQ  # noqa: E402
import report_v2 as V  # noqa: E402
from agent_market.necklaces import role_tasks  # noqa: E402


def rag_case(case_id):
    return next(c for c in role_tasks.load(V.RAG_TASKS) if c['case_id'] == case_id)


def test_an_lax_answer_is_judged_by_the_lax_case_not_by_incheon():
    lax = rag_case('airport-lax')
    text = "Los Angeles International Airport (LAX), Los Angeles, California, United States."
    j = V.judge('airport.lookup', text, lax['input'], lax)
    assert [c['check'] for c in j['checks']] == ['answer set airport-lax']
    assert j['passed'] == j['total'] == 1
    icn = rag_case('airport-icn')
    assert V.judge('airport.lookup', text, icn['input'], icn)['passed'] == 0


def test_without_a_case_the_catalog_checks_stay():
    j = V.judge('airport.lookup', 'Incheon International Airport', {'code': 'ICN'})
    assert [c['check'] for c in j['checks']] == ['Incheon'] and j['passed'] == 1


def test_generic_checks_stay_next_to_the_case_check():
    case = next(c for c in role_tasks.load() if c['role'] == 'news.search.v1')
    names = [c['check'] for c in V.judge('news.search', 'x', case['input'], case)['checks']]
    assert names == ['a date', 'a headline line', f"answer set {case['case_id']}"]


def test_contract_shaped_answers_are_judged_as_text():
    envelope = {'answer': 'Los Angeles International Airport (LAX)', 'url': 'https://example.org', 'source': 'x'}
    points, _, fields, detail = DQ.completeness(json.dumps(envelope), envelope, role='airport.lookup.v1')
    assert points is None and fields == 2 and 'contract text answer' in detail
    own = {'code': 'LAX', 'name': 'Los Angeles International'}
    assert DQ.completeness(json.dumps(own), own, role='airport.lookup.v1')[0] == DQ.WEIGHTS['completeness']
    for role in ('book.search.v1', 'domain.lookup.v1', 'sec.filings.v1'):
        assert DQ.completeness(json.dumps(envelope), envelope, role=role)[0] is None, role
    # a role whose contract has the fields keeps measuring them
    assert DQ.contract_text_answer('news.search.v1', {'answer': 'x', 'source': 'y'}) is False


def test_the_evaluator_version_moved():
    assert V.EVALUATOR_VERSION == 'dq-2026-11-15c'
