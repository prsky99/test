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
