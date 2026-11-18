"""PM 11-18: the public pearl list the pages, Explore and cards read (agent_market/pearls_public)."""
import json
import os

from agent_market import pearls_public as P

SUMMARY = {'generated': '2026-11-17T20:17:22+0900', 'rules': {'pass_mark': 85, 'confirm_days': 2, 'evaluator_version': 'dq-x'}}


def _m(rid, score, days, tool='t', tested='2026-11-16 18:26', tasks=2, rate=1.0, outcome='succeeded'):
    return {'resource_id': rid, 'id': rid, 'tool': tool, 'score': score, 'best_recent_score': score, 'success_days': days,
            'tested': tested, 'recent_tasks': tasks, 'recent_pass_rate': rate, 'outcome': outcome}


GROUPS = {'roles': {
    'fx.rate.v1': {'domain': 'finance', 'final_pearl': 46160, 'provisional_pearl': 273045,
                   'members': [_m(273045, 90.0, 1), _m(46160, 91.0, 2, tasks=3, rate=2 / 3), _m(225022, 88.0, 2),
                               _m(300000, 86.0, 1), _m(300001, 70.0, 3), _m(300002, 95.0, 2, outcome='failed')]},
    'weather.forecast.v1': {'domain': 'weather', 'final_pearl': 225022, 'provisional_pearl': None,
                            'members': [_m(225022, 92.0, 2)]}}}


def test_levels_follow_the_official_counts():
    doc = P.build(SUMMARY, GROUPS, {46160: 'silent'})
    levels = {(p['resource_id'], p['role']): p['level'] for p in doc['pearls']}
    assert levels == {(273045, 'fx.rate.v1'): 'provisional', (46160, 'fx.rate.v1'): 'final',
                      (225022, 'fx.rate.v1'): 'verified', (225022, 'weather.forecast.v1'): 'final'}
    # 300000 (85+ one day, not the role's provisional pearl), 300001 (below 85) and 300002 (failed) are not listed
    fx = next(p for p in doc['pearls'] if p['resource_id'] == 46160)
    assert fx == {'resource_id': 46160, 'role': 'fx.rate.v1', 'label': 'Fx rate', 'field': 'finance', 'level': 'final',
                  'final': True, 'tool': 't', 'score': 91.0, 'passed': 2, 'of': 3, 'days': 2,
                  'last_checked': '2026-11-16', 'terms': 'silent', 'words': 'fx rate t'}
    assert doc['schema'] == P.SCHEMA and doc['evaluator_version'] == 'dq-x'
    assert doc['by_resource']['225022'] == {'level': 'final', 'roles': ['fx.rate.v1', 'weather.forecast.v1']}
    assert doc['by_resource']['273045']['level'] == 'provisional'


def test_badges_use_final_and_verified_only(tmp_path):
    target = tmp_path / 'p.json'
    P.write(SUMMARY, GROUPS, target=target)
    assert P.pearl_of(46160, target)['level'] == 'final'
    assert P.pearl_of(273045, target) is None          # provisional: listed, no badge
    assert P.pearl_of(1, target) is None


def test_missing_or_malformed_file_means_no_pearls(tmp_path):
    assert P.load(tmp_path / 'none.json') == {'pearls': [], 'by_resource': {}}
    bad = tmp_path / 'bad.json'
    bad.write_text('{"schema": "other", "pearls": []}')
    assert P.load(bad) == {'pearls': [], 'by_resource': {}}
    bad.write_text('not json')
    os.utime(bad, (1, 1))
    assert P.load(bad) == {'pearls': [], 'by_resource': {}}


def test_load_rereads_only_when_the_file_changes(tmp_path):
    target = tmp_path / 'p.json'
    P.write(SUMMARY, GROUPS, target=target)
    first = P.load(target)
    assert P.load(target) is first                     # cached by modification time
    P.write(SUMMARY, {'roles': {}}, target=target)
    os.utime(target, (first_time := target.stat().st_mtime + 5, first_time))
    assert P.load(target)['pearls'] == []


def test_the_file_lives_under_the_project_root_and_is_replaced_whole(tmp_path, monkeypatch):
    monkeypatch.delenv('PEARLS_PUBLIC_PATH', raising=False)      # set by tests/conftest.py for every other test
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    assert P.path() == tmp_path / 'gateway-data' / 'pearls' / 'public-pearls.json'
    assert P.write(SUMMARY, GROUPS) == 4
    assert json.loads(P.path().read_text())['schema'] == P.SCHEMA
    assert not list(P.path().parent.glob('*.tmp'))


def test_the_command_writes_from_the_official_exports(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('PEARLS_PUBLIC_PATH', raising=False)
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    final = tmp_path / 'exports' / 'pearls' / 'final'
    final.mkdir(parents=True)
    (final / 'summary.json').write_text(json.dumps(SUMMARY))
    (final / 'role_groups.json').write_text(json.dumps(GROUPS))
    assert P.main(['write']) == 0 and '4 pearls' in capsys.readouterr().out
    assert P.main([]) == 2
