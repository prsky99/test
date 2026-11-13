"""jobs steps for the fallback agents: the hourly watch and the daily airport index (PM 11-14)."""
from datetime import datetime

from agent_market.fallback_schedule import AirportIndexRefresh, FallbackWatchStep, airport_window


class Watch:
    def __init__(self, due=True, fail=False):
        self.is_due, self.fail, self.runs = due, fail, 0

    def due(self):
        return self.is_due

    def run(self):
        self.runs += 1
        if self.fail:
            raise OSError('disk')
        return {'alerts': [], 'open_problems': 0, 'failing': []}


def test_watch_step_runs_only_when_due_and_never_raises():
    idle = Watch(due=False)
    assert FallbackWatchStep(idle).run_due() is None and idle.runs == 0
    ok = Watch()
    assert FallbackWatchStep(ok).run_due() == {'fallback_watch': {'alerts': [], 'open_problems': 0, 'failing': []}}
    assert FallbackWatchStep(Watch(fail=True)).run_due() == {'fallback_watch': 'failed'}


def test_airport_refresh_once_a_day_in_its_window_and_not_without_an_index(tmp_path):
    at = lambda h, m: datetime(2026, 11, 14, h, m).timestamp()
    assert airport_window(at(7, 20)) and not airport_window(at(7, 5)) and not airport_window(at(4, 30))
    calls = []
    clock = [at(7, 5)]
    step = AirportIndexRefresh(clock=lambda: clock[0], sync=lambda: calls.append(1) or {'airports': 1})
    assert step.run_due() is None                       # :05 is the measurement window
    clock[0] = at(7, 20)
    assert step.run_due() == {'airport_index': 'started'}
    step.thread.join(5)
    assert calls == [1] and step.last['ok']
    assert step.run_due() is None                       # once a day
    missing = AirportIndexRefresh(clock=lambda: at(7, 20), path=tmp_path / 'airports.json')
    assert missing.run_due() == {'airport_index': 'no_index'} and missing.thread is None
