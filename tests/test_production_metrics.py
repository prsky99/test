"""PM 11-18: the daily production line, counted from files and code (a temporary root, no site request)."""
import json
from datetime import datetime, timedelta, timezone

from agent_market.concierge import pearl_badge as pb
from scripts import production_metrics as pm
from tests.test_necklace_surface import necklace, iso

NOW = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)          # 09:00 KST on 11-19


def build(tmp_path, with_live=True):
    root = tmp_path
    base = root / 'agent_market/necklaces'
    (base / 'drafts').mkdir(parents=True); (base / 'definitions').mkdir()
    (root / 'gateway-data/necklaces/runs').mkdir(parents=True); (root / 'gateway-data/pearls').mkdir(parents=True)
    (base / 'drafts/a.json').write_text('{}'); (base / 'drafts/b.json').write_text('{}')
    for name, status in (('c1', 'candidate'), ('c2', 'candidate'), ('p1', 'preview'), ('l1', 'live'), ('x', 'weird')):
        (base / 'definitions' / (name + '.json')).write_text(json.dumps({'status': status}))
    (base / 'definitions/broken.json').write_text('{not json')
    entries = [necklace('topic-evidence-brief', gate_passed_at=iso(NOW - timedelta(hours=2)),
                        quality={'delta_pp': 10, 'tested_at': iso(NOW - timedelta(hours=1))}) if with_live else None,
               necklace('website-trust', status='preview', gate_passed_at=None,
                        preview={'note': 'Preview — test runs in progress', 'gate_passed': False}, quality=None)]
    (root / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps(
        {'schema': 'agentcon-necklaces-v1', 'generated_at': iso(NOW), 'necklaces': [e for e in entries if e], 'events': []}))
    rows = [{'role': 'a.b.v1', 'level': 'final', 'passed': 3, 'of': 3, 'days': 2, 'last_checked': '2026-11-18', 'resource_id': 1},
            {'role': 'a.b.v1', 'level': 'verified', 'passed': 3, 'of': 3, 'days': 2, 'last_checked': '2026-11-18', 'resource_id': 2},
            {'role': 'c.d.v1', 'level': 'verified', 'passed': 3, 'of': 3, 'days': 2, 'last_checked': '2026-11-18', 'resource_id': 2}]
    (root / 'gateway-data/pearls/public-pearls.json').write_text(json.dumps({'schema': pb.SCHEMA, 'generated': '2026-11-18T09:20:00+09:00', 'pearls': rows}))
    events = [{'at': '2026-11-18T03:00:00Z', 'slug': 's', 'source': 'external', 'origin': 'x', 'outcome': 'succeeded', 'run_id': 'r1'},
              {'at': '2026-11-18T04:00:00Z', 'slug': 's', 'source': 'external', 'origin': 'x', 'outcome': 'failed', 'run_id': 'r2'},
              {'at': '2026-11-18T05:00:00Z', 'slug': 's', 'source': 'internal', 'origin': 'x', 'outcome': 'succeeded', 'run_id': 'r3'},
              {'at': '2026-11-18T06:00:00Z', 'slug': 's', 'source': 'external', 'origin': 'x', 'outcome': 'succeeded', 'run_id': 'r1'}]
    (root / 'gateway-data/necklaces/runs/20261118.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n')
    return root


def test_the_line_counts_open_and_preview_pearls_stages_and_external_successes(tmp_path):
    root = build(tmp_path)
    m = pm.collect(root, now=NOW)
    assert (m['necklaces_open'], m['necklaces_preview']) == (1, 1)
    assert m['stages'] == {'draft': 2, 'candidate': 2, 'preview': 1, 'live': 1}      # a weird status and a broken file are not counted
    assert (m['pearls_final'], m['pearls_verified']) == (1, 2) and m['pearl_jobs'] == 2 and m['pearl_agents'] == 2
    assert m['external_runs_day'] == '2026-11-18'                                    # yesterday in KST
    assert (m['external_runs_succeeded'], m['external_runs']) == (1, 2)             # the replayed r1, the internal run, not counted
    assert pm.line(m).startswith('2026-11-19 09:00 KST | necklaces open 1, preview 1 | pearls final 1, verified 2 (2 jobs, 2 agents)')
    assert 'stages draft 2 > candidate 2 > preview 1 > live 1 | external necklace runs 2026-11-18: 1 succeeded of 2' in pm.line(m)


