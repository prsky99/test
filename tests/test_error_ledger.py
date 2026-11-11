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
