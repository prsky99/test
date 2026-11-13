"""The network path recorder places a stall on the first hop that failed (11-11 PM)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('net_path', Path(__file__).resolve().parents[1] / 'scripts/net_path.py')
net_path = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net_path)

OK = {'gateway_ms': 0.4, 'internet_ms': 3.0, 'dns_ms': 8, 'edge': {'status': 200, 'total_s': 1.9},
      'tunnel': {'connections': 4.0}, 'public': {'status': 200, 'total_s': 2.7}}


def test_stalled_hop_names_the_first_failing_hop():
    assert net_path.stalled_hop(OK) is None                      # ~2 s to LAX is this Mac's normal
    assert net_path.stalled_hop({**OK, 'gateway_ms': None}) == 'lan'
    assert net_path.stalled_hop({**OK, 'internet_ms': None}) == 'isp'
    assert net_path.stalled_hop({**OK, 'dns_ms': None}) == 'dns'
    assert net_path.stalled_hop({**OK, 'edge': {'error': 'timeout', 'exit': 28}}) == 'mac_to_cloudflare'
    assert net_path.stalled_hop({**OK, 'tunnel': {'connections': 2.0}}) == 'tunnel'
    assert net_path.stalled_hop({**OK, 'public': {'status': 200, 'total_s': 5.0, 'exit': 28}}) == 'cloudflare_to_origin'


def test_a_public_stall_is_placed_on_the_origin_only_when_the_local_proxy_was_slow_too():
    """PM 11-13 16:2x: 16:08 explore 15.5 s with server 0.9 s; edge, tunnel or the origin's own queue?"""
    stalled = {'status': 0, 'total_s': 5.1, 'exit': 28}
    assert net_path.stalled_hop({**OK, 'public': stalled, 'origin': {'status': 200, 'total_s': 0.02}}) == 'cloudflare_to_origin'
    assert net_path.stalled_hop({**OK, 'public': stalled, 'origin': {'status': 0, 'total_s': 5.0, 'exit': 28}}) == 'origin'
    assert net_path.stalled_hop({**OK, 'public': stalled, 'origin': {'status': 200, 'total_s': 3.1}}) == 'origin'
    assert net_path.stalled_hop({**OK, 'origin': {'status': 0, 'exit': 7}}) is None   # the public path was fine


def test_summary_counts_stalled_minutes_by_hop():
    from datetime import datetime
    now = datetime.now(net_path.KST).strftime('%Y-%m-%d %H:%M:%S')
    rows = [{'at': now, 'stalled': None}, {'at': now, 'stalled': 'mac_to_cloudflare'}, {'at': '2000-01-01 00:00:00', 'stalled': 'lan'}]
    result = net_path.summary(rows)
    assert result['minutes'] == 2 and result['by_hop'] == {'mac_to_cloudflare': 1}


def test_quic_connections_are_read_per_connection_with_their_edge_and_loss():
    out = '\n'.join([
        'cloudflared_tunnel_server_locations{connection_id="0",edge_location="icn06"} 1',
        'cloudflared_tunnel_server_locations{connection_id="1",edge_location="icn07"} 1',
        'quic_client_latest_rtt{conn_index="0"} 3',
        'quic_client_smoothed_rtt{conn_index="0"} 4',
        'quic_client_congestion_window{conn_index="0"} 90496',
        'quic_client_latest_rtt{conn_index="1"} 40',
        'quic_client_lost_packets{conn_index="1",reason="reordering_threshold"} 13',
        'quic_client_lost_packets{conn_index="1",reason="time_threshold"} 21',
        'quic_client_closed_connections 4',
    ])
    conns = net_path.quic_connections(out)
    assert conns['0'] == {'lost': 0, 'edge': 'icn06', 'rtt_ms': 3.0, 'srtt_ms': 4.0, 'cwnd': 90496.0}
    assert conns['1'] == {'lost': 34, 'edge': 'icn07', 'rtt_ms': 40.0}
    assert net_path.quic_connections('cloudflared_tunnel_ha_connections 4') == {}


def test_a_public_stall_with_a_slow_handshake_of_its_own_is_not_put_on_edge_to_origin_alone():
    """PM 11-13 18:2x: in 10 of 11 slow minutes the public request's own TLS with the edge took 1.0-2.6 s."""
    origin = {'status': 200, 'total_s': 0.01}
    slow_handshake = {'status': 0, 'tls_s': 2.32, 'total_s': 5.08, 'exit': 28}
    assert net_path.stalled_hop({**OK, 'public': slow_handshake, 'origin': origin}) == 'mac_or_cloudflare_to_origin'
    clean = {'status': 200, 'tls_s': 0.48, 'first_byte_s': 3.97, 'total_s': 5.0}
    assert net_path.stalled_hop({**OK, 'public': clean, 'origin': origin}) == 'cloudflare_to_origin'
