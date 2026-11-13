"""scripts.outside_server_split: the time outside the server in three parts (PM 11-13 10:3x)."""
import json

from scripts import outside_server_split as split


def sample(tls, first, body, server_ms, colo='LAX'):
    return {'tls_s': tls, 'first_byte_s': first, 'body_s': body, 'server_ms': server_ms, 'colo': colo}


def probe(at, edge_tls, edge_first, pub_tls, pub_first, colo='LAX', status=200):
    return {'at': at, 'edge': {'status': 200, 'tls_s': edge_tls, 'first_byte_s': edge_first, 'colo': colo},
            'public': {'status': status, 'tls_s': pub_tls, 'first_byte_s': pub_first, 'total_s': pub_first + 0.001}}


def test_a_sample_splits_into_parts_that_add_up():
    part = split.split_sample(sample(0.3, 1.5, 1.6, 700))
    assert part['client_edge'] == 0.3 and abs(part['edge_origin'] - 0.5) < 1e-9 and abs(part['body'] - 0.1) < 1e-9
    assert abs(part['outside'] - (part['client_edge'] + part['edge_origin'] + part['body'])) < 1e-9


def test_a_sample_without_server_timing_is_skipped_not_guessed():
    assert split.split_sample({'tls_s': 0.3, 'first_byte_s': 1.0, 'body_s': 1.0, 'server_ms': None}) is None


def test_probe_c2o_is_the_origin_trip_beyond_the_edge_only_wait():
    part = split.split_probe(probe('2026-11-13 03:00:00', 0.3, 0.45, 0.3, 0.65))
    assert abs(part['edge_wait'] - 0.15) < 1e-9 and abs(part['c2o'] - 0.2) < 1e-9
    assert split.split_probe(probe('2026-11-13 03:00:00', 0.3, 0.45, 0.3, 0.65, status=403)) is None


def test_build_groups_by_hour_and_band_and_counts_every_sample(tmp_path):
    slo = tmp_path / 'slo.jsonl'
    rows = [{'at': '2026-11-13 03:01', 'explore': {'samples': [sample(0.3, 1.2, 1.2, 600)] * 3}},
            {'at': '2026-11-13 10:01', 'explore': {'samples': [sample(0.5, 2.0, 2.0, 700), {'s': 9}]}}]
    slo.write_text('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
    probes = tmp_path / 'net.jsonl'
    probes.write_text('\n'.join(json.dumps(p) for p in [probe('2026-11-13 03:00:10', 0.3, 0.45, 0.3, 0.65),
                                                        probe('2026-11-13 10:00:10', 0.48, 0.81, 0.48, 1.01)]))
    result = split.build(str(slo), str(probes), '2026-11-13 00:00')
    assert result['slo_hours']['explore'][('2026-11-13', '03')]['n'] == 3
    assert result['slo_bands']['explore']['day 09-24']['n'] == 1          # the sample without timing is not counted
    assert abs(result['probe_bands']['day 09-24']['edge_wait']['p50'] - 0.33) < 1e-9
    text = split.markdown(result)
    assert '| 11-13 10 | 1 | 2000 | 700 | 1300 | 500 (500) | 800 (800) | 330 | 470 | 0 |' in text
    assert 'night 01-08' in text and 'c2o' in text


def test_until_bounds_the_window(tmp_path):
    slo = tmp_path / 'slo.jsonl'
    slo.write_text(json.dumps({'at': '2026-11-14 09:01', 'explore': {'samples': [sample(0.3, 1, 1, 500)]}}))
    probes = tmp_path / 'net.jsonl'
    probes.write_text('')
    assert split.build(str(slo), str(probes), '2026-11-13 00:00', '2026-11-14 00:00')['slo_whole'] == {}
