"""Developer pass signals (PM 11-17): fake production rows, no database, no status board."""
import io
import json

from scripts import ad_coin_pass_signals as signals
from scripts.prod_ro_sql import statements


def _runner(lines, code=0, seen=None):
    def run(text, out, err):
        if seen is not None:
            seen.append(text)
        if code:
            print('refused: busy', file=err)
            return code
        out.write('\n'.join(lines) + '\n')
        return 0
    return run


ROWS = ['imp|a2a|4', 'imp|mcp|7', 'imp|explore|1', 'r429|12|3', 'feed429|2']


def test_the_statements_pass_the_read_only_checks_and_cover_one_utc_day():
    text = signals.build_sql('2026-11-16')
    assert len(statements(text)) == 3
    assert 'day_ms = 1794787200000' in text and 'at >= 1794787200 AND at < 1794873600' in text


def test_a_day_with_fake_rows_reports_only_measured_numbers(tmp_path):
    out, growth = tmp_path / 'signals.jsonl', tmp_path / 'necklace.jsonl'
    growth.write_text(json.dumps({'day': '2026-11-16', 'counts': [
        {'day': '2026-11-16', 'surface': 'mcp', 'necklace': 'cve-incident-brief', 'category': 'security', 'served': 3},
        {'day': '2026-11-15', 'surface': 'mcp', 'necklace': 'cve-incident-brief', 'category': 'security', 'served': 9}]})
        + '\n')
    seen, printed = [], io.StringIO()
    assert signals.main(['--day', '2026-11-16'], runner=_runner(ROWS, seen=seen), out_path=out,
                        necklace_path=growth, stdout=printed) == 0
    assert len(seen) == 1                                         # one read-only run
    record = json.loads(out.read_text())
    assert record['a'] == {'measured': False, 'reason': signals.NOT_MEASURED['a'],
                           'reference': {'rate_limit_429_events': 12, 'rate_limit_429_networks': 3}}
    assert record['b']['measured'] is False and record['b']['reference'] == {'read_limit_429_on_feed': 2}
    assert 'value' not in record['a'] and 'value' not in record['b']             # never a number for unmeasured
    assert record['c']['value'] == 12 and record['c']['met'] is False
    assert record['c']['by_surface'] == {'a2a': 4, 'explore': 1, 'mcp': 7}
    assert record['c']['necklace'] == [{'necklace': 'cve-incident-brief', 'surface': 'mcp', 'served': 3}]
    text = printed.getvalue().strip()
    assert text == record['text']
    assert text.startswith('- 11-16 개발자 이용권 신호: (a) 한도 50% 지문 측정 안 됨(')
    assert '(c) 광고 노출 12회(기준 1,000), 그중 목걸이 3회' in text and text.endswith('7일 연속 충족 없음')


def test_a_refused_read_leaves_c_unmeasured_and_exits_nonzero(tmp_path):
    out = tmp_path / 'signals.jsonl'
    printed = io.StringIO()
    assert signals.main(['--day', '2026-11-16'], runner=_runner([], code=75), out_path=out,
                        necklace_path=tmp_path / 'absent.jsonl', stdout=printed) == 1
    record = json.loads(out.read_text())
    assert record['c']['measured'] is False and 'exit 75' in record['c']['reason']
    assert record['c']['necklace'] is None and '목걸이 기록 없음' in printed.getvalue()


def test_seven_days_in_a_row_go_to_the_pm_and_a_gap_breaks_the_run(tmp_path):
    out = tmp_path / 'signals.jsonl'
    busy = ['imp|mcp|1500', 'r429|0|0', 'feed429|0']
    for day in range(10, 17):
        signals.main(['--day', '2026-11-%02d' % day], runner=_runner(busy), out_path=out,
                     necklace_path=tmp_path / 'absent.jsonl', stdout=io.StringIO())
    last = json.loads(out.read_text().splitlines()[-1])
    assert last['streak_days'] == {'a': 0, 'b': 0, 'c': 7} and last['text'].endswith('c 7일 연속 충족, PM에 올림')
    signals.main(['--day', '2026-11-18'], runner=_runner(busy), out_path=out,
                 necklace_path=tmp_path / 'absent.jsonl', stdout=io.StringIO())   # 11-17 missing
    last = json.loads(out.read_text().splitlines()[-1])
    assert last['streak_days']['c'] == 1 and last['text'].endswith('7일 연속 충족 없음(최장 1일)')


def test_unexpected_output_is_not_turned_into_numbers():
    rows, error = signals.query('2026-11-16', runner=_runner(['imp|mcp|3', 'something else']))
    assert rows is None and 'unexpected line' in error
    rows, error = signals.query('2026-11-16', runner=_runner(['imp|mcp|3']))
    assert rows is None and error == 'missing rows'


def test_our_own_machine_is_not_counted_as_demand(tmp_path):
    """PM 11-17: the 11-16 rate-limit 429s (4,399 from 127.0.x.x, client class 'other') were our own requests."""
    from scripts import ad_coin_pass_signals as sig
    own = tmp_path / 'own-networks.txt'
    own.write_text("203.0.113.7\n198.51.100.0/24\n# a note\n2001:db8::5\nnot an address'); DROP\n\n")
    assert sig.own_networks(own) == ['198.51.100.0/24', '2001:db8::5', '203.0.113.7']
    assert sig.own_networks(tmp_path / 'missing.txt') == []
    sql = sig.build_sql('2026-11-16', sig.own_networks(own))
    for part in ("ip NOT LIKE '127.%'", "ip NOT LIKE '10.%'", "ip NOT LIKE '192.168.%'", "ip <> '::1'",
                 "'internal'", "ip NOT IN ('198.51.100.0/24','2001:db8::5','203.0.113.7')"):
        assert sql.count(part) == 2, part                       # both 429 statements
    assert 'DROP' not in sql and '\\' not in sql
    seen = []
    sig.query('2026-11-16', runner=lambda text, out, err: (seen.append(text), 0)[1], own=[])
    assert "NOT IN" not in seen[0] and "ip NOT LIKE '127.%'" in seen[0]
