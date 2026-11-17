"""Test runs never touch production records, secrets or the production database (PM 11-17).

Installed by tests/conftest.py for the pytest session in a git checkout (a release copy has no .git, and production
code never imports this module):

1. Records: a write that resolves under <checkout>/reports/ or <checkout>/exports/, or to the status board
   logs/ops/status-board.md, goes to <checkout>/gateway-data/test-report-out/<same relative path> (gateway-data/ is
   git-ignored), one line per redirected file goes to test-report-out/redirects.log, and a later read of a file this
   session redirected reads the redirected copy. Every other path, and every read of a file this session did not
   write, is untouched. REPORT_SHOTS=1 turns this part off to refresh the records on purpose. (11-17: the night full
   pytest rewrote 13 dated report files; a report_v2.main test wrote two lines to the live board and rebuilt
   exports/pearls/verify-snapshot.json.)
2. Secrets: opening the production DSN file, env files or key folders of this checkout raises PermissionError.
   (11-17 11:45: a test read gateway-data/postgres18/application.dsn and counted rows in production.)
3. Production database: psycopg connections and sockets to the production server (the gateway-data/postgres18/run
   socket or port 55432) raise PermissionError. This joins the 11-15 guard in
   agent_market.application_runtime.refuse_production_in_tests, which only covers the store's own connect.

A test that has to use these on purpose carries @pytest.mark.production_paths (the conftest then lifts parts 2 and
3 for that test only; the list is reported to the PM). Subprocesses a test starts are not covered here; the
application runtime guard still refuses them through the inherited PYTEST_CURRENT_TEST.
"""
import builtins
import fnmatch
import io
import os
import socket
import time

_state = {}
_ORIGINAL_OPEN = io.open
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex

RECORD_FOLDERS = ('reports', 'exports')
RECORD_FILES = ('logs/ops/status-board.md',)
SECRET_PATTERNS = ('gateway-data/postgres18/*.dsn', 'gateway-data/*.env', 'gateway-data/*.env.*',
                   'gateway-data/*key*', 'gateway-data/ad_coin_v2_keys/*', 'gateway-data/signing/*',
                   'deploy/gateway.env')
PRODUCTION_SOCKET = 'gateway-data/postgres18/run'
PRODUCTION_PORT = 55432


def _real(file):
    if isinstance(file, int) or not isinstance(file, (str, bytes, os.PathLike)):
        return None
    path = os.fsdecode(os.fspath(file))
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(os.getcwd(), path))


def _relative(real):
    root = _state['root']
    return os.path.relpath(real, root) if real.startswith(root + os.sep) else None


def is_record(relative):
    return relative in RECORD_FILES or any(relative == f or relative.startswith(f + os.sep) for f in RECORD_FOLDERS)


def is_secret(relative):
    return any(fnmatch.fnmatch(relative, pattern) for pattern in SECRET_PATTERNS)


def _target(file, mode):
    """The path to open instead, or None to open FILE as asked; PermissionError for a production secret."""
    real = _real(file)
    relative = real and _relative(real)
    if not relative:
        return None
    if is_secret(relative) and not _state['allowed']:
        raise PermissionError(f'tests may not open the production file {relative} (tests/report_redirect.py; '
                              'mark the test production_paths if it must)')
    if not _state['records'] or not is_record(relative):
        return None
    moved = os.path.join(_state['out'], relative)
    if any(flag in mode for flag in 'wax+'):
        os.makedirs(os.path.dirname(moved), exist_ok=True)
        if real not in _state['moved']:
            _state['moved'].add(real)
            with _ORIGINAL_OPEN(_state['log'], 'a', encoding='utf-8') as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{real}\t{moved}\n")
        return moved
    return moved if real in _state['moved'] else None


def _open(file, mode='r', *args, **kwargs):
    target = _target(file, mode) if _state else None
    return _ORIGINAL_OPEN(target if target is not None else file, mode, *args, **kwargs)


def is_production_address(address):
    if isinstance(address, (str, bytes)):                       # AF_UNIX path, e.g. <run>/.s.PGSQL.55432
        path = os.fsdecode(address)
        return path.endswith(f'.s.PGSQL.{PRODUCTION_PORT}') or PRODUCTION_SOCKET in path
    return isinstance(address, tuple) and len(address) >= 2 and address[1] == PRODUCTION_PORT


def _refuse_address(address):
    if _state and not _state['allowed'] and is_production_address(address):
        raise PermissionError(f'tests may not connect to the production database at {address!r} '
                              '(tests/report_redirect.py; mark the test production_paths if it must)')


def _connect(self, address):
    _refuse_address(address)
    return _ORIGINAL_CONNECT(self, address)


def _connect_ex(self, address):
    _refuse_address(address)
    return _ORIGINAL_CONNECT_EX(self, address)


def refuse_production_conninfo(conninfo='', **kwargs):
    """psycopg goes through libpq, not Python sockets: check its connection options before it connects."""
    if not _state or _state['allowed']:
        return
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(conninfo, **kwargs)
    host = str(options.get('host') or os.environ.get('PGHOST') or '').rstrip('/')
    port = str(options.get('port') or os.environ.get('PGPORT') or '')
    if host.endswith(PRODUCTION_SOCKET) or port == str(PRODUCTION_PORT):
        raise PermissionError('tests may not connect to the production database (tests/report_redirect.py; '
                              'mark the test production_paths if it must)')


def _patch_psycopg():
    try:
        import psycopg
    except ImportError:
        return
    original = psycopg.Connection.connect.__func__
    if getattr(original, '_report_redirect', False):
        return

    def connect(cls, conninfo='', **kwargs):
        refuse_production_conninfo(conninfo, **{k: v for k, v in kwargs.items()
                                                if k not in ('autocommit', 'prepare_threshold', 'context',
                                                             'row_factory', 'cursor_factory')})
        return original(cls, conninfo, **kwargs)
    connect._report_redirect = True
    _state['psycopg'] = (psycopg.Connection, original, psycopg.connect)
    psycopg.Connection.connect = classmethod(connect)
    psycopg.connect = psycopg.Connection.connect          # psycopg.connect is bound when psycopg is imported


def install(root, environ=None):
    """Start guarding the checkout ROOT. Returns False (and does nothing) outside a git checkout."""
    environ = os.environ if environ is None else environ
    root = os.path.realpath(str(root))
    if _state or not os.path.exists(os.path.join(root, '.git')):
        return False
    out = os.path.join(root, 'gateway-data', 'test-report-out')
    os.makedirs(out, exist_ok=True)
    _state.update(root=root, out=out, moved=set(), log=os.path.join(out, 'redirects.log'), allowed=False,
                  records=environ.get('REPORT_SHOTS') != '1')
    io.open = builtins.open = _open
    socket.socket.connect, socket.socket.connect_ex = _connect, _connect_ex
    _patch_psycopg()
    return True


def uninstall():
    if _state:
        io.open = builtins.open = _ORIGINAL_OPEN
        socket.socket.connect, socket.socket.connect_ex = _ORIGINAL_CONNECT, _ORIGINAL_CONNECT_EX
        if 'psycopg' in _state:
            cls, original, module_connect = _state['psycopg']
            cls.connect = classmethod(original)
            import psycopg
            psycopg.connect = module_connect
        _state.clear()


def allow_production(flag):
    """For one test marked production_paths: lift the secret and database parts (records stay redirected)."""
    if _state:
        _state['allowed'] = bool(flag)


def active():
    return bool(_state)
