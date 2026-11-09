"""매일 운영 점검 표본 스크립트의 오류율 집계(2026-11-10, 운영·SRE)."""
import json
from datetime import date

from scripts import ops_daily_samples as samples


def test_error_rate_splits_internal_and_external(tmp_path, monkeypatch):
    day = date.today().isoformat()
    folder = tmp_path / 'logs/service-frontend/traffic'
    folder.mkdir(parents=True)
    (folder / f'{day}.1.json').write_text(json.dumps({'status': {
        'explore|internal|2xx': 90, 'api_other|internal|5xx': 5, 'mcp|other|2xx': 3, 'api_other|other|5xx': 2}}))
    (folder / f'{day}.2.json').write_text(json.dumps({'status': {'home|browser|2xx': 5}}))
    (folder / f'{day}.bad.json').write_text('{not json')
    monkeypatch.setattr(samples, 'ROOT', tmp_path)
    [row] = samples.error_rates(0)
    assert row == {'day': day, 'requests': 105, '5xx': 7, '5xx_rate': 6.67, 'external': 10,
                   '5xx_external': 2, '5xx_external_rate': 20.0}


def test_days_without_traffic_are_left_out(tmp_path, monkeypatch):
    (tmp_path / 'logs/service-frontend/traffic').mkdir(parents=True)
    monkeypatch.setattr(samples, 'ROOT', tmp_path)
    assert samples.error_rates(7) == []


def test_recorded_rows_roll_up_by_iso_week(tmp_path):
    path = tmp_path / 'samples.jsonl'
    for day, explore, chat in (('2026-11-09', 1500, 3000), ('2026-11-10', 1800, 2800), ('2026-11-16', 2400, 4000)):
        result = {'load_1m': 3.0,
                  'explore_summary': {'n': 5, 'median_ms': explore, 'max_ms': explore + 500, 'over_goal': 0},
                  'chat_summary': {'n': 3, 'median_ms': chat, 'max_ms': chat + 900, 'over_goal': int(chat > 3500)}}
        row = samples.record(result, path)
        row['at'] = day + row['at'][10:]
        lines = path.read_text().splitlines()
        lines[-1] = json.dumps(row)
        path.write_text('\n'.join(lines) + '\n')
    path.write_text(path.read_text() + 'not json\n')
    weeks = samples.trend(path)
    assert [w['week'] for w in weeks] == ['2026-W46', '2026-W47']
    assert weeks[0]['explore'] == {'days': 2, 'median_ms': 1650, 'max_ms': 2300, 'over_goal': 0}
    assert weeks[1]['chat'] == {'days': 1, 'median_ms': 4000, 'max_ms': 4900, 'over_goal': 1}
    assert 'category' not in weeks[0]


def test_trend_without_a_record_file_is_empty(tmp_path):
    assert samples.trend(tmp_path / 'missing.jsonl') == []
