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


def test_summary_counts_stalled_minutes_by_hop():
    from datetime import datetime
    now = datetime.now(net_path.KST).strftime('%Y-%m-%d %H:%M:%S')
    rows = [{'at': now, 'stalled': None}, {'at': now, 'stalled': 'mac_to_cloudflare'}, {'at': '2000-01-01 00:00:00', 'stalled': 'lan'}]
    result = net_path.summary(rows)
    assert result['minutes'] == 2 and result['by_hop'] == {'mac_to_cloudflare': 1}
