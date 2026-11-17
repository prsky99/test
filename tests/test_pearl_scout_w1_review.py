"""Pearl scout W1 review (검색과 RAG, PM 11-17): the four test errors confirmed against the stored versions.

TLS and DNS answers that were accurate stayed at 80 (no required output for the role), every San Francisco concert list
failed a 'published within 60 days' check, the MCP Registry case gave the expected name in its input (not checkable),
and a mail-auth task's own 'type': 'TXT' was dropped as an option.
"""
import datetime as dt
import json
import time

from agent_market.necklaces import role_tasks
from scripts import data_quality as DQ
from scripts.role_tool_test import case_arguments


def test_tls_and_dns_answers_have_required_output():
    tls = {'host': 'github.com', 'issuer': 'Sectigo Limited', 'expires': '2027-01-27T23:59:59+00:00', 'days_left': 71}
    points, _, fields, detail = DQ.completeness(json.dumps(tls), tls, 'tls.certificate.v1')
    assert points == DQ.WEIGHTS['completeness'] and fields == 2 and detail == 'required output present'
    dns = {'domain': 'github.com', 'checks': [{'id': 'spf', 'status': 'pass'}]}
    assert DQ.completeness(json.dumps(dns), dns, 'dns.mail_auth.v1')[3] == 'required output present'
    records = {'MX': ['0 github-com.mail.protection.outlook.com.'], 'TXT': ['"v=spf1 include:_spf.google.com ~all"']}
    assert DQ.completeness(json.dumps(records), records, 'dns.mail_auth.v1')[3] == 'required output present'
    assert DQ.completeness('{"host": "x.org"}', {'host': 'x.org'}, 'tls.certificate.v1')[3] == 'missing issuer, expires'
    # A text answer is still judged by the role's own fact checks.
    assert DQ.completeness('valid until 2027-02-14, issued by GlobalSign', None, 'tls.certificate.v1')[0] is None


def _case(cid):
    every = role_tasks.load() + role_tasks.load(role_tasks.FILE.parent / 'role-tasks-rag-v1.jsonl')
    return next(c for c in every if c['case_id'] == cid)


def test_an_event_search_is_checked_for_dates_ahead():
    case = _case('events-san-francisco')
    assert 'published_within_days' not in case['expect'] and case['expect']['upcoming_within_days'] == 120
    now = time.time()
    soon = (dt.datetime.fromtimestamp(now) + dt.timedelta(days=30)).strftime('%Y-%m-%d')
    later = (dt.datetime.fromtimestamp(now) + dt.timedelta(days=400)).strftime('%Y-%m-%d')
    past = (dt.datetime.fromtimestamp(now) - dt.timedelta(days=30)).strftime('%Y-%m-%d')
    items = lambda day: {'items': [{'title': 'SF Symphony', 'date': day, 'venue': 'Davies Hall, San Francisco'}]}
    assert DQ.upcoming_within(json.dumps(items(soon)), items(soon), 120, now)
    assert not DQ.upcoming_within(json.dumps(items(later)), items(later), 120, now)
    assert not DQ.upcoming_within(json.dumps(items(past)), items(past), 120, now)
    points, source, reasons = DQ.accuracy(case, json.dumps(items(soon)), items(soon), role_tasks=role_tasks)
    assert points == DQ.WEIGHTS['accuracy'], reasons
    points, _, reasons = DQ.accuracy(case, json.dumps(items(past)), items(past), role_tasks=role_tasks)
    assert points == 0 and any('next 120 days' in r for r in reasons)


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
