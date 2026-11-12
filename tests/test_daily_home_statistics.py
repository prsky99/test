"""Daily, crawlable statistics must remain factual, bounded and restart-safe."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.daily_statistics import DailyStatistics, KEY, ZONE, description, valid
from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.public_metadata import PAGES, apply_daily_home, graph, sitemap
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'reports/daily-home-statistics-seo-2026-10-26'


def snapshot(at=None, count=12345):
    at = at or datetime.now(timezone.utc)-timedelta(seconds=1)
    return dict(day=at.astimezone(ZONE).date().isoformat(), captured_at=at.isoformat(),
                modified_at=at.isoformat(), cataloged=count, reachable=count-3,
                with_status_check=count-1, a2a=count-10, mcp=7, x402=3)


def raw(value):
    return dict(captured_at_utc=value['captured_at'],
                **{k:value[k] for k in ('cataloged','reachable','with_status_check')},
                by_protocol=[{'kind':k,'n':value[k]} for k in ('a2a','mcp','x402')])


def test_restart_and_next_kst_day_preserve_modified_time_until_counts_change(tmp_path):
    store = Store(str(tmp_path/'daily.db'))
    # 23:59:59 and 00:00:01 Korea are the same UTC calendar day.
    at = datetime.now(timezone.utc).replace(hour=14, minute=59, second=59, microsecond=0)-timedelta(days=2)
    clock = [at]
    calls = []
    def collect(_):
        calls.append(1)
        return raw(snapshot(clock[0], count=12345 if len(calls)<3 else 12346))
    daily = DailyStatistics(store, clock=lambda:clock[0], collect=collect)
    daily._refresh()
    first = daily.peek()
    restarted = DailyStatistics(store, clock=lambda:clock[0], collect=collect)
    restarted._refresh()
    assert restarted.peek() == first and len(calls) == 1
    clock[0] += timedelta(seconds=2)
    restarted._refresh()
    second = restarted.peek()
    assert second['day'] != first['day'] and second['captured_at'] != first['captured_at']
    assert second['modified_at'] == first['modified_at'] and len(calls) == 2
    clock[0] += timedelta(days=1)
    restarted._refresh()
    third = restarted.peek()
    assert third['cataloged'] == 12346 and third['modified_at'] == third['captured_at']
    assert store.get_meta(KEY) == third


def test_sixteen_requests_share_one_bounded_background_refresh(tmp_path):
    store = Store(str(tmp_path/'parallel.db'))
    release = threading.Event()
    calls = []
    value = snapshot()
    def collect(_):
        calls.append(1)
        release.wait(3)
        return raw(value)
    daily = DailyStatistics(store, collect=collect)
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _:daily.read(.01), range(16)))
        assert results == [None]*16 and time.monotonic()-started < 1
        assert len(calls) == 1
    finally:
        release.set()
    deadline = time.monotonic()+3
    while daily.peek() is None and time.monotonic()<deadline:
        time.sleep(.01)
    assert daily.read() == value and len(calls) == 1


def test_failure_retains_original_snapshot_date_and_retries_are_bounded(tmp_path):
    store = Store(str(tmp_path/'fallback.db'))
    previous = snapshot(datetime.now(timezone.utc)-timedelta(days=2))
    store.set_meta(KEY, previous)
    calls = []
    def fail(_):
        calls.append(1)
        raise RuntimeError('private diagnostic must not be published')
    daily = DailyStatistics(store, collect=fail)
    assert daily.read(.25) == previous
    for _ in range(10):
        assert daily.read() == previous
    assert calls == [1]
    rendered = apply_daily_home((ROOT/'new/en/index.html').read_text(), previous)
    assert previous['day'] in rendered and 'private diagnostic' not in rendered


@pytest.mark.parametrize('mutate', [
    lambda v:v.update(cataloged=True), lambda v:v.update(reachable=v['cataloged']+1),
    lambda v:v.update(a2a=-1), lambda v:v.update(secret='never exposed'),
    lambda v:v.update(captured_at=v['captured_at'].replace('T','"')),
    lambda v:v.update(day='<script>alert(1)</script>'),
    lambda v:v.update(modified_at='2099-01-01T00:00:00+00:00'),
    lambda v:v.update(cataloged=10**15),
])
def test_invalid_or_private_stored_data_cannot_enter_metadata(mutate):
    value = snapshot()
    mutate(value)
    assert not valid(value)
    source = (ROOT/'new/en/index.html').read_text()
    assert apply_daily_home(source, value) == source
    assert '<lastmod>' not in sitemap('https://agentconcierge.biz', value)


def test_corrupt_persistence_can_be_repaired(tmp_path):
    store = Store(str(tmp_path/'corrupt.db'))
    with store.tx() as db:
        db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)',(KEY,'broken-json'))
    value = snapshot()
    daily = DailyStatistics(store, collect=lambda _:raw(value))
    assert daily.read(.25) == value


@pytest.fixture
def daily_app(tmp_path):
    store = Store(str(tmp_path/'app.db'))
    value = snapshot()
    store.set_meta(KEY, value)
    front = Front(store, allow_private=True)
    assert front.daily_statistics.read(.25) == value
    with TestClient(create_front_app(front)) as client:
        yield client, value


def test_crawlers_receive_matching_visible_meta_and_dataset_without_javascript(daily_app):
    client, value = daily_app
    for route in ('/', '/new/en/index.html'):
        response = client.get(route, headers={'accept':'text/html','user-agent':'Googlebot'})
        assert response.status_code == 200
        body = response.text
        for key in ('description','og:description','twitter:description'):
            assert re.search(r'<meta (?:name|property)="'+key+r'" content="([^"]*)"',body)[1] == description(value).replace('&','&amp;')
        ld = json.loads(re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',body,re.S)[1])
        dataset = next(n for n in ld['@graph'] if n['@type']=='Dataset')
        assert {n['propertyID']:n['value'] for n in dataset['variableMeasured']} == {k:value[k] for k in ('cataloged','reachable','with_status_check','a2a','mcp','x402')}
        assert dataset['temporalCoverage'] == value['captured_at']
        assert '<section id="daily-catalog-statistics"' in body and '12,345' in body
        assert 'does not guarantee task completion' in body
        assert "script-src 'self' 'sha256-" in response.headers['content-security-policy']
        assert 'stale-while-revalidate=600' in response.headers['cache-control']  # 11-11 PM decision A
        assert not re.search(r'[\uac00-\ud7af]',body)
    xml = ET.fromstring(client.get('/sitemap.xml').text)
    dates = xml.findall('.//{*}lastmod')
    assert len(dates)==1 and dates[0].text==value['modified_at']
    explore = client.get('/new/en/explore.html').text
    assert PAGES['explore'][2] in explore
    ld = json.loads(re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',explore,re.S)[1])
    assert not any(n['@type']=='Dataset' for n in ld['@graph'])
    assert 'id="dailyHomeMetadata"' in explore


def test_static_metadata_fallback_has_no_fake_dates_or_counts():
    assert not any(n['@type']=='Dataset' for n in graph()['@graph'])
    assert '<lastmod>' not in sitemap('https://agentconcierge.biz')


@pytest.mark.parametrize('entry', ['/', '/new/en/explore.html'])
def test_browser_navigation_preserves_daily_home_metadata_and_layout(browser, daily_app, entry):
    client, value = daily_app
    context = browser.new_context(viewport={'width':1440,'height':1000})
    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            route.abort()
            return
        response = client.request(request.method,url.path+('?' + url.query if url.query else ''),
                                  content=request.post_data,headers={'accept':request.headers.get('accept','')})
        route.fulfill(status=response.status_code,body=response.content,
                      headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page = context.new_page()
    errors = []
    page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto('https://agentconcierge.biz'+entry)
        page.wait_for_function('typeof updatePageMeta === "function"')
        # Follow the visible navigation controls, including the return to Home.
        page.locator('header .brand-box').click()
        page.wait_for_function('document.querySelector("meta[name=description]").content.includes("12,345")')
        assert page.locator('#daily-catalog-statistics').is_visible()
        REPORT.mkdir(exist_ok=True)
        label = 'root' if entry=='/' else 'from-explore'
        page.screenshot(path=str(REPORT/f'home-daily-{label}-desktop.png'),full_page=True)
        page.locator('#navTabs [data-tab=explore]').click()
        assert page.locator('meta[name=description]').get_attribute('content') == PAGES['explore'][2]
        assert '"@type":"Dataset"' not in page.locator('script[type="application/ld+json"]').inner_text()
        page.locator('header .brand-box').click()
        assert page.locator('meta[name=description]').get_attribute('content') == description(value)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(REPORT/f'home-daily-{label}-mobile.png'),full_page=True)
        assert not errors
    finally:
        context.close()


def test_home_snapshot_is_collapsed_until_opened():
    from agent_market.concierge.public_metadata import daily_home_text
    value = snapshot()
    page = daily_home_text('<section id="secOverview"></section>', value)
    block = page[page.index('<section id="daily-catalog-statistics"'):page.index('</section>', page.index('<section id="daily-catalog-statistics"'))]
    # Only the summary line shows; the figures stay in the document and open on request.
    assert '<details class="daily-snapshot">' in block and ' open' not in block.split('>')[1]
    assert '<summary' in block and value['day'] in block and '12,345' in block
