"""Imported by every Python child a test starts when this folder leads its PYTHONPATH (tests/conftest.py and
scripts/rehearse_storage_adapter_postgres._environment put it there, PM 11-18).

A child does not inherit the parent's patched socket, so the outside-network guard of tests/report_redirect.py part 4
would not cover it; the 11-18 technology-news bundle was written by such a child (a private-cluster rehearsal).
This installs only that part, with the same rule as the parent (tests/report_redirect.py): a connect to a
non-private address is written to gateway-data/test-report-out/outside-network.log with a "child" mark, and raises
PermissionError only when NETWORK_GUARD=block (the first nights run in report mode, PM 11-18). It does nothing when
NETWORK_GUARD is "off"."""
import os
import socket

if os.environ.get('NETWORK_GUARD') != 'off':
    import ipaddress
    import time
    from pathlib import Path

    _MODE = 'block' if os.environ.get('NETWORK_GUARD') == 'block' else 'report'
    _LOG = Path(__file__).resolve().parents[2] / 'gateway-data' / 'test-report-out' / 'outside-network.log'

    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _outside(address):
        if not (isinstance(address, tuple) and len(address) >= 2 and isinstance(address[0], str)):
            return False
        try:
            ip = ipaddress.ip_address(address[0].split('%', 1)[0])
        except ValueError:
            return address[0] != 'localhost'
        if getattr(ip, 'ipv4_mapped', None):
            ip = ip.ipv4_mapped
        return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified)

    def _refuse(address):
        if not _outside(address):
            return
        try:
            test = os.environ.get('PYTEST_CURRENT_TEST', '?').rsplit(' (', 1)[0]
            _LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_LOG, 'a', encoding='utf-8') as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{test}\t{address[0]}:{address[1]}\t{_MODE}\tchild\n")
        except OSError:
            pass
        if _MODE == 'block':
            raise PermissionError(f'tests may not connect to the outside network ({address[0]}:{address[1]}; '
                                  'a test child, tests/child_guard)')

    def connect(self, address):
        _refuse(address)
        return _connect(self, address)

    def connect_ex(self, address):
        _refuse(address)
        return _connect_ex(self, address)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
