"""Ops gate for self-made substitutes (deploy/NECKLACE_GATE.md section 10): answerable cases only, contract inputs required."""
import json

from scripts import substitute_gate as gate


def write(root, slug, split, cases):
    folder = root / 'gateway-data/necklaces/gold' / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{split}.jsonl').write_text('\n'.join(json.dumps(c) for c in cases))


def test_held_out_takes_answerable_cases_and_fills_from_the_next_round(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    case = lambda i, cik: {'case_id': f'c{i}', 'input': {}, 'truth': {'cik': cik, 'lei': None}}
    write(tmp_path, 'company-due-diligence', 'holdout-r1', [case(i, '1' if i % 5 else None) for i in range(30)])
    write(tmp_path, 'company-due-diligence', 'holdout-r2', [case(100 + i, '2') for i in range(30)])
    first = gate.held_out('sec-edgar', 'holdout-r1')
    assert len(first) == 24 and all(c['truth']['cik'] for c in first)
    filled = gate.held_out('sec-edgar', 'holdout-r1', 'holdout-r2')
    assert len(filled) == 30 and [c['split'] for c in filled].count('holdout-r2') == 6
    assert gate.held_out('gleif-lei', 'holdout-r1', 'holdout-r2') == []     # no LEI anywhere: nothing to call


def test_a_re_judgement_skips_seen_cases_and_fills_from_two_rounds(tmp_path, monkeypatch):
    """PM 11-15 14:34: after a fix the cases already seen are left out; the rest comes from rounds 2 and 3 in order."""
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    case = lambda i: {'case_id': f'c{i}', 'input': {}, 'truth': {'cik': str(i), 'lei': None}}
    write(tmp_path, 'company-due-diligence', 'holdout-r1', [case(i) for i in range(20)])
    write(tmp_path, 'company-due-diligence', 'holdout-r2', [case(100 + i) for i in range(10)])
    write(tmp_path, 'company-due-diligence', 'holdout-r3', [case(200 + i) for i in range(25)])
    seen = frozenset(('sec-filings', f'c{i}') for i in list(range(15)) + [100, 101, 102])
    cases = gate.held_out('sec-filings', 'holdout-r1', 'holdout-r2,holdout-r3', exclude=seen)
    splits = [c['split'] for c in cases]
    assert len(cases) == 30 and splits.count('holdout-r1') == 5 and splits.count('holdout-r2') == 7
    assert splits.count('holdout-r3') == 18 and not any(('sec-filings', c['case_id']) in seen for c in cases)


def test_a_source_short_of_cases_is_not_called(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(gate.time, 'localtime', lambda *a: __import__('time').struct_time((2026, 11, 14, 8, 20, 0, 5, 318, 0)))
    write(tmp_path, 'company-due-diligence', 'holdout-r1', [{'case_id': 'a', 'input': {}, 'truth': {'lei': 'X'}}])
    monkeypatch.setattr(gate, 'reserve_calls', lambda *a: (_ for _ in ()).throw(AssertionError('no reservation')))
    assert gate.main(['gleif-lei']) == 76
    assert json.loads(capsys.readouterr().out)['answerable'] == {'gleif-lei': 1}


def test_the_gate_never_starts_in_a_measurement_window(monkeypatch, capsys):
    monkeypatch.setattr(gate.time, 'localtime', lambda *a: __import__('time').struct_time((2026, 11, 14, 8, 57, 0, 5, 318, 0)))
    assert gate.main(['sec-edgar']) == 75 and json.loads(capsys.readouterr().out)['reason'] == 'measurement_window'


def test_run_maps_gold_inputs_like_the_tuning_runs(tmp_path, monkeypatch):
    """11-15 08:16: cutting the input to the contract fields dropped 'topic', so all 30 Wikipedia cases had no title."""
    from agent_market.fallback_agents import gold_check
    from agent_market.fallback_agents.gold_check import SLUG
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    write(tmp_path, SLUG['wikipedia-summary'], 'holdout-r2',
          [{'case_id': f'w{i}', 'input': {'topic': f'Topic {i}', 'audience': 'x'}, 'truth': {}} for i in range(3)])
    contract_inputs = tmp_path / 'contract.json'
    contract_inputs.write_text('{}')
    monkeypatch.setattr(gate, 'CONTRACT_INPUTS', contract_inputs)
    monkeypatch.setattr(gold_check, 'judge', lambda agent, case, result: {'pass': True})
    monkeypatch.setattr(gold_check, 'role_task_check', lambda ids, agents, before_call=None: {ids[0]: {'passed': 0, 'cases': 0}})
    calls = []

    class Agents:
        def execute(self, agent_id, arguments):
            calls.append(arguments)
            return {'result': {}}
    gate.run(['wikipedia-summary'], 'holdout-r2', tmp_path / 'raw.jsonl', agents=Agents(),
             exclude={('wikipedia-summary', 'w1')})
    assert calls == [gold_check.case_arguments('wikipedia-summary', {'input': {'topic': 'Topic 0', 'audience': 'x'}}),
                     gold_check.case_arguments('wikipedia-summary', {'input': {'topic': 'Topic 2', 'audience': 'x'}})]
    assert all(c.get('title', '').startswith('Topic ') for c in calls)


def test_used_cases_from_raw_files_are_skipped(tmp_path):
    raw = tmp_path / 'raw.jsonl'
    raw.write_text('\n'.join([json.dumps({'agent': 'gleif-lei', 'case_id': 'g1'}), 'not json',
                              json.dumps({'agent': 'sec-edgar', 'case_id': 's1', 'envelope': None})]))
    assert gate.used_cases([raw]) == {('gleif-lei', 'g1'), ('sec-edgar', 's1')}
    assert gate.used_cases([]) == set()


def test_reservations_count_calls_per_case_and_refuse_what_cannot_fit_a_day(monkeypatch):
    needed = gate.calls_needed(['gleif-lei', 'sec-edgar'], cases=30)
    assert needed == {'https://api.gleif.org/': 64, 'https://query.wikidata.org/': 34, 'https://data.sec.gov/': 34}
    import agent_market.provider_budget as budget
    taken = []
    monkeypatch.setattr(budget, 'reserve', lambda url, system, n=1, **k: (taken.append((url, system, n)) or (True, None)))
    refused = gate.reserve_calls(['gleif-lei'], cases=30)
    assert taken == [] and 'api.gleif.org' in next(iter(refused))     # 64 > 60: nothing reserved at all
    assert gate.reserve_calls(['sec-edgar'], cases=30) == {} and taken == [('https://data.sec.gov/', 'gate', 34)]
    assert gate.reserve_calls(['gleif-lei'], cases=20) == {}           # 2 x 20 + 4 = 44 fits


def test_a_verdict_split_over_two_days_is_judged_on_both_parts(tmp_path, monkeypatch, capsys):
    """PM 11-15 08:4x: GLEIF 15 cases a day (2 calls each), the two days together make the 30-case verdict."""
    from agent_market.fallback_agents import gold_check
    from agent_market.fallback_agents.gold_check import SLUG
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(gate, 'SUBSTITUTE_CASES', 4)
    monkeypatch.setattr(gate, 'NEED', 4)
    write(tmp_path, SLUG['gleif-lei'], 'holdout-r3',
          [{'case_id': f'g{i}', 'input': {'name': f'Co {i}'}, 'truth': {'lei': f'L{i}'}} for i in range(6)])
    contract_inputs = tmp_path / 'contract.json'
    contract_inputs.write_text(json.dumps({'gleif-lei': [[{'name': 'x'}, 'ok']]}))
    monkeypatch.setattr(gate, 'CONTRACT_INPUTS', contract_inputs)
    monkeypatch.setattr(gold_check, 'judge', lambda agent, case, result: {'pass': True})
    monkeypatch.setattr(gold_check, 'role_task_check', lambda ids, agents, before_call=None: {ids[0]: {'passed': 1, 'cases': 1}})
    monkeypatch.setattr(gate, 'quality', lambda envelope: [])
    reserved = []
    monkeypatch.setattr(gate, 'reserve_calls', lambda ids, cases=None: reserved.append(cases) or {})
    called = []

    class Agents:
        def execute(self, agent_id, arguments):
            called.append(arguments.get('name'))
            return {'result': {}}
    import agent_market.fallback_agents.agents as agents_module
    monkeypatch.setattr(agents_module, 'FallbackAgents', Agents)
    monkeypatch.setattr(gate.time, 'localtime', lambda *a: __import__('time').struct_time((2026, 11, 16, 8, 20, 0, 0, 320, 0)))
    monkeypatch.setattr(gate.time, 'strftime', lambda fmt, *a: '20261116-0820')
    assert gate.main(['gleif-lei', '--split', 'holdout-r3', '--limit', '2']) == 0
    first = json.loads((tmp_path / 'out/verdict-holdout-r3-20261116-0820.json').read_text())['agents']['gleif-lei']
    assert first['answer_set'] == '2/2' and first['part'] == {'earlier_rows': 0, 'this_part': 2, 'complete': False}
    assert first['pass'] is False and 'held_out_cases' in first['missing'] and reserved == [2]
    part1 = tmp_path / 'part1.json'
    (tmp_path / 'out/verdict-holdout-r3-20261116-0820.json').rename(part1)
    capsys.readouterr()
    assert gate.main(['gleif-lei', '--split', 'holdout-r3', '--limit', '2', '--continue-from', str(part1)]) == 0
    # the first part's raw file still holds 0820, so this run in the same minute writes 0820-2 and replaces nothing
    assert (tmp_path / 'out/raw-holdout-r3-20261116-0820.jsonl').exists()
    second = json.loads((tmp_path / 'out/verdict-holdout-r3-20261116-0820-2.json').read_text())['agents']['gleif-lei']
    assert second['answer_set'] == '4/4' and second['part'] == {'earlier_rows': 2, 'this_part': 2, 'complete': True}
    assert second['pass'] is True and second['missing'] == [] and reserved == [2, 2]
    assert called == ['Co 0', 'Co 1', 'x', 'Co 2', 'Co 3', 'x']          # no case runs twice


def test_every_fallback_agent_has_a_domain_entry():
    """R30 (PM 11-15): the gate reserves calls for all 29 agents, one URL per registrable domain."""
    from agent_market.fallback_agents.catalog import SPECS
    from agent_market.provider_budget import domain
    from scripts import substitute_gate as G
    assert set(G.DOMAINS) == set(SPECS)
    for agent_id, urls in G.DOMAINS.items():
        assert len({domain(u) for u in urls}) == len(urls), agent_id


def test_pace_waits_outside_the_call_budget_for_slow_hosts():
    """Agent team 11-15: arXiv's 3 s spacing ate the 3.3 s budget when gate cases ran back to back."""
    import scripts.substitute_gate as gate
    from agent_market.fallback_agents.limits import limiters

    class Agents:
        def __init__(self):
            self.limiters = limiters()
    a, slept = Agents(), []
    gate.pace(a, "arxiv-search", slept.append)
    assert slept == [3.2]                                   # arXiv spacing 3 s + 0.2
    a.limiters["export.arxiv.org"].rest_until = a.limiters["export.arxiv.org"].clock() + 60   # after a 503
    gate.pace(a, "arxiv-search", slept.append)
    assert 59 <= slept[-1] <= 60.1
    gate.pace(a, "wikipedia-summary", slept.append)          # fast hosts are not paced
    assert len(slept) == 2
    gate.pace(a, "github-releases", slept.append)            # ops 11-15: 2 s between cases at least
    assert slept[-1] == 2.0


def test_role_tasks_are_paced_like_the_cases(monkeypatch, tmp_path):
    """ops 11-15 16:25: arxiv-search role tasks 0/3 right after the cases; each call now waits like the cases do."""
    from agent_market.fallback_agents import gold_check
    from agent_market.necklaces import role_tasks
    calls = []

    class Agents:
        def execute(self, agent_id, arguments):
            calls.append("call")
            raise gold_check.FallbackUnavailable("not_found", "x")
    tasks = [{"case_id": f"t{i}", "contract": "papers.search.v1", "input": {"query": "x"}} for i in range(2)]
    monkeypatch.setattr(role_tasks, "FILE", str(tmp_path / "role-tasks-v1.jsonl"))
    monkeypatch.setattr(role_tasks, "load", lambda *a, **k: [] if a else tasks)
    gold_check.role_task_check(["arxiv-search"], Agents(), before_call=lambda a: calls.append("pace:" + a))
    assert calls == ["pace:arxiv-search", "call", "pace:arxiv-search", "call"]
