"""The test wrapper never runs pytest without named tests and sends wide runs through heavy_slot (PM 11-12)."""
import pytest

from scripts import pytest_slot


def test_an_empty_list_or_a_missing_file_runs_nothing(tmp_path):
    with pytest.raises(SystemExit):
        pytest_slot.command([], root=tmp_path)
    with pytest.raises(SystemExit):
        pytest_slot.command(['tests/test_none.py'], root=tmp_path)
    assert pytest_slot.main([]) == 2


def test_small_runs_directly_and_wide_runs_through_heavy_slot(tmp_path):
    (tmp_path / 'tests').mkdir()
    names = []
    for i in range(7):
        (tmp_path / 'tests' / f'test_{i}.py').write_text('')
        names.append(f'tests/test_{i}.py')
    small = pytest_slot.command(names[:2] + ['tests/test_2.py::test_x'], root=tmp_path)
    assert small[:3] == ['nice', '-n', '15'] and small[-3:] == names[:2] + ['tests/test_2.py::test_x']
    wide = pytest_slot.command(names, minutes=20, root=tmp_path)
    assert wide[1:3] == ['-m', 'scripts.heavy_slot'] and wide[wide.index('--minutes') + 1] == '20'
    assert wide[wide.index('--') + 1:wide.index('--') + 4] == ['nice', '-n', '15']
    assert pytest_slot.command(['tests'], root=tmp_path)[1:3] == ['-m', 'scripts.heavy_slot']   # a directory is wide


def test_small_runs_wait_inside_a_window_reserved_for_rehearsals(monkeypatch, capsys):
    from scripts import heavy_slot, pytest_slot
    monkeypatch.setattr(heavy_slot, 'reserved', lambda now=None, board=None: 'reserved for copy rehearsals: 11-15 00:30~03:30')
    ran = []
    monkeypatch.setattr(pytest_slot.subprocess, 'run', lambda *a, **k: ran.append(a))
    assert pytest_slot.main(['tests/test_pytest_slot.py']) == heavy_slot.BUSY
    assert not ran and 'reserved for copy rehearsals' in capsys.readouterr().err


def test_day_runs_wait_for_load_and_for_two_runs_already_going():
    """PM 11-15 16:26: small runs had no limit in the day; explore slowed while five teams tested at once."""
    from datetime import datetime
    from scripts import pytest_slot
    day, night = datetime(2026, 11, 16, 14, 20), datetime(2026, 11, 16, 3, 0)
    assert pytest_slot.day_busy(day, load=2.0, running=1) is None
    assert 'load 9.5' in pytest_slot.day_busy(day, load=9.5, running=0)
    assert pytest_slot.day_busy(day, load=6.5, running=0) is None   # PM 11-16: 9.0, was 6.0
    assert '2 small test runs' in pytest_slot.day_busy(day, load=2.0, running=2)
    assert pytest_slot.day_busy(night, load=9.0, running=5) is None



def test_the_same_tests_started_five_times_in_ten_minutes_wait_the_sixth_time(tmp_path):
    """PM 11-17 06:3x: a loop retried one PostgreSQL test file every 60 s for 13 hours; fixing and rerunning one file
    three or four times in ten minutes stays allowed."""
    from scripts import pytest_slot
    log = tmp_path / 'runs.jsonl'
    tests = ['tests/test_b.py', 'tests/test_a.py']
    for at in (1000, 1100, 1200, 1300, 1400):
        assert pytest_slot.repeated(tests, now=at, log=log) is None
        pytest_slot.note_start(tests, now=at, log=log)
    refused = pytest_slot.repeated(list(reversed(tests)), now=1500, log=log)
    assert 'started 5 times' in refused and "PYTEST_SLOT_REPEAT_OK='<reason>'" in refused
    assert pytest_slot.repeated(['tests/test_a.py'], now=1500, log=log) is None   # other tests are not held back
    assert pytest_slot.repeated(tests, now=1000 + 601, log=log) is None          # the oldest start left the window


def test_a_checked_rerun_runs_and_keeps_its_reason_and_a_refused_run_is_not_counted(monkeypatch, tmp_path):
    import json
    from scripts import heavy_slot, pytest_slot
    log = tmp_path / 'runs.jsonl'
    monkeypatch.setattr(pytest_slot, 'repeat_log', lambda: log)
    monkeypatch.setattr(heavy_slot, 'reserved', lambda now=None, board=None: 'reserved for the public measurement')
    assert pytest_slot.main(['tests/test_pytest_slot.py']) == heavy_slot.BUSY
    assert not log.exists()
    monkeypatch.setattr(heavy_slot, 'reserved', lambda now=None, board=None: None)
    monkeypatch.setattr(heavy_slot, 'measurement_window', lambda now=None: None)
    monkeypatch.setattr(pytest_slot, 'day_busy', lambda *a, **k: None)
    monkeypatch.setattr(pytest_slot, 'repeated', lambda *a, **k: 'the same tests started 5 times')
    monkeypatch.setattr(pytest_slot.subprocess, 'run', lambda *a, **k: type('Done', (), {'returncode': 0})())
    assert pytest_slot.main(['tests/test_pytest_slot.py']) == heavy_slot.BUSY
    monkeypatch.setenv('PYTEST_SLOT_REPEAT_OK', 'fixed the fixture, rerun checked')
    assert pytest_slot.main(['tests/test_pytest_slot.py']) == 0
    row = json.loads(log.read_text().splitlines()[-1])
    assert row['repeat_ok'] == 'fixed the fixture, rerun checked' and row['tests'] == 'tests/test_pytest_slot.py'
