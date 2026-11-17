"""Sponsored offers served in necklace answers (PM 11-17): counted in memory, appended to a growth file at flush,
no schema change, our QA and Early-Data requests never counted."""
import json

from agent_market.ad_coin.v2 import sponsored_agent as sa

DAY = 86_400_000


def test_writer_appends_one_line_and_the_reader_sums_per_necklace_and_surface(tmp_path):
    path = tmp_path / 'logs/growth/necklace-ad-served.jsonl'
    day1, day2 = 20 * DAY, 21 * DAY
    sa.write_necklace_counts(path, {(day1, 'mcp', 'cve-incident-brief', 'security'): 2,
                                    (day1, 'a2a', 'cve-incident-brief', 'security'): 1}, now=day1 / 1000 + 60)
    sa.write_necklace_counts(path, {(day2, 'mcp', 'cve-incident-brief', 'security'): 3,
                                    (day2, 'mcp', 'topic-evidence-brief', 'research'): 4}, now=day2 / 1000 + 60)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first['day'] == '1970-01-21' and first['flushed_at'] == day1 // 1000 + 60
    assert first['counts'][0] == {'day': '1970-01-21', 'surface': 'a2a', 'necklace': 'cve-incident-brief',
                                  'category': 'security', 'served': 1}
    assert set(first['counts'][0]) == {'day', 'surface', 'necklace', 'category', 'served'}   # counts only
    path.open('a').write('not json\n{"counts": [{"day": "1970-01-22", "necklace": "x", "surface": "mcp", "served": -1}]}\n')
    today = day2 / 1000 + 3600
    assert sa.necklace_ad_served(days=7, path=path, today=today) == {
        ('cve-incident-brief', 'mcp'): 5, ('cve-incident-brief', 'a2a'): 1, ('topic-evidence-brief', 'mcp'): 4}
    assert sa.necklace_ad_served(days=1, path=path, today=today) == {
        ('cve-incident-brief', 'mcp'): 3, ('topic-evidence-brief', 'mcp'): 4}
    assert sa.necklace_ad_served(path=tmp_path / 'missing.jsonl') == {}


def test_no_project_root_means_no_file(monkeypatch):
    monkeypatch.delenv('AGENTCON_PROJECT_ROOT', raising=False)
    assert sa.necklace_log_path() is None and sa.necklace_ad_served() == {}
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', '/srv/project')
    assert str(sa.necklace_log_path()) == '/srv/project/logs/growth/necklace-ad-served.jsonl'


class _Slots:
    """Just enough of SponsoredSlots for the request path (memory only)."""
    taxonomy = {'technology': {}, 'research': {}}   # SITE_CATEGORIES: security -> technology
    regions = {'US': {}}
    store = None

    def cards(self, category, region, rebuild=False):
        return [{'id': 'camp-1', 'advertiser': 'Paper Finder Inc'}]


def _provider(tmp_path, monkeypatch, now):
    monkeypatch.setattr(sa, 'agent_block', lambda card, offer, category, region: {'label': 'Sponsored'})
    provider = sa.AgentOfferProvider(_Slots(), clock=lambda: now, url_check=lambda u: True,
                                     necklace_log=tmp_path / 'served.jsonl')
    provider._offers = {'camp-1': {'endpoint': 'https://mcp.example.org'}}
    return provider


def test_flush_writes_necklace_serves_even_when_the_table_is_not_ready(tmp_path, monkeypatch):
    now = 30 * DAY / 1000 + 10
    provider = _provider(tmp_path, monkeypatch, now)
    provider._counting = False                                   # table CHECK not widened: DB counts nothing
    ctx = dict(surface='mcp', tool='necklace', necklace='cve-incident-brief', category='security', region='US',
               counted=True, task='CVE-2026-0001')
    assert provider(ctx)['label'] == 'Sponsored'
    provider(dict(ctx, surface='a2a'))
    provider(dict(ctx, counted=False))                           # QA header or Early-Data: shown, not counted
    provider(dict(ctx, tool='search', necklace=None))            # not a necklace answer: not in this file
    assert provider._served == {}
    assert provider.flush_necklace() == 2
    line = json.loads((tmp_path / 'served.jsonl').read_text())
    assert line['counts'] == [
        {'day': '1970-01-31', 'surface': 'a2a', 'necklace': 'cve-incident-brief', 'category': 'technology', 'served': 1},
        {'day': '1970-01-31', 'surface': 'mcp', 'necklace': 'cve-incident-brief', 'category': 'technology', 'served': 1}]
    assert 'CVE-2026-0001' not in (tmp_path / 'served.jsonl').read_text()   # no task text kept
    assert provider.flush_necklace() == 0                        # nothing pending: no empty line
    assert len((tmp_path / 'served.jsonl').read_text().splitlines()) == 1


