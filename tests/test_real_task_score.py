"""Real-task scorer (11-11): argument mapping, tool choice without writes, grading and failure causes."""
import json
import re
from pathlib import Path

from scripts import real_task_score as rts

TASKS = json.loads((Path(__file__).resolve().parents[1] / 'tests/data/real_tasks_30.json').read_text())['tasks']


def test_answer_set_has_thirty_tasks_with_compilable_checks():
    assert len(TASKS) == 30 and len({t['id'] for t in TASKS}) == 30
    assert sum(t['who'] == 'agent' for t in TASKS) == 15
    for t in TASKS:
        assert t['check']['all'] and all(re.compile(p) for p in t['check']['all'])
        assert set(t) >= {'needs', 'sample_input', 'must_return', 'fail_if', 'free_check'}


def test_arguments_follow_the_tool_schema():
    schema = {'type': 'object', 'properties': {'arxiv_id': {'type': 'string'}}, 'required': ['arxiv_id']}
    assert rts.arguments_for(schema, {'id': '1706.03762'}, 'x') == {'arxiv_id': '1706.03762'}
    schema = {'properties': {'q': {'type': 'string'}, 'limit': {'type': 'integer'}}, 'required': ['q']}
    assert rts.arguments_for(schema, {'query': 'rag', 'limit': '5'}, 'x') == {'q': 'rag', 'limit': 5}
    schema = {'properties': {'data': {'type': 'string'}}, 'required': ['data']}
    assert rts.arguments_for(schema, {'instance': {'b': 1}}, 'x') == {'data': '{"b": 1}'}


def test_write_tools_are_never_picked():
    tools = [{'name': 'delete_repo', 'description': 'github repository search'}, {'name': 'search_repos', 'description': 'search'}]
    assert rts.pick_tool(tools, 'repository search on GitHub', set())['name'] == 'search_repos'
    assert rts.pick_tool([{'name': 'send_email'}, {'name': 'create_order'}], 'email', set()) is None


def test_grading_and_failure_causes():
    task = {'check': {'all': [r'Example Domain']}}
    assert rts.checked(task, {'content': [{'text': 'Example Domain ...'}]})[0]
    assert not rts.checked(task, {'content': []})[0]
    assert rts.failure(200, {'error': {'data': {'error_code': 'UPSTREAM_PROTOCOL'}}}) == 'connection_failed'
    assert rts.failure(200, {'error': {'code': -32602, 'data': {'error_code': 'INVALID_ARGUMENTS'}}}) == 'call_failed'
    assert rts.failure(503, {}) == 'connection_failed'


