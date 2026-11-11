"""scripts/post_deploy_check.py: the before/after comparison the PM asked for (11-11 22시)."""
from scripts import post_deploy_check as check


def sample(s, cache, wire=40000):
    return {'s': s, 'status': 200, 'wire_bytes': wire, 'cache': cache, 'colo': 'LAX'}


def test_summary_keeps_the_first_visit_and_every_sample():
    rows = {'/': [sample(2.4, 'EXPIRED', 43600), sample(0.9, 'HIT'), sample(0.8, 'HIT')]}
    out = check.summary(rows)['/']
    assert out['first_s'] == 2.4 and out['median_s'] == 0.9 and out['within_1s'] == 2
    assert out['wire_kb'] == 42.6 and out['caches'] == ['EXPIRED', 'HIT', 'HIT'] and out['colos'] == ['LAX']


def test_a_failed_download_is_counted_not_dropped():
    rows = {'/': [{'s': 30.0, 'status': 'ReadTimeout'}, sample(1.2, 'MISS'), sample(1.1, 'HIT')]}
    out = check.summary(rows)['/']
    assert out['runs'] == 3 and out['first_s'] == 30.0 and out['median_s'] == 1.2


def test_compare_lists_every_page():
    before = {'summary': {p: check.summary({p: [sample(2.0, 'EXPIRED')]})[p] for p in check.PAGES}}
    after = {'summary': {p: check.summary({p: [sample(0.9, 'HIT', 20000)]})[p] for p in check.PAGES}}
    table = check.compare(before, after)
    assert len(table.splitlines()) == 1 + len(check.PAGES) and '39.1→19.5' in table
