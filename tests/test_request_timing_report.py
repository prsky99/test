"""scripts/request_timing_report.py: medians of real requests and the 14-day keep (PM 11-16)."""
import json
from datetime import datetime, date

from scripts import request_timing_report as rt


def write(directory, day, rows):
    path = directory / f'{day}.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows) + 'not json\n')


def test_recent_and_baseline_leave_out_qa_lines_and_split_by_kind(tmp_path):
    now = datetime(2026, 11, 17, 15, 0).timestamp()
    rows = [{'at': now - 60 * i, 'path': 'mcp', 'status': 200, 'server_ms': 1000 + i, 'qa': False} for i in range(1, 6)]
    rows += [{'at': now - 120, 'path': 'mcp', 'server_ms': 99999, 'qa': True},                    # our own test
             {'at': now - 90, 'path': 'api_explore', 'server_ms': 400, 'qa': False},
             {'at': now - 3 * 3600, 'path': 'chat', 'server_ms': 2000, 'qa': False},
             {'at': now - 5 * 3600, 'path': 'chat', 'server_ms': 1000, 'qa': False}]
    write(tmp_path, '2026-11-17', rows)
    recent = rt.recent(now, directory=tmp_path)
    assert recent == {'recommend': (1003, 5), 'explore': (400, 1)}
    assert rt.baseline(now, directory=tmp_path) == {'recommend': 1500.0}
    table = rt.hourly_table('2026-11-17', directory=tmp_path)
    assert table['14']['recommend']['n'] == 5


def test_prune_keeps_fourteen_days(tmp_path):
    for day in ('2026-11-01', '2026-11-02', '2026-11-03', '2026-11-17'):
        write(tmp_path, day, [])
    (tmp_path / 'notes.txt').write_text('x')
    assert rt.prune(14, directory=tmp_path, today=date(2026, 11, 17)) == ['2026-11-01.jsonl', '2026-11-02.jsonl']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['2026-11-03.jsonl', '2026-11-17.jsonl', 'notes.txt']
