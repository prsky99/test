"""Imported by every Python child a test starts when this folder leads its PYTHONPATH (tests/conftest.py and
scripts/rehearse_storage_adapter_postgres._environment put it there, PM 11-18).

A child does not inherit the parent's patched socket, so the outside-network guard of tests/report_redirect.py part 4
would not cover it; the 11-18 technology-news bundle was written by such a child (a private-cluster rehearsal).
This installs only that part: a connect to a non-private address raises PermissionError. It does nothing when
NETWORK_GUARD is "off", and nothing at all when the checkout cannot be found."""
import os
import socket

if os.environ.get('NETWORK_GUARD') != 'off':
    import ipaddress

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
        if _outside(address):
            raise PermissionError(f'tests may not connect to the outside network ({address[0]}:{address[1]}; '
                                  'a test child, tests/child_guard)')

    def connect(self, address):
        _refuse(address)
        return _connect(self, address)

    def connect_ex(self, address):
        _refuse(address)
        return _connect_ex(self, address)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