def test_a_failed_write_keeps_the_counts_for_the_next_flush(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, 30 * DAY / 1000)
    ctx = dict(surface='mcp', tool='necklace', necklace='cve-incident-brief', category='security', region='US',
               counted=True)
    provider(ctx)
    blocker = tmp_path / 'blocked'
    blocker.write_text('a file, not a folder')
    provider._necklace_log = blocker / 'served.jsonl'
    assert provider.flush_necklace() == 0
    provider(ctx)
    provider._necklace_log = tmp_path / 'served.jsonl'
    assert provider.flush_necklace() == 2


def test_necklace_serve_is_counted_and_flushed_with_the_impressions(p1_suite, tmp_path):  # noqa: F811
    """PG path as live_service runs it: the table gets mcp/a2a rows as before, the growth file gets the necklace."""
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.concierge import ad_slot
    from tests.test_ad_coin_v2_sponsored import NOW, slots_for
    from tests.test_ad_coin_v2_sponsored_offer import _approved_offer_suite
    pg, _campaign = _approved_offer_suite(p1_suite)
    log = tmp_path / 'logs/growth/necklace-ad-served.jsonl'
    provider = sa.AgentOfferProvider(slots_for(p1_suite), clock=lambda: NOW / 1000, necklace_log=log)
    assert provider.refresh() == 1
    ctx = ad_slot.necklace_context('mcp', 'topic-evidence-brief', headers={}, task='retrieval augmented generation')
    ctx['region'] = 'US'
    assert ctx['tool'] == 'necklace' and ctx['counted'] is True
    assert provider(ctx)['label'] == 'Sponsored'
    qa = ad_slot.necklace_context('mcp', 'topic-evidence-brief', headers={'x-agentcon-qa': 'check'})
    early = ad_slot.necklace_context('a2a', 'topic-evidence-brief', headers={'early-data': '1'})
    for skipped in (qa, early):
        skipped['region'] = 'US'
        assert skipped['counted'] is False and provider(skipped) is not None
    provider(dict(surface='mcp', tool='search', category='web_search', categories=['web_search'], region='US',
                  counted=True))
    assert provider.flush_now() == 2                             # table: the necklace answer and the search answer
    with unchecked(), pg.atomic():
        rows = pg.database.all("SELECT placement AS surface, served FROM adc2_sponsored_impressions")
    assert sum(int(r['served']) for r in rows) == 2
    [line] = [json.loads(t) for t in log.read_text().splitlines()]
    assert [(c['necklace'], c['surface'], c['served']) for c in line['counts']] == [('topic-evidence-brief', 'mcp', 1)]
    assert sa.necklace_ad_served(days=1, path=log, today=NOW / 1000) == {('topic-evidence-brief', 'mcp'): 1}


from tests.test_ad_coin_postgres import cluster  # noqa: E402,F401
from tests.test_ad_coin_v2_persistence import store  # noqa: E402,F401
from tests.test_ad_coin_v2_p1 import p1_suite  # noqa: E402,F401
from tests.test_ad_coin_v2_sponsored_offer import _public_only  # noqa: E402,F401  (no DNS in tests)


def test_without_the_root_variable_the_project_logs_folder_is_found_outside_pytest(tmp_path, monkeypatch):
    """11-17: the production frontend runs from the project folder without AGENTCON_PROJECT_ROOT."""
    from agent_market.ad_coin.v2 import paid_bookings
    monkeypatch.delenv('AGENTCON_PROJECT_ROOT', raising=False)
    (tmp_path / 'logs' / 'growth').mkdir(parents=True)
    monkeypatch.setattr(paid_bookings, 'data_path', lambda path: str(tmp_path / path))
    assert sa.necklace_log_path() is None                       # under pytest: never the real logs
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    assert sa.necklace_log_path() == tmp_path / 'logs/growth/necklace-ad-served.jsonl'
    monkeypatch.setattr(paid_bookings, 'data_path', lambda path: str(tmp_path / 'missing' / path))
    assert sa.necklace_log_path() is None                       # no logs/growth folder: nothing written
