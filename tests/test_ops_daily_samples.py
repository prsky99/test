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
