"""Parsers of the one-minute line-side record (PM 11-12 14:3x, read only)."""
from scripts import net_side

NETSTAT_IB = """Name       Mtu   Network       Address            Ipkts Ierrs     Ibytes    Opkts Oerrs     Obytes  Coll
en5        1500  <Link#10>   a0:ce:c8:95:a9:2e 27377002     0 20576343743 29386373     0 17667228203     0
en5        1500  macbook-pro fe80:a::8da:9afc: 27377002     - 20576343743 29386373     - 17667228203     -
"""


def test_interface_counters_come_from_the_link_row():
    assert net_side.interface_bytes('en5', NETSTAT_IB) == {'ibytes': 20576343743, 'obytes': 17667228203, 'ierrs': 0, 'oerrs': 0}
    assert net_side.interface_bytes('en0', NETSTAT_IB) is None


def test_ping_route_retransmits_and_process_bytes():
    text = '10 packets transmitted, 9 packets received, 10.0% packet loss\nround-trip min/avg/max/stddev = 0.466/0.560/0.792/0.108 ms'
    assert net_side.ping('x', text) == {'loss_pct': 10.0, 'avg_ms': 0.56, 'max_ms': 0.792}
    assert net_side.ping('x', 'ping: cannot resolve') == {'loss_pct': None, 'avg_ms': None, 'max_ms': None}
    assert net_side.default_route('    gateway: 192.168.0.1\n  interface: en5\n') == ('192.168.0.1', 'en5')
    assert net_side.tcp_retransmits('\t\t12 data packets (3456 bytes) retransmitted\n\t3 retransmit timeouts\n') == \
        {'packets': 12, 'bytes': 3456, 'timeouts': 3}
    nettop = ',bytes_in,bytes_out,\ncloudflared.1027,97353795,405836873,\nremoting_me2me_.3206,22816,23011,\n'
    assert net_side.process_bytes([], nettop) == {1027: (97353795, 405836873), 3206: (22816, 23011)}
    assert net_side.delta({'a': 5, 'b': None}, {'a': 2, 'b': 1}) == {'a': 3, 'b': None} and net_side.delta(None, {}) is None
