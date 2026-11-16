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
    assert pb.note('https://a.example.com/', 'role_tests', 429, now=now, directory=tmp_path, evidence=pb.PROVIDER_HTTP)
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
    assert pb.reserve('https://api.gleif.org/a', 'substitute_tests', n=20, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://api.gleif.org/b', 'substitute_tests', n=10, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://api.gleif.org/c', 'substitute_tests', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve('https://api.example.com/', 'substitute_tests', n=6, now=now, directory=tmp_path) == \
        (False, 'system_share')
    assert pb.reserve('https://api.gleif.org/x', 'necklace_retest', n=30, now=now, directory=tmp_path)[0]   # 30 + 30 = 60
    assert pb.reserve('https://api.gleif.org/x', 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')
    assert ('substitute_tests', 'github.com') not in pb.SHARE_OVERRIDE


def test_answer_key_references_count_in_the_ledger_and_stop_after_a_429(monkeypatch):
    """PM F15 11-14: data_quality reference reads are 'reference_checks', apart from users' runs; a 429 is not retried."""
    import httpx
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import data_quality as dq
    calls = []
    monkeypatch.setattr(pb, 'ONE_DAY', {})   # a dated grant (11-16 reference_checks npmjs.org 30) must not move the share of 10

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


def test_provider_self_claim_checks_have_six_a_domain_and_keep_the_total(tmp_path):
    """Agent team 11-15 (docs/PROVIDER_SELF_CLAIM.md): Verify and the 30-day recheck use 'provider_claims'."""
    url, now = 'https://provider.example/.well-known/agentvalcon.json', at(14)
    assert pb.SHARE['provider_claims'] == 6 and pb.DAILY_TOTAL == 60
    assert all(pb.reserve(url, 'provider_claims', now=now, directory=tmp_path)[0] for _ in range(6))
    assert pb.reserve(url, 'provider_claims', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve(url, 'gate', n=54, now=now, directory=tmp_path) == (True, 'ok')        # 60 - 6
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')


def test_public_institutions_with_a_checked_published_limit_take_ten_times_and_stay_under_half(tmp_path):
    """PM 11-15 11:40 decision 5: only domains whose published limit was checked, at most half of it, source kept."""
    now = at(14)
    for name, total in pb.DOMAIN_TOTAL.items():
        limit_text, daily_half, url = pb.DOMAIN_LIMIT_SOURCE[name]
        assert total <= daily_half and url.startswith('https://') and limit_text
    assert set(pb.DOMAIN_TOTAL) == {'sec.gov', 'arxiv.org', 'met.no', 'openalex.org'}   # NVD, GLEIF: no number we could check
    assert pb.reserve('https://data.sec.gov/x', 'necklace_retest', n=350, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://www.sec.gov/y', 'necklace_retest', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve('https://www.sec.gov/z', 'substitute_tests', n=250, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://www.sec.gov/z', 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')
    assert pb.reserve('https://export.arxiv.org/api', 'pearl_batch', n=30, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://api.met.no/x', 'role_tests', n=50, now=now, directory=tmp_path)[0]
    assert pb.reserve('https://api.example.com/', 'necklace_retest', n=36, now=now, directory=tmp_path) == \
        (False, 'system_share')                                            # commercial providers keep 35 / 60
    assert pb.share_limit('necklace_retest', 'example.com') == 35 and pb.domain_total('example.com') == 60


def test_rdap_reads_count_per_rdap_server_not_per_looked_up_domain(tmp_path):
    """Agent team E6 (11-15): .com and .net expiry reads both go to Verisign's RDAP server and share its 50."""
    now = at(14)
    assert pb.reserve('https://rdap.verisign.com/com/v1/domain/example.com', 'lifecycle_rdap', n=30, now=now,
                      directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://rdap.verisign.com/net/v1/domain/example.net', 'lifecycle_rdap', n=20, now=now,
                      directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://rdap.verisign.com/com/v1/domain/other.com', 'lifecycle_rdap', now=now,
                      directory=tmp_path) == (False, 'system_share')
    assert pb.reserve('https://rdap.identitydigital.services/rdap/domain/x.io', 'lifecycle_rdap', now=now,
                      directory=tmp_path) == (True, 'ok')
    assert pb.status(pb.today(now), tmp_path)['domains']['verisign.com']['by'] == {'lifecycle_rdap': 50}


def test_a_pause_needs_evidence_that_the_provider_sent_the_429(tmp_path, caplog):
    """The ledger's gatekeeper (PM 11:5x, 11-15): 11-14 05:11 and 11-15 11:42 our relay's own 429 paused providers."""
    import json
    now, url = at(15), 'https://filings.tools/mcp'
    assert pb.note(url, 'gate', 429, now=now, directory=tmp_path) is False                     # no evidence
    assert pb.note(url, 'gate', 429, now=now, directory=tmp_path, evidence={'origin': 'provider_rpc'}) is False
    assert pb.note('https://agentconcierge.biz/api/gateway/mcp/58997', 'gate', 429, now=now, directory=tmp_path,
                   evidence='provider_http') is False                                         # our own host
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (True, 'ok')               # still open
    entry = json.loads((tmp_path / f'{pb.today(now)}.json').read_text())['domains']['filings.tools']
    assert entry['pause_refused']['count'] == 2 and entry['pause_refused']['last']['why'] == 'no_evidence'
    assert 'refused' in caplog.text
    assert pb.note(url, 'gate', 429, now=now, directory=tmp_path,
                   evidence={'origin': 'provider_rpc', 'retry_after': 60, 'message': 'paused'}) is True
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (False, 'paused_429')
    entry = json.loads((tmp_path / f'{pb.today(now)}.json').read_text())['domains']['filings.tools']
    assert entry['paused']['evidence'] == {'origin': 'provider_rpc', 'retry_after': 60, 'message': 'paused'}
    other = 'https://api.example.org/x'
    assert pb.note(other, 'reference_checks', 429, now=now, directory=tmp_path, evidence=pb.PROVIDER_HTTP) is True
    assert pb.note(other, 'reference_checks', 200, now=now, directory=tmp_path) is False


def test_ad_review_blocklists_have_four_a_day_per_feed_host(tmp_path):
    """AI AD Coin (11-15): two read-only feed downloads a day; a retry fits, a loop does not."""
    now = at(14)
    assert all(pb.reserve('https://urlhaus.abuse.ch/downloads/hostfile/', 'ad_blocklists', now=now, directory=tmp_path)[0]
               for _ in range(4))
    assert pb.reserve('https://urlhaus.abuse.ch/downloads/hostfile/', 'ad_blocklists', now=now,
                      directory=tmp_path) == (False, 'system_share')
    assert pb.reserve('https://openphish.com/feed.txt', 'ad_blocklists', now=now, directory=tmp_path) == (True, 'ok')


def test_ad_review_domain_age_has_its_own_ten_beside_the_daily_lifecycle_fifty(tmp_path):
    """11-15: the daily E6 run cannot use up the RDAP reads a waiting advertiser's offer needs."""
    now = at(14)
    url = 'https://rdap.verisign.com/com/v1/domain/x.com'
    assert pb.reserve(url, 'lifecycle_rdap', n=50, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'lifecycle_rdap', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.reserve(url, 'ad_review_rdap', n=10, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')


def test_gdelt_substitute_tests_get_thirty_a_day_within_the_total_of_sixty(tmp_path):
    """11-15 PM 13:52: the GDELT news substitute's gate set and contract inputs; the domain total stays 60."""
    now = at(14)
    url = 'https://api.gdeltproject.org/api/v2/doc/doc?query=x&mode=artlist&format=json'
    assert pb.reserve(url, 'substitute_tests', n=30, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'substitute_tests', now=now, directory=tmp_path) == (False, 'system_share')
    assert pb.domain_total('gdeltproject.org') == 60


def test_census_geocoder_substitute_tests_get_thirty_a_day(tmp_path):
    """11-15 PM 14:25: the US-address substitute's gate set; geocoding.geo.census.gov counts as census.gov."""
    now = at(14)
    url = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=x&benchmark=Public_AR_Current&format=json'
    assert pb.reserve(url, 'substitute_tests', n=30, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'substitute_tests', now=now, directory=tmp_path) == (False, 'system_share')


def test_a_day_plan_keeps_calls_for_the_gate_first(tmp_path, monkeypatch):
    """PM 11-15 16:03: gate > substitute tests > pearl and role tests > necklace retests, on the planned domains."""
    import json as _json
    monkeypatch.setattr(pb, 'TERMS_PATH', tmp_path / 'no-terms.json')     # no published limits: the default 60
    pb._declared_cache.update(mtime=None, map={})
    now = at(9)
    (tmp_path / f'plan-{pb.today(now)}.json').write_text(_json.dumps({'holds': {'wikipedia.org': {'gate': 34, 'substitute_tests': 10}}}))
    url = 'https://en.wikipedia.org/api/rest_v1/page/summary/X'
    assert pb.reserve(url, 'necklace_retest', n=16, now=now, directory=tmp_path) == (True, 'ok')       # 60-44 left
    assert pb.reserve(url, 'necklace_retest', now=now, directory=tmp_path) == (False, 'held_for_higher_priority')
    assert pb.reserve(url, 'role_tests', now=now, directory=tmp_path) == (False, 'held_for_higher_priority')
    assert pb.reserve(url, 'substitute_tests', n=10, now=now, directory=tmp_path) == (True, 'ok')     # its own hold
    assert pb.reserve(url, 'gate', n=34, now=now, directory=tmp_path) == (True, 'ok')
    other = 'https://query.wikidata.org/sparql'                                                     # not planned
    assert pb.reserve(other, 'necklace_retest', n=35, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'gate', now=now, directory=tmp_path) == (False, 'domain_daily_total')


def test_without_a_plan_the_ledger_is_first_come(tmp_path):
    now = at(9)
    assert pb.plan(pb.today(now), tmp_path) == {}
    assert pb.reserve('https://en.wikipedia.org/x', 'necklace_retest', n=35, now=now, directory=tmp_path) == (True, 'ok')


def test_npm_registry_substitute_tests_get_thirty_a_day(tmp_path):
    """11-15 PM 16:12: package-releases reads registry.npmjs.org; the domain total stays 60."""
    now = at(14)
    url = 'https://registry.npmjs.org/lodash'
    assert pb.reserve(url, 'substitute_tests', n=30, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(url, 'substitute_tests', now=now, directory=tmp_path) == (False, 'system_share')


def test_one_day_grants_end_by_themselves(tmp_path):
    """11-15: the package-risk-audit activity answer set gets npm and GitHub reference reads on 11-16 only."""
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    d16 = datetime(2026, 11, 16, 3, 0, tzinfo=kst).timestamp()
    d16_day = datetime(2026, 11, 16, 14, 0, tzinfo=kst).timestamp()
    d17 = datetime(2026, 11, 17, 3, 0, tzinfo=kst).timestamp()
    npm = 'https://registry.npmjs.org/lodash'
    assert pb.reserve(npm, 'reference_checks', n=27, now=d16, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(npm, 'reference_checks', n=27, now=d17, directory=tmp_path) == (False, 'system_share')
    assert pb.github_share('reference_checks', d16) == 10
    assert pb.github_share('reference_checks', d16_day) == 2
    assert pb.github_reserve('reference_checks', n=10, now=d16, directory=tmp_path) == (True, 'ok')
    assert pb.reserve('https://api.openalex.org/works?search=x', 'reference_checks', n=39, now=d16, directory=tmp_path) == (True, 'ok')
    gh = 'https://api.github.com/advisories?cve_id=CVE-2024-1'
    assert pb.reserve(gh, 'reference_checks', n=50, now=d17, directory=tmp_path) == (True, 'ok')
    assert pb.reserve(gh, 'reference_checks', now=d17, directory=tmp_path) == (False, 'system_share')
    assert pb.github_share('reference_checks', d17) == 10


def test_a_declared_limit_lifts_the_day_total_to_a_fifth_of_it(tmp_path):
    """PM 11-15 17:16: 60 is our default; a published limit counts at 20%, never above it, at most 1000 a day."""
    import json as _json
    terms = tmp_path / 'member_terms.json'
    terms.write_text(_json.dumps({'members': {
        '264482': {'status': 'allowed', 'declared_limit': {'domain': 'dmvtransit.com', 'per_minute': 120, 'per_day': 3000,
                                                            'source': 'https://dmvtransit.com/mcp-server'}},
        '37322': {'status': 'allowed', 'declared_limit': {'domain': 'datakoot.com', 'per_day': 100, 'source': 'https://datakoot.com/terms'}},
        'w': {'status': 'allowed', 'declared_limit': {'domain': 'wikipedia.org', 'per_minute': 200,
                                                       'source': 'https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits'}},
        'x': {'status': 'silent', 'declared_limit': {'domain': 'nosource.dev', 'per_day': 9000}}}}))
    assert pb.domain_total('dmvtransit.com', terms) == 600            # 20% of 3,000
    assert pb.domain_total('datakoot.com', terms) == 20               # PM 17:24: 20% on a day without a gate
    assert pb.domain_total('wikipedia.org', terms) == 1000            # 200 a minute: the cap
    assert pb.domain_total('nosource.dev', terms) == 60               # no source, not counted
    assert pb.domain_total('presend.pages.dev', terms) == 60          # nothing published
    assert pb.domain_total('sec.gov', terms) == 600                   # the earlier fixed table still wins


def test_a_gate_day_lifts_a_declared_domain_and_live_calls_stop_at_80_percent(tmp_path, monkeypatch):
    """PM 11-15 17:24: datakoot publishes 100 a day; tests get 20, a gate day 60, live necklace calls up to 80."""
    import json as _json
    terms = tmp_path / 'member_terms.json'
    terms.write_text(_json.dumps({'members': {'37322': {'declared_limit': {'domain': 'datakoot.com', 'per_day': 100,
                                                                             'source': 'https://datakoot.com/terms'}}}}))
    monkeypatch.setattr(pb, 'TERMS_PATH', terms)
    pb._declared_cache.update(mtime=None, map={})
    url, now = 'https://datakoot.com/mcp', at(9)
    assert pb.reserve(url, 'necklace_retest', n=21, now=now, directory=tmp_path) == (False, 'domain_daily_total')
    (tmp_path / f'plan-{pb.today(now)}.json').write_text(_json.dumps({'holds': {'datakoot.com': {'gate': 60}}}))
    assert pb.reserve(url, 'gate', n=60, now=now, directory=tmp_path) == (True, 'ok')
    for _ in range(20):
        assert pb.live_reserve(url, now=now, directory=tmp_path) == (True, 'ok')
    assert pb.live_reserve(url, now=now, directory=tmp_path) == (False, 'quota_exhausted')   # 60 + 20 = 80
    assert pb.live_reserve('https://cwei59969.workers.dev/mcp', now=now, directory=tmp_path) == (True, 'ok')
    for _ in range(240):                                                          # 80% of 300
        assert pb.live_reserve('https://presend.pages.dev/x', now=now, directory=tmp_path, default_per_day=300) == (True, 'ok')
    assert pb.live_reserve('https://presend.pages.dev/x', now=now, directory=tmp_path, default_per_day=300) == (False, 'quota_exhausted')


def test_fallback_watch_hourly_probes_fit_every_sole_member_domain():
    """02900b54 probes a sole-member substitute once an hour (24 a day); sec.gov carries two of them (48)."""
    from agent_market import provider_budget as b
    assert b.share_limit('fallback_watch', 'gleif.org') >= 24
    assert b.share_limit('fallback_watch', 'sec.gov') >= 48


def test_holdout_r4_openalex_reads_fit_on_11_17_only():
    """workflow cdccd97e: 29 OpenAlex reads left for topic-evidence-brief holdout-r4, granted for 11-17 alone."""
    assert pb.share_limit('reference_checks', 'openalex.org', day='20261117') == pb.domain_total('openalex.org') == 50
    assert pb.share_limit('reference_checks', 'openalex.org', day='20261118') == 10 * 50 // 60   # ordinary day


def test_company_r5_sec_reads_fit_on_11_16_only():
    """gold_company_r5 reads SEC up to 95 times on 11-16 after holdout-r4 took 90 of the usual 100."""
    assert pb.share_limit('reference_checks', 'sec.gov', day='20261116') == 200
    assert pb.share_limit('reference_checks', 'sec.gov', day='20261117') == 200   # three company sets that day
    assert pb.share_limit('reference_checks', 'sec.gov', day='20261118') == 100


def test_wikidata_truth_source_terms_are_recorded_and_keep_the_default_total():
    """PM 11-16: Wikidata as a truth source is written down with its license and limits; no daily number is
    published, so its day total stays the default."""
    terms = pb.TRUTH_SOURCE_TERMS['wikidata.org']
    assert terms['license'].startswith('CC0') and terms['license_url'].startswith('https://www.wikidata.org/')
    assert 'wikidata.org' not in pb.DOMAIN_TOTAL and pb.domain_total('wikidata.org') == pb.DAILY_TOTAL


def test_holdout_r5_wiki_reads_fit_on_11_16_only():
    """PM 11-16: +40 Wikipedia reference reads for the mixed wikipedia-summary re-gate set, that day only."""
    assert pb.share_limit('reference_checks', 'wikipedia.org', day='20261116') == 216
    assert pb.share_limit('reference_checks', 'wikipedia.org', day='20261117') == 166


def test_the_cassette_share_is_small_on_commercial_domains_pinned_on_declared_ones_and_ends_after_1124():
    """agent team 11-16: one recording of the approved substitutes for the agents.py split (PM target 11-24)."""
    from agent_market import provider_budget as pb
    assert pb.share_limit('cassettes', 'deps.dev', day='2026-11-16') == 20
    assert pb.share_limit('cassettes', 'sec.gov', day='2026-11-16') == 40
    assert pb.share_limit('cassettes', 'wikipedia.org', day='2026-11-16') == 66
    assert pb.share_limit('cassettes', 'deps.dev', day='2026-11-25') == 0
