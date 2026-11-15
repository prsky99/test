"""Revenue funnel, one line a day (PM 11-15 10:57): read-only counts, a jsonl line and the board line."""
import json
import types
from datetime import datetime

import pytest

from scripts import ops_auto, prod_ro_sql, revenue_funnel

OUTPUT = ['clients|2828|3|126|126|185', 'channel|a2a|285', 'channel|mcp|576', 'channel|rest|1967',
          'owners|0|0|0', 'control|1|1', 'applications|internal|1|0', 'applications|external|2|1',
          'advertisers|internal|1', 'bookings|external|2|1|1|1|5000000|0', 'bookings|internal|3|0|0|0|0|0']


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
    ext, own = record['external'], record['internal']
    assert record['owners'] == 1 and ext['applications'] == 2 and ext['quotes'] == 2 and ext['paid'] == 1
    assert ext['usdc_received'] == 5.0 and ext['paid_24h'] == 1 and ext['advertisers_active'] == 0
    assert own == {'applications': 1, 'applications_24h': 0, 'advertisers_active': 1, 'quotes': 3, 'quotes_24h': 0,
                   'paid': 0, 'paid_24h': 0, 'usdc_received': 0.0, 'refunded': 0}   # kept apart, never dropped
    text = revenue_funnel.line(record)
    assert text == ('토큰 받은 클라이언트 2828(새 126) → 다시 들고 옴 185 → 토큰 재방문(하한) 3 → 소유 확인 1 → 외부 신청 2'
                    ' → 견적 2 → 결제 1 → 5.00 USDC | 내부 신청 1·견적 3·결제 0')
    assert len('2026-11-15 ' + text) <= 150   # ops_auto.board_handoff keeps 150
    assert record['reidentified'] == 185 and record['returning_basis'] == 'credential_lower_bound'


def test_the_internal_rule_is_the_ad_coin_demand_rule():
    sql = open('deploy/ops/adcoin-demand-counts.sql').read()
    for value in (revenue_funnel.HOUSE, revenue_funnel.PLATFORM):
        assert value.strip("'") in sql
    empty = revenue_funnel.parse(['clients|5|0|1|1|0', 'owners|0|0|0', 'control|0|0', 'advertisers|internal|1'])
    assert empty['external']['applications'] == 0 and empty['external']['paid'] == 0 and empty['internal']['advertisers_active'] == 1


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
    import sys
    monkeypatch.setitem(sys.modules, 'scripts.revenue_funnel', None)   # launchd runs ops_auto.py as a script: no 'scripts.' package
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
    assert handed[0][0] == 'revenue' and handed[0][1].startswith('2026-11-16 토큰 받은 클라이언트 2828(새 126)')
    assert ops_auto.TEAM['revenue'] == 'PM'
    failed = lambda: types.SimpleNamespace(returncode=75, stdout='')                       # noqa: E731
    assert ops_auto.revenue_funnel(clock=at(2026, 11, 17, 8, 5), run=failed) == 'failed'
    assert handed[-1] == ('revenue', '매출 깔때기 집계(scripts/revenue_funnel.py)가 결과를 내지 못함 → 운영·SRE 확인')


def test_a_daily_report_line_is_replaced_and_never_escalates(monkeypatch, tmp_path):
    board = tmp_path / 'board.md'
    board.write_text('## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n\n## PM 결정 대기\n')
    monkeypatch.setattr(ops_auto, 'BOARD', board)
    escalated = []
    monkeypatch.setattr(ops_auto, 'escalate', lambda kind, text: escalated.append(kind))
    for day in range(1, 10):
        ops_auto.board_handoff('revenue', f'2026-11-{day:02d} 클라이언트 {day}')
        ops_auto.board_handoff('disk', f'disk full {day}')   # an alert still counts its repeats
    text = board.read_text()
    assert text.count('자동 점검 [revenue]') == 1 and '2026-11-09 클라이언트 9' in text
    assert '같은 경고' not in [row for row in text.splitlines() if '[revenue]' in row][0]
    assert escalated == ['disk'] and '같은 경고 9회째' in text


def test_no_test_can_write_the_real_ops_state_files():
    """conftest.isolated_ops_state (11-15): the ops watch's board, logs and state files point into a temporary folder."""
    from pathlib import Path
    real = ops_auto.ROOT / 'logs'
    for key in ('REVENUE_STATE', 'NORTH_STAR_STATE', 'VECTOR_USAGE_STATE', 'STATE', 'ACTIONS', 'BOARD', 'ESCALATIONS'):
        assert real not in Path(getattr(ops_auto, key)).parents, key
    assert ops_auto.AGENTCON_ENV.name == 'agentcon.env'   # an input it only reads stays where it is


def test_registry_clients_come_from_the_frontend_traffic_files_without_our_own(tmp_path):
    """E7 (PM 5-2 4): distinct registry clients a day; each process salts its own digests, so the sum is an upper bound."""
    from agent_market.concierge.traffic import entry_of
    assert entry_of('GET', '/registry/verified/v0.1/servers') == 'registry'
    # 08:05 KST on 11-16 is 23:05 UTC on 11-15: the last full UTC day is 11-14 (09:00 KST 11-14 to 09:00 KST 11-15)
    (tmp_path / '2026-11-14.111.json').write_text(json.dumps({'distinct': {'registry|other': 3, 'registry|internal': 9,
                                                                            'mcp|other': 50}}))
    (tmp_path / '2026-11-14.222.json').write_text(json.dumps({'distinct': {'registry|other': 1, 'registry|ai_bot': 2}}))
    (tmp_path / '2026-11-15.111.json').write_text(json.dumps({'distinct': {'registry|other': 40}}))   # UTC day not over
    got = revenue_funnel.registry_clients(lambda: datetime(2026, 11, 16, 8, 5).timestamp(), tmp_path)
    assert got == {'day': '2026-11-14', 'total': 6, 'by_class': {'other': 4, 'ai_bot': 2},
                   'basis': 'sum_over_processes_upper_bound'}
