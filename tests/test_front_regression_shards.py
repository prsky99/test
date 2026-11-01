"""File shards preserve the full offline corpus without accidental discovery."""
from itertools import chain
import sys

import pytest

from scripts import run_frontend_regressions as runner
from scripts import check_front_content as content_check


def test_content_inventory_includes_publication_and_generator(tmp_path, monkeypatch):
    names = ('new/en/index.html', 'new/en/assets/ui.js', 'new/html/index.html',
             'new/live-assets/ui.js', 'new/build_en.py', 'new/presentation.py',
             'new/shared-ui.js')
    for name in (*names, 'gateway-data/private.json', 'new/qa/private.html'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('')
    monkeypatch.setattr(content_check, 'ROOT', tmp_path)
    selected = set(content_check.public_content_paths())
    assert all(tmp_path / name in selected for name in names)
    assert tmp_path / 'gateway-data/private.json' not in selected
    assert tmp_path / 'new/qa/private.html' not in selected


def test_content_check_rejects_non_english_published_asset(tmp_path, monkeypatch):
    for name in ('agent_market/concierge/front.py', 'extracted_html.txt', 'AGENT_FRONT.md',
                 'agent_market/edge_gateway/sdk.js','agent_market/edge_gateway/router.py','agent_market/edge_gateway/service.py'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((content_check.ROOT / name).read_text())
    asset = tmp_path / 'new/en/assets/ui.js'
    asset.parent.mkdir(parents=True)
    asset.write_text('// ' + chr(0xAC00))
    monkeypatch.setattr(content_check, 'ROOT', tmp_path)
    _, errors = content_check.check()
    assert any('new/en/assets/ui.js:1: literal Hangul' in error for error in errors)
    asset.write_text('// Public interface')
    assert content_check.check()[1] == []


def fixture_files(tmp_path, monkeypatch, names):
    folder = tmp_path / 'tests'
    folder.mkdir()
    for name in names:
        (folder / name).write_text('')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'REQUIRED_TESTS', ())


def test_default_selection_preserves_patterns_sorting_and_deduplication(tmp_path, monkeypatch):
    fixture_files(tmp_path, monkeypatch, ['test_front_z.py', 'test_front_a.py',
        'test_workspace_roles.py', 'test_application_native.py', 'test_sns.py', 'test_unselected.py'])
    expected = ['tests/test_application_native.py', 'tests/test_front_a.py',
        'tests/test_front_z.py', 'tests/test_sns.py', 'tests/test_workspace_roles.py']
    assert runner.selected_tests() == expected == runner.selected_tests(1, 1)
    assert 'test_front_*.py' in runner.PATTERNS


def test_four_shards_cover_actual_corpus_exactly_once_and_are_stable():
    runner.validate_required_tests()
    complete = runner.selected_tests()
    shards = [runner.selected_tests(index, 4) for index in range(1, 5)]
    flattened = list(chain.from_iterable(shards))
    assert len(complete) > 4 and all(shards)
    assert sorted(flattened) == complete and len(set(flattened)) == len(flattened)
    assert max(map(len, shards)) - min(map(len, shards)) <= 1
    assert shards == [runner.selected_tests(index, 4) for index in range(1, 5)]
    assert 'tests/test_front_regression_shards.py' in complete
    assert {'tests/test_pearl_frontend.py', 'tests/test_pearl_menu_compositions.py',
            'tests/test_pearl_task_ux.py'} <= set(complete)


def test_required_suite_cannot_silently_fall_outside_patterns(tmp_path, monkeypatch):
    fixture_files(tmp_path, monkeypatch, ['test_critical.py', 'test_front_other.py'])
    monkeypatch.setattr(runner, 'REQUIRED_TESTS', ('test_critical.py',))
    with pytest.raises(ValueError, match='test_critical.py'):
        runner.validate_required_tests()
    monkeypatch.setattr(runner, 'PATTERNS', (*runner.PATTERNS, 'test_critical.py'))
    runner.validate_required_tests()
    (tmp_path / 'tests/test_critical.py').unlink()
    with pytest.raises(ValueError, match='test_critical.py'):
        runner.validate_required_tests()


@pytest.mark.parametrize('index,count', [(0, 1), (-1, 4), (5, 4), (2, 1), (1, 0),
    (1, -1), (1, 65), (True, 4), (1, True), (1.0, 4), (1, 4.0)])
def test_invalid_shard_bounds_rejected_without_selecting(index, count):
    with pytest.raises(ValueError):
        runner.selected_tests(index, count)


def test_list_flags_select_only_requested_shard_without_subprocess(tmp_path, monkeypatch, capsys):
    fixture_files(tmp_path, monkeypatch, ['test_front_'+str(i)+'.py' for i in range(8)])
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py', '--list', '--shard-index', '2', '--shard-count', '4'])
    monkeypatch.setattr(runner, 'run', lambda *_: pytest.fail('Listing must not execute a subprocess.'))
    assert runner.main() == 0
    assert capsys.readouterr().out.splitlines() == ['tests/test_front_1.py', 'tests/test_front_5.py']
    assert not (tmp_path / 'reports').exists()


@pytest.mark.parametrize('flags', [('--shard-index', '0'), ('--shard-count', '0'),
    ('--shard-index', '2'), ('--shard-count', '65'), ('--shard-index', 'invalid')])
def test_cli_invalid_bounds_exit_before_creating_output_or_running(tmp_path, monkeypatch, flags):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py', *flags, '--output', str(tmp_path / 'unexpected')])
    monkeypatch.setattr(runner, 'run', lambda *_: pytest.fail('Invalid arguments must not execute.'))
    with pytest.raises(SystemExit) as caught:
        runner.main()
    assert caught.value.code == 2 and not (tmp_path / 'unexpected').exists()


def test_empty_shard_never_falls_back_to_unscoped_pytest_discovery(tmp_path, monkeypatch, capsys):
    fixture_files(tmp_path, monkeypatch, ['test_front_one.py'])
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py', '--shard-count', '4', '--shard-index', '4'])
    monkeypatch.setattr(runner, 'run', lambda *_: pytest.fail('An empty shard must not discover the full corpus.'))
    assert runner.main() == 0 and 'No test modules' in capsys.readouterr().out
    assert not (tmp_path / 'reports').exists()


def test_unsharded_execution_keeps_existing_explicit_module_arguments(tmp_path, monkeypatch):
    fixture_files(tmp_path, monkeypatch, ['test_front_b.py', 'test_front_a.py'])
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py'])
    prepared, commands = [], []
    monkeypatch.setattr(runner, 'prepare_screenshot_directories', lambda names: prepared.extend(names))
    monkeypatch.setattr(runner, 'run', lambda command: commands.append(command) or 0)
    assert runner.main() == 0
    assert prepared == ['tests/test_front_a.py', 'tests/test_front_b.py']
    assert commands[0] == ['scripts/check_front_content.py']
    assert commands[-1] == ['-m', 'pytest', '-q', *prepared,
        '--junitxml=' + str(tmp_path / 'reports/frontend-regressions/regression.xml')]


def test_native_dependency_failure_stops_before_output_or_test_launch(tmp_path, monkeypatch, capsys):
    fixture_files(tmp_path, monkeypatch, ['test_application_postgres.py'])
    monkeypatch.setattr(runner, 'PATTERNS', ('test_application_*.py',))
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py'])
    def unavailable(name):
        raise ImportError('Synthetic missing driver')
    monkeypatch.setattr(runner.importlib, 'import_module', unavailable)
    monkeypatch.setattr(runner, 'run', lambda *_: pytest.fail('Missing dependencies must stop the cohort.'))
    with pytest.raises(SystemExit) as caught:
        runner.main()
    assert caught.value.code == 2
    assert 'requirements-storage-postgres.txt' in capsys.readouterr().err
    assert not (tmp_path / 'reports').exists()


def test_native_preflight_checks_tools_but_list_mode_remains_dependency_free(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    fixture_files(tmp_path, monkeypatch, ['test_application_postgres.py'])
    monkeypatch.setattr(runner, 'PATTERNS', ('test_application_*.py',))
    monkeypatch.setattr(runner.importlib, 'import_module', lambda name: SimpleNamespace(connect=lambda: None))
    monkeypatch.setattr(runner.shutil, 'which', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='initdb and pg_ctl'):
        runner.validate_native_dependencies(runner.selected_tests())
    monkeypatch.setattr(sys, 'argv', ['run_frontend_regressions.py', '--list'])
    assert runner.main() == 0
    assert 'test_application_postgres.py' in capsys.readouterr().out
