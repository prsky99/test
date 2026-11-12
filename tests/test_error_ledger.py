import json
from collections import Counter
from datetime import datetime

from scripts import error_ledger, ops_auto

DAY = '2026-11-11'
LOG = '\n'.join([
    '2026-11-10 23:59:59 ERROR agent_market.x: yesterday 1',
    '2026-11-11 10:00:01 ERROR agent_market.collector: health loop error for kinds=mcp',
    'Traceback (most recent call last):',
    '  File "x.py", line 1, in f',
    'agent_market.application_store_postgres.ApplicationStoreError: boom',
    '2026-11-11 10:00:02 INFO agent_market.y: fine',
    '2026-11-11 10:00:03 ERROR uvicorn.access: 1.2.3.4 - "POST /api/edge-gateway-internal/v1/public-prepare?x=1 HTTP/1.1" 503',
    '2026-11-11 10:00:04 WARNING agent_market.g: Execution failure reference=r1 resource_id=7 protocol=mcp code=UPSTREAM_TIMEOUT stage=gateway',
    '2026-11-11 10:00:05 WARNING agent_market.g: Execution failure reference=r2 resource_id=8 protocol=mcp code=UPSTREAM_TIMEOUT stage=gateway',
])


def test_from_logs_counts_one_day_by_cause(tmp_path):
    (tmp_path / 'service.a.log').write_text(LOG)
    counts = error_ledger.from_logs(DAY, tmp_path)
    assert counts['gateway|mcp|UPSTREAM_TIMEOUT|gateway'] == 2
    assert counts['log|a|uvicorn.access|POST /api/edge-gateway-internal/vN/public-prepare 503'] == 1
    assert counts['log|a|agent_market.collector|health loop error for kinds=mcp|'
                  'agent_market.application_store_postgres.ApplicationStoreError'] == 1
    assert sum(counts.values()) == 4          # the previous day and INFO lines are left out


def test_from_edge_reads_outcomes_and_survives_a_failed_read():
    assert error_ledger.from_edge(DAY, run=lambda q: 'error:timeout|3\norigin:admin:publish_failed|2\n') == \
        Counter({'edge|error:timeout': 3, 'edge|origin:admin:publish_failed': 2})

    def broken(_q):
        raise TimeoutError
    assert error_ledger.from_edge(DAY, run=broken) == Counter({'ledger|edge_unreadable|TimeoutError': 1})


def test_explained_only_by_a_reviewed_pattern(tmp_path):
    known = [{'pattern': r'^gateway\|mcp\|UPSTREAM_', 'reason': 'provider side', 'team': '검색과 RAG'}]
    result = error_ledger.ledger(DAY, counts=Counter({'gateway|mcp|UPSTREAM_TIMEOUT|gateway': 2, 'log|a|x|y': 1}),
                                 known=known)
    assert (result['total'], result['unexplained'], result['unexplained_kinds']) == (3, 1, 1)
    md = error_ledger.write(result, tmp_path).read_text()
    assert '설명되지 않음' in md and 'provider side (검색과 RAG)' in md
    assert json.loads((tmp_path / f'{DAY}.json').read_text())['unexplained'] == 1


