"""A failed listener reservation must not open storage or start a partial server."""
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_market.gateway.startup import reserve_listeners, wal_reset_fixed


def test_reservations_hold_both_ports_and_release_them_on_exit():
    with reserve_listeners([('admin', '127.0.0.1', 0), ('agent-front', '127.0.0.1', 0)]) as listeners:
        ports = [sock.getsockname()[1] for sock in listeners]
        assert ports[0] != ports[1]
        for port in ports:
            with socket.socket() as duplicate:
                with pytest.raises(OSError):
                    duplicate.bind(('127.0.0.1', port))
    for port in ports:
        with socket.socket() as reopened:
            reopened.bind(('127.0.0.1', port))


def test_second_port_collision_releases_the_first_reservation():
    with socket.socket() as first, socket.socket() as occupied:
        first.bind(('127.0.0.1', 0))
        first_port = first.getsockname()[1]
        first.close()
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        with pytest.raises(RuntimeError, match='agent-front'):
            with reserve_listeners([('admin', '127.0.0.1', first_port),
                                    ('agent-front', '127.0.0.1', occupied.getsockname()[1])]):
                pytest.fail('A partial startup must never be yielded')
        with socket.socket() as reopened:
            reopened.bind(('127.0.0.1', first_port))


def test_port_collision_exits_before_database_or_ssl_side_effects(monkeypatch):
    import agent_market.gateway.server as gateway
    import agent_market.gateway.startup as startup
    import agent_market.gateway.ssl_manager as tls
    import agent_market.logger as logging_setup
    app_factory, tls_factory = Mock(), Mock()
    monkeypatch.setattr(gateway, 'create_app', app_factory)
    monkeypatch.setattr(tls, 'get_ssl_manager', tls_factory)
    monkeypatch.setattr(startup, 'prefer_patched_macos_sqlite', lambda: None)
    monkeypatch.setattr(logging_setup, 'setup_logging', lambda **kwargs: None)
    monkeypatch.setattr(logging_setup, 'shutdown_logging', lambda: None)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        monkeypatch.setenv('PORT', str(occupied.getsockname()[1]))
        monkeypatch.setenv('HOST', '127.0.0.1')
        with pytest.raises(SystemExit) as stopped:
            gateway.main()
    assert stopped.value.code == 1
    app_factory.assert_not_called()
    tls_factory.assert_not_called()


@pytest.mark.parametrize('version,safe', [
    ((3, 46, 0), False), ((3, 51, 2), False), ((3, 51, 3), True),
    ((3, 53, 0), True), ((3, 44, 6), True), ((3, 50, 7), True), ((3, 50, 6), False),
])
def test_wal_reset_patch_versions(version, safe):
    assert wal_reset_fixed(version) is safe


def test_macos_reexec_probes_runtime_and_preserves_configuration(monkeypatch):
    import agent_market.gateway.startup as startup
    monkeypatch.setattr(startup.sys, 'platform', 'darwin')
    monkeypatch.setattr(startup.sqlite3, 'sqlite_version_info', (3, 46, 0))
    monkeypatch.setattr(startup.Path, 'is_file', lambda path: True)
    monkeypatch.delenv('_A2A_SQLITE_REEXEC', raising=False)
    monkeypatch.setenv('GATEWAY_DB', '/example/keep.sqlite3')
    probe = Mock(return_value=SimpleNamespace(stdout='3.53.0\n'))
    monkeypatch.setattr(startup.subprocess, 'run', probe)
    class Reexecuted(Exception):
        pass
    def reexec(executable, argv, environment):
        assert executable == startup.sys.executable
        assert argv[1:3] == ['-m', 'agent_market.gateway.server']
        assert environment['GATEWAY_DB'] == '/example/keep.sqlite3'
        assert environment['_A2A_SQLITE_REEXEC'] == '1'
        assert environment['DYLD_LIBRARY_PATH'].startswith('/opt/homebrew/opt/sqlite/lib')
        raise Reexecuted
    monkeypatch.setattr(startup.os, 'execve', reexec)
    with pytest.raises(Reexecuted):
        startup.prefer_patched_macos_sqlite()
    probe.assert_called_once()
