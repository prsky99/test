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
    monkeypatch.setattr(gold_check, 'role_task_check', lambda ids, agents: {ids[0]: {'passed': 0, 'cases': 0}})
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
