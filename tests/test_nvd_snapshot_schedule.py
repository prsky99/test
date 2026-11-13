"""The jobs scheduler refreshes the NVD snapshot every two hours in its window, in a background thread (11-14)."""
from datetime import datetime

from agent_market.nvd_snapshot_schedule import NvdSnapshotRefresh, in_window


def at(h, m):
    return datetime(2026, 11, 14, h, m).timestamp()


def test_window_avoids_the_hourly_measurement():
    assert in_window(at(6, 15)) and in_window(at(6, 50))
    assert not in_window(at(6, 55)) and not in_window(at(7, 5)) and not in_window(at(7, 10))


def test_it_runs_every_two_hours_in_a_thread_and_survives_a_failure(tmp_path):
    calls, clock = [], [at(6, 20)]

    def sync():
        calls.append(clock[0])
        if len(calls) == 2:
            raise RuntimeError('feed down')
        return {'mode': 'update', 'changed': 3}
    job = NvdSnapshotRefresh(clock=lambda: clock[0], sync=sync)
    assert job.run_due() == {'nvd_snapshot': 'started'}
    job.thread.join(); assert job.last['ok'] and len(calls) == 1
    clock[0] = at(7, 20)
    assert job.run_due() is None                          # within two hours
    clock[0] = at(8, 21)
    assert job.run_due() == {'nvd_snapshot': 'started'}
    job.thread.join(); assert job.last == {'ok': False, 'error': 'RuntimeError'}
    clock[0] = at(10, 30)
    assert job.run_due() == {'nvd_snapshot': 'started'}
    job.thread.join(); assert len(calls) == 3


def test_without_a_snapshot_it_does_nothing(tmp_path):
    job = NvdSnapshotRefresh(clock=lambda: at(6, 20), data_dir=tmp_path)
    assert job.run_due() == {'nvd_snapshot': 'no_snapshot'} and job.thread is None
