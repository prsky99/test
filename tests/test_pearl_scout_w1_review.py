"""Pearl scout W1 review (검색과 RAG, PM 11-17): test errors confirmed against the stored versions (input side).

TLS and DNS answers that were accurate stayed at 80 (no required output for the role), every San Francisco concert list
failed a 'published within 60 days' check, the MCP Registry case gave the expected name in its input (not checkable),
and a mail-auth task's own 'type': 'TXT' was dropped as an option.
"""
import json

from agent_market.necklaces import role_tasks
from scripts import data_quality as DQ
from scripts.role_tool_test import case_arguments


def _case(cid):
    every = role_tasks.load() + role_tasks.load(role_tasks.FILE.parent / 'role-tasks-rag-v1.jsonl')
    return next(c for c in every if c['case_id'] == cid)


def test_the_mcp_registry_case_asks_for_a_name_it_does_not_give():
    case = _case('mcp-registry-agent-concierge')
    assert 'name' not in case['input'] and role_tasks.fact_checks(case) == 1
    found = {'servers': [{'name': 'biz.agentconcierge/agent-concierge', 'version': '1.0.0'}]}
    assert DQ.accuracy(case, json.dumps(found), found, role_tasks=role_tasks)[0] == DQ.WEIGHTS['accuracy']
    other = {'servers': [{'name': 'io.example/concierge'}]}
    assert DQ.accuracy(case, json.dumps(other), other, role_tasks=role_tasks)[0] == 0


def test_an_option_the_task_names_is_passed():
    lookup = {'name': 't', 'required': ['domain'], 'params': {'domain': {'type': 'string'}, 'type': {'type': 'string'},
                                                            'search_mode': {'type': 'string'}}}
    args, missing = case_arguments(lookup, {'domain': 'python.org', 'record_type': 'TXT', 'type': 'TXT'})
    assert args == {'domain': 'python.org', 'type': 'TXT'} and missing == []
    args, _ = case_arguments(lookup, {'domain': 'python.org'})
    assert args == {'domain': 'python.org'}                        # an option the task does not name stays unset
