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
    assert small[:3] == ['nice', '-n', '10'] and small[-3:] == names[:2] + ['tests/test_2.py::test_x']
    wide = pytest_slot.command(names, minutes=20, root=tmp_path)
    assert wide[1:3] == ['-m', 'scripts.heavy_slot'] and wide[wide.index('--minutes') + 1] == '20'
    assert wide[wide.index('--') + 1:wide.index('--') + 4] == ['nice', '-n', '10']
    assert pytest_slot.command(['tests'], root=tmp_path)[1:3] == ['-m', 'scripts.heavy_slot']   # a directory is wide
