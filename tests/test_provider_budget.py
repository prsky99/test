"""One shared daily budget for outside test calls per registrable domain (PM 11-14)."""
import threading
from datetime import datetime

import pytest

from agent_market import provider_budget as pb


def at(day, h=12):
    return datetime(2026, 11, day, h, 0, tzinfo=pb.KST).timestamp()


def test_calls_are_grouped_by_registrable_domain_and_hosting_tenant():
    assert pb.domain('https://api.example.com/mcp') == 'example.com'
    assert pb.domain('https://www.example.com/a2a') == 'example.com'
    assert pb.domain('https://x.y.example.co.uk/') == 'example.co.uk'
    assert pb.domain('https://alice.vercel.app/mcp') == 'alice.vercel.app'       # each tenant is its own provider
    assert pb.domain('https://deep.alice.vercel.app/') == 'alice.vercel.app'
    assert pb.domain('https://bob.up.railway.app/') == 'bob.up.railway.app'
    assert pb.domain('hub.rssa.getvda.ai') == 'getvda.ai'


def test_the_daily_total_and_each_system_share_hold_across_systems(tmp_path):
    url, now = 'https://api.example.com/mcp', at(14)
    assert all(pb.reserve(url, 'pearl_batch', now=now, directory=tmp_path)[0] for _ in range(3))
    assert pb.reserve(url, 'pearl_batch', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve(url, 'necklace_retest', n=35, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://www.example.com/', 'gate', n=22, now=now, directory=tmp_path) == (True, 'ok')   # 60 - 38
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')
    assert pb.reserve('https://other.org/', 'gate', n=60, now=now, directory=tmp_path) == (True, 'ok')
    day = pb.status(pb.today(now), tmp_path)['domains']['example.com']
    assert day['total'] == 60 and day['by'] == {'pearl_batch': 3, 'necklace_retest': 35, 'gate': 22}
    assert pb.reserve(url, 'pearl_batch', now=at(15), directory=tmp_path) == (True, 'ok')     # a new KST day
    with pytest.raises(ValueError):
        pb.reserve(url, 'someone_new', now=now, directory=tmp_path)


def test_a_429_stops_every_system_on_that_domain_for_the_rest_of_the_day(tmp_path):
    now = at(14, 9)
    assert pb.reserve('https://a.example.com/', 'role_tests', now=now, directory=tmp_path)[0]
    assert pb.note('https://a.example.com/', 'role_tests', 429, now=now, directory=tmp_path)
    assert not pb.note('https://a.example.com/', 'role_tests', 200, now=now, directory=tmp_path)
    for system in ('necklace_retest', 'gate', 'pearl_batch', 'substitute_tests'):
        assert pb.reserve('https://b.example.com/', system, now=at(14, 23), directory=tmp_path) == (False, 'paused_429')
    assert pb.reserve('https://b.example.com/', 'necklace_retest', now=at(15, 1), directory=tmp_path)[0]


def test_concurrent_reservations_never_pass_the_total(tmp_path):
    now, granted = at(14), []

    def worker():
        for _ in range(20):
            ok, _ = pb.reserve('https://c.example.net/', 'gate', now=now, directory=tmp_path)
            granted.append(ok)
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(granted) == pb.DAILY_TOTAL == pb.status(pb.today(now), tmp_path)['domains']['example.net']['total']