def test_ops_auto_starts_the_score_once_a_night(tmp_path, monkeypatch):
    """11-11: the 10-minute watch starts the scorer once a day in the 04:00 local hour, never while busy."""
    import sys
    from datetime import datetime
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import ops_auto
    monkeypatch.setattr(ops_auto, 'REAL_TASK_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    monkeypatch.setattr(ops_auto, 'ROOT', tmp_path)
    (tmp_path / 'logs/ops').mkdir(parents=True)
    started = []
    launch = lambda cmd, **kw: started.append(cmd)  # noqa: E731
    at = lambda h: datetime(2026, 11, 12, h, 5).timestamp()  # noqa: E731
    monkeypatch.setattr(ops_auto, 'busy', lambda: None)
    # 11-12 PM: twice a day, night (04-05) and afternoon (15-17), through heavy_slot
    assert ops_auto.real_task_score(clock=lambda: at(13), launch=launch, free=True) is None and not started
    assert ops_auto.real_task_score(clock=lambda: at(4), launch=launch, free=True) == '2026-11-12|night'
    command = started[0]
    assert command[1:3] == ['-m', 'scripts.heavy_slot'] and command[command.index('--minutes') + 1] == '20'
    assert command[command.index('--') + 1:command.index('--') + 4] == ['nice', '-n', '10']
    assert command[-2:] == ['-m', 'scripts.real_task_score']
    assert ops_auto.real_task_score(clock=lambda: at(5), launch=launch, free=True) is None and len(started) == 1
    assert ops_auto.real_task_score(clock=lambda: at(15), launch=launch, free=False) is None and len(started) == 1
    assert ops_auto.real_task_score(clock=lambda: at(16), launch=launch, free=True) == '2026-11-12|afternoon'
    assert ops_auto.real_task_score(clock=lambda: at(17), launch=launch, free=True) is None and len(started) == 2
    (tmp_path / 'state.json').unlink()
    monkeypatch.setattr(ops_auto, 'busy', lambda: 'tests_or_deploy_running')
    assert ops_auto.real_task_score(clock=lambda: at(4), launch=launch, free=True) is None and len(started) == 2


def test_every_full_run_rewrites_the_latest_block_of_the_readme(tmp_path):
    report = {'summary': {'at': '2026-11-12T06:00:00+00:00', 'tasks': 3, 'passed': 1, 'score': 0.333,
                          'by_who': {'person': '1/2', 'agent': '0/1'}, 'causes': {'call_failed': 2}},
              'rows': [{'id': 'p01', 'outcome': 'pass'},
                       {'id': 'p02', 'outcome': 'call_failed', 'agent': {'name': 'Zaleso'}, 'detail': 'tools/call 403'},
                       {'id': 'a01', 'outcome': 'call_failed', 'agent': {'name': 'X'}, 'detail': 'a|b'}]}
    readme = tmp_path / 'README.md'
    readme.write_text('# 실제 과제 채점\n\n소개\n\n## 첫 기준 점수\n\n표\n')
    log = tmp_path / 'log.jsonl'
    log.write_text(json.dumps(report['summary']) + '\n')
    rts.update_readme(report, readme=readme, log=log)
    once = readme.read_text()
    assert once.index('## 최신 점수') < once.index('## 첫 기준 점수') and '**1 / 3 통과 (33%)**' in once
    assert '15:00 KST' in once and '| 호출 오류 call_failed | 2 | p02 Zaleso · tools/call 403; a01 X · a/b |' in once
    report['summary']['passed'] = 3
    rts.update_readme(report, readme=readme, log=log)
    twice = readme.read_text()
    assert twice.count('<!-- latest:start -->') == 1 and '**3 / 3 통과' in twice and '## 첫 기준 점수' in twice


def test_paid_or_sign_in_answers_count_as_failed():
    assert rts.paid_or_auth(0, 'Requires Team tier or above')
    assert rts.paid_or_auth(0, '{"error": "Invalid API key"}') and rts.paid_or_auth(402, '')
    assert rts.paid_or_auth(0, 'Please upgrade your plan to continue')
    assert not rts.paid_or_auth(0, 'Example Domain. This domain is for use in examples.')


def test_gateway_calls_are_paced_under_the_public_limit():
    rts._gateway_calls.clear()
    now = [0.0]; slept = []
    clock = lambda: now[0]  # noqa: E731
    def sleep(s):
        slept.append(s); now[0] += s
    for _ in range(rts.GATEWAY_PER_MINUTE + 1):
        rts.pace('https://agentconcierge.biz/api/gateway/mcp/1', clock=clock, sleep=sleep)
    assert slept and now[0] >= 60
    rts.pace('https://agentconcierge.biz/mcp', clock=clock, sleep=sleep)  # our own MCP endpoint is not paced
    assert len(slept) == 1
    rts._gateway_calls.clear()


def test_enum_values_and_aliases_follow_the_schema():
    schema = {'properties': {'target_format': {'type': 'string', 'enum': ['pdf', 'txt']}, 'source_url': {'type': 'string'}},
              'required': ['target_format']}
    assert rts.arguments_for(schema, {'url': 'https://x.test/a.pdf'}, 'convert PDF to text') == {
        'source_url': 'https://x.test/a.pdf', 'target_format': 'txt'}
    schema = {'properties': {'ecosystem': {'type': 'string', 'enum': ['npm', 'pypi']}, 'name': {'type': 'string'}}, 'required': ['ecosystem', 'name']}
    assert rts.arguments_for(schema, {'ecosystem': 'PyPI', 'package': 'requests'}, 'x')['ecosystem'] == 'pypi'
    schema = {'properties': {'value': {'type': ['string', 'object']}, 'schema': {'type': ['string', 'object']}}, 'required': ['value', 'schema']}
    assert set(rts.arguments_for(schema, {'schema': {'type': 'object'}, 'instance': {'b': 1}}, 'x')) == {'value', 'schema'}
    tools = [{'name': 'reverse_geocode', 'description': 'coordinates to address'}, {'name': 'geocode_address', 'description': 'address to coordinates'}]
    assert rts.pick_tool(tools, 'forward geocoding of an address', {'reverse_geocode'})['name'] == 'geocode_address'


def test_one_value_fills_a_plural_list_field():
    """11-11 p05/a05: check_cves {cves: [..]} and geocode_address {addresses: [..]} were called with {}."""
    from scripts.real_task_score import arguments_for
    cves = {'type': 'object', 'required': ['cves'], 'properties': {'cves': {'type': 'array', 'items': {'type': 'string'}}}}
    assert arguments_for(cves, {'cve': 'CVE-2024-3094'}, 'Is CVE-2024-3094 actively exploited?') == {'cves': ['CVE-2024-3094']}
    addresses = {'type': 'object', 'properties': {'addresses': {'type': 'array', 'items': {'type': 'string'}}}}
    assert arguments_for(addresses, {'address': '1600 Pennsylvania Avenue NW'}, 'Geocode') == {'addresses': ['1600 Pennsylvania Avenue NW']}
    plain = {'type': 'object', 'properties': {'address': {'type': 'string'}}}
    assert arguments_for(plain, {'address': 'x'}, 'Geocode') == {'address': 'x'}
