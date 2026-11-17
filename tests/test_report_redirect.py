"""PM 11-17: test runs never touch production records, secrets or the production database (tests/report_redirect.py)."""
import builtins
import io
import os
import socket
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests import report_redirect as rr

ROOT = Path(__file__).resolve().parents[1]


def _checkout(tmp_path):
    root = tmp_path / 'co'
    (root / '.git').mkdir(parents=True)
    for rel, text in {'reports/old-2026-11-09/shot.json': 'record', 'reports/old-2026-11-09/other.json': 'other',
                      'exports/pearls/verify-snapshot.json': 'snapshot', 'logs/ops/status-board.md': 'board',
                      'gateway-data/postgres18/application.dsn': 'host=x port=55432',
                      'gateway-data/agentcon.env': 'KEY=1', 'gateway-data/ad_coin_v2_keys/k.pem': 'pem',
                      'gateway-data/notes.json': 'free'}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


@contextmanager
def _guarding(root, environ=None):
    """Point the guard at ROOT for one test, then put the session's guard back as it was."""
    saved = dict(rr._state)
    rr.uninstall()
    try:
        assert rr.install(root, environ=environ or {}) is True
        yield
    finally:
        rr.uninstall()
        if saved:
            assert rr.install(saved['root'], environ={'REPORT_SHOTS': '1'} if not saved['records'] else {})
            rr._state['moved'] |= saved['moved']
            rr._state['allowed'] = saved['allowed']


def test_session_guard_is_on_in_this_checkout():
    assert rr.active() == (ROOT / '.git').exists()


def test_record_writes_go_to_test_report_out_and_reads_follow(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    monkeypatch.chdir(root)
    with _guarding(root):
        Path('reports/old-2026-11-09/shot.json').write_text('new run')           # relative path, Path API
        with open(root / 'reports/new-dir/x.png', 'wb') as fh:                    # absolute path, builtin open
            fh.write(b'png')
        Path('exports/pearls/verify-snapshot.json').write_text('rebuilt')
        with open('logs/ops/status-board.md', 'a') as fh:
            fh.write('\nfake line')
        assert Path('reports/old-2026-11-09/shot.json').read_text() == 'new run'   # this session's write reads back
        assert Path('reports/old-2026-11-09/other.json').read_text() == 'other'    # other records read as they are
        Path('gateway-data/notes.json').write_text('changed')                      # outside the records: unchanged
    assert (root / 'reports/old-2026-11-09/shot.json').read_text() == 'record'
    assert not (root / 'reports/new-dir/x.png').exists()
    assert (root / 'exports/pearls/verify-snapshot.json').read_text() == 'snapshot'
    assert (root / 'logs/ops/status-board.md').read_text() == 'board'
    assert (root / 'gateway-data/notes.json').read_text() == 'changed'
    out = root / 'gateway-data/test-report-out'
    assert (out / 'reports/old-2026-11-09/shot.json').read_text() == 'new run'
    assert (out / 'reports/new-dir/x.png').read_bytes() == b'png'
    assert (out / 'logs/ops/status-board.md').read_text() == '\nfake line'     # append starts a fresh copy
    lines = (out / 'redirects.log').read_text().splitlines()
    assert len(lines) == 4 and all(len(line.split('\t')) == 3 for line in lines)


def test_report_shots_writes_the_records_but_secrets_stay_closed(tmp_path):
    root = _checkout(tmp_path)
    with _guarding(root, {'REPORT_SHOTS': '1'}):
        (root / 'reports/old-2026-11-09/shot.json').write_text('refreshed')
        with pytest.raises(PermissionError):
            (root / 'gateway-data/agentcon.env').read_text()
    assert (root / 'reports/old-2026-11-09/shot.json').read_text() == 'refreshed'


@pytest.mark.parametrize('rel', ['gateway-data/postgres18/application.dsn', 'gateway-data/agentcon.env',
                                 'gateway-data/ad_coin_v2_keys/k.pem'])
def test_production_secrets_cannot_be_opened(tmp_path, rel):
    root = _checkout(tmp_path)
    with _guarding(root):
        with pytest.raises(PermissionError):
            (root / rel).read_text()
        rr.allow_production(True)                                                 # a production_paths test
        assert (root / rel).read_text()


def test_production_database_connections_are_refused(tmp_path):
    root = _checkout(tmp_path)
    with _guarding(root):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(PermissionError):
                sock.connect(('127.0.0.1', 55432))
        finally:
            sock.close()
        assert rr.is_production_address(str(root / 'gateway-data/postgres18/run/.s.PGSQL.55432'))
        assert not rr.is_production_address(('127.0.0.1', 5432))
        psycopg = pytest.importorskip('psycopg')
        with pytest.raises(PermissionError):
            psycopg.connect(f'host={root}/gateway-data/postgres18/run port=55432 dbname=x user=x')
        with pytest.raises(PermissionError):
            psycopg.connect(host='127.0.0.1', port=55432, dbname='x', user='x')


def test_off_without_git_and_everything_restored(tmp_path):
    saved = dict(rr._state)
    rr.uninstall()
    try:
        bare = tmp_path / 'release'
        (bare / 'reports').mkdir(parents=True)
        assert rr.install(bare, environ={}) is False and not rr.active()        # release copy: no .git
        assert io.open is rr._ORIGINAL_OPEN and builtins.open is rr._ORIGINAL_OPEN
        assert socket.socket.connect is rr._ORIGINAL_CONNECT
    finally:
        if saved:
            assert rr.install(saved['root'], environ={'REPORT_SHOTS': '1'} if not saved['records'] else {})
            rr._state['moved'] |= saved['moved']


@pytest.mark.production_paths
def test_production_paths_marker_lifts_secrets_for_that_test_only():
    assert not rr.active() or rr._state['allowed'] is True


def test_unmarked_tests_are_not_allowed():
    assert not rr.active() or rr._state['allowed'] is False


def test_production_code_never_imports_the_guard():
    for folder in ('agent_market', 'scripts'):
        for path in (ROOT / folder).rglob('*.py'):
            assert 'report_redirect' not in path.read_text(errors='ignore'), path