def test_no_live_necklace_and_missing_files_give_zeros_not_errors(tmp_path):
    root = build(tmp_path, with_live=False)
    assert pm.collect(root, now=NOW)['necklaces_open'] == 0
    empty = pm.collect(tmp_path / 'nothing', now=NOW)
    assert (empty['necklaces_open'], empty['necklaces_preview'], empty['pearls_final'], empty['external_runs_succeeded']) == (0, 0, 0, 0)
    assert empty['stages'] == {'draft': 0, 'candidate': 0, 'preview': 0, 'live': 0}


def test_write_keeps_one_line_per_day_and_the_run_names_no_site(tmp_path, monkeypatch):
    root = build(tmp_path)
    m = pm.collect(root, now=NOW)
    pm.write(root, m)
    pm.write(root, dict(m, necklaces_open=5))                                        # the same day again replaces its line
    later = dict(m, at='2026-11-20 09:00 KST')
    pm.write(root, later)
    lines = (root / 'logs/ops/production-daily.jsonl').read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])['necklaces_open'] == 5 and json.loads(lines[1])['at'].startswith('2026-11-20')
    import socket
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')))
    pm.collect(root, now=NOW)                                                          # reading files needs no connection


def add_pearls(root, rows):
    path = root / 'gateway-data/pearls/public-pearls.json'
    data = json.loads(path.read_text())
    data['pearls'] += rows
    path.write_text(json.dumps(data))


def prow(agent, role, level='verified', **extra):
    return {'resource_id': agent, 'role': role, 'level': level, 'passed': 3, 'of': 3, 'days': 1, 'last_checked': '2026-11-19',
            'terms': 'silent', **extra}


def test_goals_start_with_a_baseline_then_count_new_pearls_and_necklaces_and_carry_the_shortfall(tmp_path):
    root = build(tmp_path)
    day1, day2, day3 = '2026-11-19', '2026-11-20', '2026-11-21'
    first = pm.collect(root, day=day1, now=NOW)
    assert first['goals'] is None and 'baseline not set yet' in pm.line(first)         # nothing is called "new" before a baseline
    pm.write(root, first)                                                              # the first --write sets the baseline
    state = json.loads((root / 'logs/ops/production-state.json').read_text())
    assert set(state['pearls'].values()) == {'baseline'} and len(state['pearls']) == 3 and state['necklaces']['topic-evidence-brief'] == 'baseline'
    # day 2: 5 new pearls (one needs a direct connection: left out), a repeat of an old pair is not new
    add_pearls(root, [prow(10 + i, 'x.y.v1') for i in range(5)] + [prow(99, 'x.y.v1', terms='prohibits', ), prow(1, 'a.b.v1')])
    # the 'direct' flag is derived from terms prohibits by the public list; one more necklace opens
    second = pm.collect(root, day=day2, now=NOW)
    g = second['goals']
    assert (g['new_pearls'], g['pearl_target'], g['pearl_shortfall'], g['pearl_carry_in'], g['pearl_carry_out']) == (5, 24, 19, 0, 19)
    assert (g['new_necklaces'], g['necklace_shortfall'], g['necklace_carry_out']) == (0, 3, 3)
    assert 'new pearls 5 of 24 (short 19, carried in 0, carried on 19)' in pm.line(second)
    pm.write(root, second)
    pm.write(root, pm.collect(root, day=day2, now=NOW))                                # the same day again changes nothing
    assert json.loads((root / 'logs/ops/production-state.json').read_text())['days'][day2]['new_pearls'] == 5
    # day 3: the shortfall of 19 pearls and 3 necklaces is added to the target; 30 new pearls beat 24 + 19 only in part
    add_pearls(root, [prow(100 + i, 'z.w.v1') for i in range(30)])
    third = pm.collect(root, day=day3, now=NOW)['goals']
    assert (third['new_pearls'], third['pearl_carry_in'], third['pearl_shortfall'], third['pearl_carry_out']) == (30, 19, 0, 13)
    assert third['necklace_carry_in'] == 3 and third['necklace_carry_out'] == 6 and third['necklace_target'] == 3
