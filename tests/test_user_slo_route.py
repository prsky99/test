"""PM 11-18: user_slo shows a run that went through another Cloudflare path, without leaving any sample out."""
from scripts import user_slo as slo


def _run(colos, tls):
    samples = [{'colo': c, 'tls_s': t, 's': 1.0} for c, t in zip(colos, tls)]
    return {'explore': {'samples': samples}, 'recommend': {'samples': []}, 'pages': {'samples': []}}


def test_the_usual_path_is_not_a_route_shift():
    got = slo.route(_run(['LAX', 'LAX', 'LAX'], [0.31, 0.30, 0.37]))
    assert got == {'colos': ['LAX'], 'tls_median_s': 0.31, 'route_shift': False}


def test_europe_or_a_slow_handshake_is_a_route_shift():
    assert slo.route(_run(['MAN', 'DUB'], [0.57, 0.59]))['route_shift'] is True        # 11-18 02:09
    assert slo.route(_run(['LAX', 'EWR', 'LAX'], [0.6, 0.62, 0.3]))['route_shift'] is True


def test_no_samples_is_not_a_shift_and_attainment_is_untouched():
    assert slo.route(_run([], []))['route_shift'] is False
    import inspect
    source = inspect.getsource(slo.main)
    assert source.index("record['attainment']") < source.index("record['route']")      # shown after, never used by it
