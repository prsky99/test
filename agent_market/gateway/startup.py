"""Reserve both listeners before opening storage or starting background jobs."""
import contextlib
import logging
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

log = logging.getLogger(__name__)


def wal_reset_fixed(version):
    return (version >= (3, 51, 3) or
            (3, 50, 7) <= version < (3, 51, 0) or
            (3, 44, 6) <= version < (3, 45, 0))


def prefer_patched_macos_sqlite():
    """Use an installed patched Homebrew SQLite without replacing Python packages.

    DYLD must select the library before Python imports SQLite, hence re-exec.
    No connections exist when the command-line entry point calls this helper.
    https://www.sqlite.org/wal.html#walreset
    """
    if sys.platform != 'darwin' or wal_reset_fixed(sqlite3.sqlite_version_info):
        return
    if os.environ.get('_A2A_SQLITE_REEXEC') == '1':
        raise RuntimeError('The selected SQLite runtime did not load; use a Python runtime with patched SQLite')
    for prefix in ('/opt/homebrew/opt/sqlite/lib', '/usr/local/opt/sqlite/lib'):
        if not (Path(prefix) / 'libsqlite3.0.dylib').is_file():
            continue
        env = dict(os.environ)
        env['DYLD_LIBRARY_PATH'] = prefix + (':' + env['DYLD_LIBRARY_PATH'] if env.get('DYLD_LIBRARY_PATH') else '')
        try:
            result = subprocess.run([sys.executable, '-c', 'import sqlite3;print(sqlite3.sqlite_version)'],
                                    env=env, capture_output=True, text=True, timeout=5, check=True)
            version = tuple(int(part) for part in result.stdout.strip().split('.'))
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if not wal_reset_fixed(version):
            continue
        env['_A2A_SQLITE_REEXEC'] = '1'
        os.execve(sys.executable, [sys.executable, '-m', 'agent_market.gateway.server', *sys.argv[1:]], env)
    log.warning('SQLite %s predates the WAL-reset fix; use SQLite 3.51.3+ or a patched backport', sqlite3.sqlite_version)


@contextlib.contextmanager
def reserve_listeners(endpoints):
    """Hold real listening sockets until Uvicorn takes them; never partially bind."""
    with contextlib.ExitStack() as stack:
        listeners = []
        for role, host, port in endpoints:
            family = socket.AF_INET6 if ':' in host else socket.AF_INET
            sock = stack.enter_context(socket.socket(family, socket.SOCK_STREAM))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                sock.listen(2048)
                sock.setblocking(False)
            except OSError as exc:
                raise RuntimeError(f'Cannot start {role} listener on {host}:{port}: {exc.strerror}. '
                                   'Check the existing gateway process before starting another instance.') from exc
            listeners.append(sock)
        yield listeners
