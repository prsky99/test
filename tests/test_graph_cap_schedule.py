"""The daily graph-cap refresh is a jobs scheduler step (PM 11-15), once a day from 05:30, outside :55-:10."""
import json
import time

from agent_market.graph_cap_schedule import GraphCapRefresh, refresh_window


def at(h, m):
    return time.mktime((2026, 11, 16, h, m, 0, 0, 0, -1))


def test_the_window_and_once_a_day(tmp_path):
    assert not refresh_window(at(4, 0)) and not refresh_window(at(5, 56)) and refresh_window(at(5, 30))
    calls = []
    now = [at(5, 31)]
    step = GraphCapRefresh(clock=lambda: now[0], refresh=lambda: calls.append(1) or {'refreshed': False, 'reason': 'no_column'},
                           root=tmp_path)
    assert step.run_due() == {'graph_cap_refresh': 'started'}
    step.thread.join(5)
    assert step.run_due() is None and calls == [1]                      # once a day
    line = json.loads((tmp_path / 'logs/ops/graph-cap/refresh-2026-11-16.jsonl').read_text().splitlines()[0])
    assert line['ok'] and line['reason'] == 'no_column'


def test_a_failure_is_logged_and_never_raised(tmp_path):
    step = GraphCapRefresh(clock=lambda: at(6, 20), refresh=lambda: 1 / 0, root=tmp_path)
    step.run_due()
    step.thread.join(5)
    assert step.last['ok'] is False and step.last['error'] == 'ZeroDivisionError'


def test_the_scheduler_installs_it():
    from pathlib import Path
    assert 'GraphCapRefresh()' in Path('agent_market/gateway/server.py').read_text()