def test_ops_auto_runs_once_then_hands_off_unexplained(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_auto, 'LEDGER_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'LEDGER_DIR', tmp_path)
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    launched = []
    early = datetime(2026, 11, 12, 0, 5).timestamp()
    assert ops_auto.error_ledger(clock=lambda: early, launch=lambda *a, **k: launched.append(a)) is None
    at = datetime(2026, 11, 12, 0, 30).timestamp()
    assert ops_auto.error_ledger(clock=lambda: at, launch=lambda *a, **k: launched.append(a)) == 'started'
    assert '--day' in launched[0][0] and DAY in launched[0][0]
    assert ops_auto.error_ledger(clock=lambda: at + 600, launch=lambda *a, **k: launched.append(a)) is None
    result = error_ledger.ledger(DAY, counts=Counter({'log|a|x|y': 4}), known=[])
    error_ledger.write(result, tmp_path)
    assert ops_auto.error_ledger(clock=lambda: at + 1200, launch=lambda *a, **k: launched.append(a)) == 'reported'
    assert handed and handed[0][0] == 'error_ledger' and '설명되지 않음 4건' in handed[0][1]
    assert ops_auto.error_ledger(clock=lambda: at + 1800, launch=lambda *a, **k: launched.append(a)) is None
    assert len(launched) == 1 and len(handed) == 1


def test_internal_measurement_failures_are_counted_on_their_own_rows(tmp_path):
    (tmp_path / 'service.a.log').write_text(
        '2026-11-11 11:21:00 WARNING agent_market.execution: Execution failure reference=r1 resource_id=7 protocol=mcp '
        'code=INVALID_INPUT stage=admission exception=ExecutionDenied qa=real_task_score\n'
        '2026-11-11 11:22:00 WARNING agent_market.execution: Execution failure reference=r2 resource_id=None protocol=mcp '
        'code=INVALID_INPUT stage=admission exception=ExecutionDenied\n')
    result = error_ledger.ledger(DAY, counts=error_ledger.from_logs(DAY, tmp_path), known=[])
    keys = {r['key']: r for r in result['rows']}
    assert keys['qa|real_task_score|gateway|mcp|INVALID_INPUT|admission']['internal']
    assert not keys['gateway|mcp|INVALID_INPUT|admission']['explained']
    assert (result['total'], result['internal'], result['unexplained']) == (2, 1, 1)
    assert '내부 측정 1건' in error_ledger.write(result, tmp_path).read_text()


def test_a_fixed_bug_rule_stops_explaining_after_its_date():
    known = [{'pattern': r'^log\|a\|x', 'reason': 'fixed in abc', 'until': '2026-11-11'}]
    assert error_ledger.ledger('2026-11-11', counts=Counter({'log|a|x|y': 1}), known=known)['unexplained'] == 0
    assert error_ledger.ledger('2026-11-12', counts=Counter({'log|a|x|y': 1}), known=known)['unexplained'] == 1


def test_retention_rows_are_recorded_apart_from_errors(tmp_path):
    (tmp_path / 'jobs.main.log').write_text(
        "2026-11-11 03:00:00 INFO agent_market.workspace_admin_retention: admin retention removed {'security_events': 10000}\n"
        "2026-11-11 03:05:00 INFO agent_market.workspace_admin_retention: admin retention removed {'security_events': 120, 'x': 'index_missing'}\n"
        "2026-11-10 03:05:00 INFO agent_market.workspace_admin_retention: admin retention removed {'security_events': 9}\n")
    assert error_ledger.retention_removed(DAY, tmp_path) == {'security_events': 10120}
    result = error_ledger.ledger(DAY, counts=Counter(), known=[])
    result['retention_removed'] = error_ledger.retention_removed(DAY, tmp_path)
    assert 'security_events 10,120행' in error_ledger.write(result, tmp_path).read_text()


def test_privacy_check_counts_unreduced_new_rows_and_is_never_explained():
    clean = error_ledger.from_privacy(DAY, run=lambda q: 'security_events_ip|0\nsecurity_events_user_agent|0\nadmin_audit_logs_ip|0\n')
    assert clean == Counter()
    dirty = error_ledger.from_privacy(DAY, run=lambda q: 'security_events_ip|2\nsecurity_events_user_agent|0\nadmin_audit_logs_ip|1\n')
    assert dirty == Counter({'privacy|unreduced|security_events_ip': 2, 'privacy|unreduced|admin_audit_logs_ip': 1})
    result = error_ledger.ledger(DAY, counts=dirty, known=[{'pattern': '.*', 'reason': 'everything'}])
    assert result['unexplained'] == 3 and result['privacy_ok'] is False
    assert error_ledger.from_privacy(DAY, run=lambda q: '') == Counter({'ledger|privacy_unreadable|empty': 1})


def test_a_deferred_workflow_round_counts_from_the_moment_it_was_added(tmp_path):
    """PM 11-12 08:2x: 'Due workflow round deferred ... statement_failed' is a storage failure; count it after 08:14."""
    from scripts import error_ledger as e
    log = tmp_path / 'biz.agentconcierge.x.execution.main.log'
    log.write_text('\n'.join([
        '2026-11-12 08:13:16 WARNING __main__: Due workflow round deferred after a storage error: statement_failed',
        '2026-11-12 08:20:01 WARNING __main__: Due workflow round deferred after a storage error: statement_failed at workflows.py:883 run_due',
        '2026-11-12 08:21:01 WARNING __main__: Due workflow round deferred after a storage error: statement_failed at workflows.py:883 run_due',
        '2026-11-12 08:22:01 WARNING agent_market.other: something harmless',
    ]) + '\n')
    counts = e.from_logs('2026-11-12', logs=tmp_path)
    assert counts == {'warn|main|__main__|Due workflow round deferred after a storage error: statement_failed|workflows.py:883 run_due': 2}
    rows = e.explain(counts, known=[], day='2026-11-12')
    assert rows[0]['explained'] is False


def test_a_failure_seen_only_by_a_measurement_is_counted_and_stays_unexplained(tmp_path):
    from scripts import error_ledger as e
    path = tmp_path / 'manual.jsonl'
    path.write_text('\n'.join([
        '{"day": "2026-11-12", "key": "measure|explore_timeout_30s|no_trace", "count": 1, "note": "10:03"}',
        '{"day": "2026-11-11", "key": "measure|other", "count": 4}',
        '{"day": "2026-11-12", "key": "log|not|a|measure", "count": 9}',
        'not json']) + '\n')
    counts = e.from_manual('2026-11-12', path)
    assert counts == {'measure|explore_timeout_30s|no_trace': 1}
    assert e.explain(counts, known=[], day='2026-11-12')[0]['explained'] is False
