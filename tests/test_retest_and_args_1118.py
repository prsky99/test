"""PM 11-18 15:2x (09:12 pearl run diagnosis): wrong-tool members stop coming back as retests, and role task inputs
reach array and owner/repo parameters (Antigravity W2 role_tool_test, reviewed by 검색과 RAG)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_v2 as V  # noqa: E402
from scripts.role_tool_test import case_arguments  # noqa: E402


def version(rid, role, tool, score):
    return {'resource_id': rid, 'role': role, 'tool': tool, 'quality': {'score': score}, 'tested': 1}


def test_a_member_the_name_rule_no_longer_takes_and_scoring_low_is_not_retested():
    off = V.off_role_members([
        version(1, 'stock.quote.v1', 'get_quote_of_the_day', 7.0),      # off the rule, 7 points: out
        version(2, 'web.grounding.v1', 'serp_live_search', 88.0),       # off the rule but 88 (queued by hand): stays
        version(3, 'weather.forecast.v1', 'get_forecast', 7.0),          # the rule takes it: stays (retests decide)
    ])
    assert (1, 'stock.quote.v1', 'get_quote_of_the_day') in off
    assert (2, 'web.grounding.v1', 'serp_live_search') not in off
    assert (3, 'weather.forecast.v1', 'get_forecast') not in off


def test_the_best_score_of_a_member_counts():
    off = V.off_role_members([version(1, 'stock.quote.v1', 'quote_x', 7.0), version(1, 'stock.quote.v1', 'quote_x', 75.0)])
    assert not off


def tool(required, params):
    return {'name': 't', 'required': required, 'params': params}


def test_a_string_reaches_an_array_parameter():
    args, missing = case_arguments(tool(['symbols'], {'symbols': {'type': 'array', 'items': {'type': 'string'}}}),
                                   {'symbol': 'AAPL'})
    assert args == {'symbols': ['AAPL']} and not missing


def test_owner_and_repo_come_from_one_slug():
    args, missing = case_arguments(tool(['owner', 'repo'], {'owner': {'type': 'string'}, 'repo': {'type': 'string'}}),
                                   {'repo': 'psf/requests'})
    assert args == {'owner': 'psf', 'repo': 'requests'} and not missing


def test_a_search_word_never_fills_an_id():
    # review 11-18: 'query' -> '^id$' was left out of the W2 diff; a name is no record id
    args, missing = case_arguments(tool(['id'], {'id': {'type': 'string'}}), {'query': 'Lazarus Group'})
    assert 'id' not in args and missing == ['id']


def _case(case_id):
    import json
    for name in ('role-tasks-v1.jsonl', 'role-tasks-rag-v1.jsonl'):
        path = Path(__file__).resolve().parents[1] / 'agent_market' / 'necklaces' / 'role_tasks' / name
        for line in path.read_text().splitlines():
            case = json.loads(line)
            if case['case_id'] == case_id:
                return case
    raise KeyError(case_id)


def test_a_search_box_takes_the_company_name_not_its_domain():
    # PM 11-18 15:4x: company-apple and company-microsoft list domain before name
    search = tool(['query'], {'query': {'type': 'string'}})
    for case_id in ('company-apple', 'company-microsoft'):
        case = _case(case_id)
        args, _ = case_arguments(search, case['input'])
        assert args['query'] == case['input']['name'], (case_id, args)
    # a domain parameter still takes the domain
    args, _ = case_arguments(tool(['domain'], {'domain': {'type': 'string'}}), _case('company-apple')['input'])
    assert args['domain'] == _case('company-apple')['input']['domain']
