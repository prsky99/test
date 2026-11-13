"""The jobs scheduler runs workflow retention once an hour in its window, applying only when switched on (11-14)."""
from datetime import datetime
from types import SimpleNamespace

from agent_market.workflow_retention_schedule import WorkflowRetention, in_window, ENV


def at(h, m):
    return datetime(2026, 11, 14, h, m).timestamp()


class Maintenance:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def run(self, *, apply=False, limit=20, actor=0, now=None):
        self.calls.append((apply, limit, actor))
        if self.fail:
            raise RuntimeError('store busy')
        return {'dry_run': not apply, 'busy': False, 'body_candidates': 3, 'metadata_candidates': 0,
                'bodies_compacted': 3 if apply else 0, 'metadata_pruned': 0, 'held_invalid_evidence': 0}


def test_window_avoids_the_hourly_measurement_and_the_night_scoring():
    assert in_window(at(5, 20)) and in_window(at(13, 50))
    assert not in_window(at(13, 10)) and not in_window(at(13, 55)) and not in_window(at(13, 5))
    assert not in_window(at(4, 30)) and not in_window(at(3, 50)) and not in_window(at(5, 10))
    assert in_window(at(3, 40))


def test_it_runs_once_an_hour_and_applies_unless_switched_off():
    clock = [at(6, 25)]
    maintenance = Maintenance()
    job = WorkflowRetention(SimpleNamespace(maintenance=maintenance), clock=lambda: clock[0], env={ENV: '0'})
    first = job.run_due()
    assert maintenance.calls == [(False, 20, 0)] and first['workflow_retention']['dry_run'] is True
    clock[0] += 600
    assert job.run_due() is None                                   # within the hour
    clock[0] = at(7, 25)
    job.env = {}                                                   # applied by default (user approval 11-14)
    second = job.run_due()
    assert maintenance.calls[-1] == (True, 20, 0) and second['workflow_retention']['bodies_compacted'] == 3


def test_outside_the_window_nothing_runs_and_a_failure_does_not_stop_the_scheduler():
    maintenance = Maintenance(fail=True)
    job = WorkflowRetention(SimpleNamespace(maintenance=maintenance), clock=lambda: at(9, 0), env={ENV: '1'})
    assert job.run_due() is None and maintenance.calls == []
    job.clock = lambda: at(9, 30)
    assert job.run_due() == {'workflow_retention': 'failed'} and maintenance.calls == [(True, 20, 0)]
    assert WorkflowRetention(SimpleNamespace(), clock=lambda: at(9, 30)).run_due() is None
