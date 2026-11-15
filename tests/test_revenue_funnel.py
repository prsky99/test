"""Revenue funnel, one line a day (PM 11-15 10:57): read-only counts, a jsonl line and the board line."""
import json
import types
from datetime import datetime

import pytest

from scripts import ops_auto, prod_ro_sql, revenue_funnel

OUTPUT = ['clients|2828|3|126|126', 'channel|a2a|285', 'channel|mcp|576', 'channel|rest|1967',
          'owners|0|0|0', 'control|1|1', 'applications|1|0', 'advertisers|1',
          'bookings|2|1|1|1|5000000|0']


def fake_run(lines, code=0):
    def run(text, out, err):
        assert text == revenue_funnel.SQL
        print('\n'.join(lines), file=out)
        if code:
            print('refused: the database has 45 connections', file=err)
        return code
    return run


def test_the_counts_pass_the_read_only_check_and_read_no_secret_or_personal_column():
    assert len(prod_ro_sql.statements(revenue_funnel.SQL)) == 7
    sql = revenue_funnel.SQL.lower()
    assert 'token' not in sql and 'user_agent' not in sql and 'fingerprint' not in sql and 'payer' not in sql
    assert 'select *' not in sql


def test_the_output_becomes_one_record_and_one_board_line():
    record = revenue_funnel.count(fake_run(OUTPUT))
    assert record['clients'] == 2828 and record['returning'] == 3 and record['clients_by_channel']['rest'] == 1967
    assert record['owners'] == 1 and record['applications'] == 1 and record['quotes'] == 2 and record['paid'] == 1
    assert record['usdc_received'] == 5.0 and record['paid_24h'] == 1
    text = revenue_funnel.line(record)
    assert text.startswith('식별 클라이언트 2828(24시간 새로 126·활동 126) → 서로 다른 날 2번 이상 3 → 제공자 소유 확인 1')
    assert '견적 2 → 결제 1 → 수령 5.00 USDC' in text


def test_a_refused_read_raises_and_writes_nothing(tmp_path):
    with pytest.raises(RuntimeError, match='exit 75'):
        revenue_funnel.main(run=fake_run([], code=75), log=tmp_path / 'funnel.jsonl')
    assert not (tmp_path / 'funnel.jsonl').exists()


def test_each_run_appends_one_dated_line(tmp_path, capsys):
    log = tmp_path / 'funnel.jsonl'
    revenue_funnel.main(run=fake_run(OUTPUT), log=log, clock=lambda: datetime(2026, 11, 16, 8, 3).timestamp())
    revenue_funnel.main(run=fake_run(OUTPUT), log=log, clock=lambda: datetime(2026, 11, 17, 8, 3).timestamp())
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row['at'] for row in rows] == ['2026-11-16 08:03', '2026-11-17 08:03'] and rows[0]['clients'] == 2828
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['at'] == '2026-11-17 08:03'


def test_ops_auto_writes_the_board_line_once_a_morning(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'REVENUE_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    record = revenue_funnel.parse(OUTPUT)
    run = lambda: types.SimpleNamespace(returncode=0, stdout=json.dumps(record) + '\n')   # noqa: E731
    at = lambda *t: (lambda: datetime(*t).timestamp())                                     # noqa: E731
    assert ops_auto.revenue_funnel(clock=at(2026, 11, 16, 7, 55), run=run) is None          # before 08:00
    assert ops_auto.revenue_funnel(clock=at(2026, 11, 16, 8, 5), run=run) == record
    assert ops_auto.revenue_funnel(clock=at(2026, 11, 16, 9, 5), run=run) is None           # once a day
    assert handed[0][0] == 'revenue' and handed[0][1].startswith('2026-11-16 식별 클라이언트 2828')
    assert ops_auto.TEAM['revenue'] == 'PM'
    failed = lambda: types.SimpleNamespace(returncode=75, stdout='')                       # noqa: E731
    assert ops_auto.revenue_funnel(clock=at(2026, 11, 17, 8, 5), run=failed) == 'failed'
    assert handed[-1] == ('revenue', '매출 깔때기 집계(scripts/revenue_funnel.py)가 결과를 내지 못함 → 운영·SRE 확인')
