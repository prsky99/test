"""user_slo measures only when called without arguments (PM 11-17 06:3x: `--help` ran a real public measurement
at 05:14 and 06:28)."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('user_slo', Path(__file__).resolve().parents[1] / 'scripts/user_slo.py')
user_slo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(user_slo)


@pytest.fixture
def measured(monkeypatch):
    calls = []
    for name in ('check_explore', 'check_recommend_and_connect', 'check_pages'):
        monkeypatch.setattr(user_slo, name, lambda name=name: calls.append(name) or (({}, {}) if 'recommend' in name else {}))
    return calls


@pytest.mark.parametrize('argv, code', [(['--help'], 0), (['-h'], 0), (['--dry-run'], 2), (['now'], 2)])
def test_help_or_an_unknown_argument_measures_nothing(argv, code, measured, capsys):
    with pytest.raises(SystemExit) as stop:
        user_slo.main(argv)
    assert stop.value.code == code and measured == []
    if code == 0:
        assert 'without arguments' in capsys.readouterr().out


def test_the_hourly_call_without_arguments_still_parses():
    assert vars(user_slo.parse_args([])) == {}
