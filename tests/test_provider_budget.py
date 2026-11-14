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


def test_github_hourly_share_floor_and_summary(tmp_path):
    """PM 11-14: GitHub's unauthenticated 60 an hour is split by system and everyone stops under 5 left."""
    now = at(14, 7)
    assert all(pb.github_reserve('role_tests', now=now, directory=tmp_path)[0] for _ in range(5))
    assert pb.github_reserve('role_tests', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.github_reserve('fallback_live', n=30, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.github_reserve('gate', n=21, now=now, directory=tmp_path) == (False, 'github_hourly_total')  # 55 usable
    assert pb.github_reserve('gate', n=20, now=now, directory=tmp_path) == (True, 'ok')
    # GitHub says only 4 are left (another user of this IP): everybody stops until the reset
    reset = int(now) + 1200
    assert pb.github_observe({'x-ratelimit-remaining': '4', 'x-ratelimit-reset': str(reset)}, 'gate', now=now,
                             directory=tmp_path) == 4
    later = at(14, 7) + 600
    assert pb.github_reserve('adhoc', now=later, directory=tmp_path) == (False, 'github_floor')
    assert pb.github_reserve('adhoc', now=at(14, 8), directory=tmp_path) == (True, 'ok')   # a new hour
    summary = pb.github_summary(hours=2, now=at(14, 8), directory=tmp_path)
    assert summary['total'] == 56 and list(summary['by'])[0] == 'fallback_live'
    assert summary['refused'] == {'role_tests': 1, 'gate': 21, 'adhoc': 1}
    with pytest.raises(ValueError):
        pb.github_reserve('collector', now=now, directory=tmp_path)


def test_fallback_github_calls_go_through_the_shared_allowance(tmp_path, monkeypatch):
    import httpx
    from agent_market.fallback_agents import net
    from agent_market.fallback_agents.limits import limiters
    monkeypatch.setattr(pb, 'DIR', tmp_path)
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={}, headers={'x-ratelimit-remaining': '3', 'x-ratelimit-reset': '9999999999'})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    net.get('https://api.github.com/repos/a/b', limiters=limiters(), seconds=5, limit=65536, http=client, preflight=False)
    with pytest.raises(net.SourceBusy):
        net.get('https://api.github.com/repos/a/c', limiters=limiters(), seconds=5, limit=65536, http=client, preflight=False)
    net.get('https://api.github.com/rate_limit', limiters=limiters(), seconds=5, limit=65536, http=client, preflight=False)
    assert seen == ['/repos/a/b', '/rate_limit']
    assert pb.github_summary(1, directory=tmp_path)['by'] == {'fallback_live': 1}


def test_public_data_institutions_take_30_substitute_tests_and_keep_the_domain_total(tmp_path):
    """PM 11-14 decision 3: 30 substitute tests a day for listed public-data domains; others stay at 5; total 60."""
    now = at(14)
    assert pb.reserve('https://data.sec.gov/submissions', 'substitute_tests', n=20, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://www.sec.gov/files/x.json', 'substitute_tests', n=10, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://www.sec.gov/y', 'substitute_tests', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve('https://api.example.com/', 'substitute_tests', n=6, now=now, directory=tmp_path) == \
        (False, 'system_share')
    assert pb.reserve('https://api.gleif.org/x', 'necklace_retest', n=35, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://api.gleif.org/x', 'substitute_tests', n=26, now=now, directory=tmp_path) == \
        (False, 'domain_daily_total')
    assert ('substitute_tests', 'github.com') not in pb.SHARE_OVERRIDE


def test_answer_key_references_count_in_the_ledger_and_stop_after_a_429(monkeypatch):
    """PM F15 11-14: data_quality reference reads are 'reference_checks', apart from users' runs; a 429 is not retried."""
    import httpx
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import data_quality as dq
    calls = []

    def fake_get(url, **_):
        calls.append(url)
        return httpx.Response(429 if 'busy' in url else 200, json={'version': '1.2.3'})
    monkeypatch.setattr(httpx, 'get', fake_get)
    assert dq._fetch_json('https://registry.npmjs.org/left-pad/latest') == {'version': '1.2.3'}
    assert pb.status()['domains']['npmjs.org']['by'] == {'reference_checks': 1}
    assert dq._fetch_json('https://api.busy.example/x') is None
    assert dq._fetch_json('https://api.busy.example/y') is None            # paused for the day: not called again
    assert calls == ['https://registry.npmjs.org/left-pad/latest', 'https://api.busy.example/x']
    for i in range(9):
        dq._fetch_json(f'https://registry.npmjs.org/p{i}/latest')
    assert dq._fetch_json('https://registry.npmjs.org/one-more/latest') is None   # share of 10 used
