"""public_full_check pages (PM 11-12 01시): a new connection per page, and the path floor as reference only."""
import json
from datetime import datetime

from scripts import public_full_check as pfc


def test_path_floor_takes_the_nearest_minute_within_the_window(tmp_path, monkeypatch):
    log = tmp_path / 'net-path.jsonl'
    rows = [{'at': '2026-11-11 23:30:25', 'edge': {'total_s': 3.09, 'tls_s': 1.40}},
            {'at': '2026-11-11 23:31:28', 'edge': {'total_s': 0.81, 'tls_s': 0.48}}]
    log.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    monkeypatch.setattr(pfc, 'NET_PATH', log)
    at = datetime(2026, 11, 11, 23, 30, 40).timestamp()
    assert pfc.path_floor(at) == {'edge_s': 3.09, 'tls_s': 1.40, 'net_at': '2026-11-11 23:30:25'}
    assert pfc.path_floor(datetime(2026, 11, 11, 23, 40).timestamp()) is None


class Response:
    status_code = 200
    headers = {'content-type': 'text/plain', 'cf-ray': 'x-LAX', 'cf-cache-status': 'MISS'}
    text = ''


class Client:
    made = 0

    def __init__(self):
        Client.made += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, **kw):
        return Response()


def test_each_page_is_fetched_on_its_own_connection_and_slow_ones_carry_the_floor(monkeypatch):
    Client.made = 0
    monkeypatch.setattr(pfc, 'client', Client)
    monkeypatch.setattr(pfc, 'GAP', 0)
    monkeypatch.setattr(pfc, 'sitemap_pages', lambda c: ['/agent/1', '/agent/2'])
    monkeypatch.setattr(pfc, 'NAV', ['/', '/new/en/chat.html'])
    monkeypatch.setattr(pfc, 'SAMPLE', {'/agent/': 2})
    clock = iter([0.0, 2.5] * 10)  # every page takes 2.5 s
    monkeypatch.setattr(pfc.time, 'time', lambda: next(clock))
    monkeypatch.setattr(pfc, 'path_floor', lambda at=None: {'edge_s': 1.4, 'tls_s': 1.2, 'net_at': 'x'})
    run = pfc.Run()
    pfc.part_pages(run, Client())
    slow = [f for f in run.failures if f['check'].startswith('time ')]
    assert Client.made == 1 + 4  # the shared client passed in, plus one per page
    assert len(slow) == 4 and all(f['ref']['edge_s'] == 1.4 for f in slow)  # still failures: the verdict is unchanged


def test_sign_in_is_measured_at_both_addresses():
    # 11-12 PM 08:3x: our links now go straight to /customer/sign-in (65d9a599). The old address keeps its 303
    # for outside links and stays measured; its shortfall still counts. Both are first-visit page samples.
    from scripts import public_full_check as check
    assert '/new/en/sign-in.html' in check.NAV and '/customer/sign-in' in check.NAV
    assert '/customer/sign-in' not in check.SLOW_OK and '/new/en/sign-in.html' not in check.SLOW_OK


def test_a_finished_test_run_is_read_in_any_case_with_its_reference():
    # 11-12 17:02: the page said 'Latest test · failed'; the old pattern wanted 'Failed' and timed out after 30 s.
    from scripts import public_full_check as check
    body = 'Test result\nLatest test · failed\nSTATUS\nfailed\nSupport reference: ex_04439821bd57a053492130a7'
    status, done = check.test_outcome(check.TEST_DONE.search(body), body)
    assert status == 'failed (ex_04439821bd57a053492130a7)' and done is False
    body = 'Latest test · Completed\nSTATUS\nCompleted'
    assert check.test_outcome(check.TEST_DONE.search(body), body) == ('Completed', True)
    assert check.TEST_DONE.search('Checking the selected request…') is None


def test_an_agent_time_sample_carries_its_server_time_and_what_the_path_took(monkeypatch):
    """PM 11-13 20:2x: 18:31 chat 3.54 s had no server time, so the side that went over could not be named."""
    class Timed:
        headers = {'server-timing': 'server;dur=2320, step_search;dur=1527', 'cf-ray': 'x-LAX', 'cf-cache-status': 'DYNAMIC'}
    monkeypatch.setattr(pfc, 'path_floor', lambda: None)
    # PM 11-15 22:2x: the request's own segments stay, so a 12 s server time can be split afterwards
    assert pfc.split(Timed(), 3.54) == {'server_s': 2.32, 'outside_s': 1.22, 'edge': 'LAX DYNAMIC',
                                        'timing': {'server': 2320, 'step_search': 1527}}

    class Untimed:
        headers = {'cf-ray': 'x-SEA'}
    assert pfc.split(Untimed(), 2.4) == {'server_s': None, 'outside_s': None, 'edge': 'SEA -'}
    assert pfc.split(None, 2.4) is None


def test_browser_load_time_is_navigation_timing_not_the_fixed_wait():
    """PM 11-14: the verdict is loadEventEnd; the 1.2 s wait for the screen checks is not a load time."""
    import inspect
    from scripts import public_full_check as pfc
    assert pfc.load_time(1.234, 2.9) == 1.23            # the browser's own navigation timing wins
    assert pfc.load_time(None, 2.345) == 2.35 and pfc.load_time(0, 1.0) == 1.0   # wall time up to 'load' otherwise
    src = inspect.getsource(pfc.part_browser)
    measure, wait = src.index('nav = page.evaluate(NAV_LOAD_JS)'), src.index('page.wait_for_timeout(1200)')
    assert measure < wait < src.index('took = load_time(nav, wall)')
    assert "'old_with_wait_s'" in src and 'definition changed 11-14' in pfc.LOAD_DEFINITION
    assert pfc.OLD_LOAD_UNTIL == '2026-11-21'


def test_navigation_timing_in_a_real_browser():
    import pytest
    playwright = pytest.importorskip('playwright.sync_api')
    from scripts import public_full_check as pfc
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<html><body>ok</body></html>')
        page.goto('data:text/html,<p>ok</p>', wait_until='load')
        nav = page.evaluate(pfc.NAV_LOAD_JS)
        browser.close()
    assert nav is None or 0 < nav < 5


def test_a_slow_sample_keeps_its_own_steps_and_the_load(monkeypatch):
    """PM 11-16 18:1x: a 13.87 s HIT at 17:29 could not be told apart (path, TLS or the check itself) afterwards."""
    class Traced:
        def request(self, method, url, **kw):
            trace = kw['extensions']['trace']
            for name in ('connection.connect_tcp.complete', 'connection.start_tls.complete',
                         'http11.send_request_headers.started', 'http11.receive_response_headers.complete',
                         'http11.receive_response_body.complete'):
                trace(name, {})
            resp = Response()
            resp.headers = {'cf-ray': 'x-LAX', 'cf-cache-status': 'HIT'}
            return resp
    clock = iter([0.0, 0.1, 0.4, 0.5, 0.8, 0.9, 1.0])
    monkeypatch.setattr(pfc, 'GAP', 0)
    monkeypatch.setattr(pfc.time, 'time', lambda: next(clock))
    monkeypatch.setattr(pfc.os, 'getloadavg', lambda: (6.87, 5.0, 4.0))
    monkeypatch.setattr(pfc, 'path_floor', lambda: None)
    took, r, err = pfc.timed(Traced(), 'GET', 'https://example.test/x')
    assert (took, err) == (1.0, None)
    ref = pfc.split(r, took)
    assert ref['phases'] == {'tcp_s': 0.1, 'tls_s': 0.4, 'first_byte_s': 0.8, 'body_end_s': 0.9, 'requests': 1,
                             'body_s': 0.1, 'load_1': 6.87}
    assert ref['edge'] == 'LAX HIT'  # the verdict and the other fields are unchanged


def test_a_bad_path_is_marked_and_remeasured_beside_the_verdict(monkeypatch):
    """PM 11-16 20:4x: a run whose TLS median is over 0.6 s is a bad path; its slow pages are measured once more (at most
    20, one at a time) and this Mac's loss is kept, all in record['path'] only (no sample dropped or replaced)."""
    run = pfc.Run()
    run.tls = [1.1, 1.2, 0.3]
    for i in range(25):
        run.ok('pages', f'time /p{i}', False, '2s', 2.0)
    run.ok('api', 'explore time', False, '3s', 3.0)
    before = [dict(f) for f in run.failures]
    calls = []
    monkeypatch.setattr(pfc, 'REMEASURE_GAP', 0)
    monkeypatch.setattr(pfc, 'client', Client)
    monkeypatch.setattr(pfc, 'gateway', lambda: '192.0.2.1')
    monkeypatch.setattr(pfc, 'ping', lambda host: {'host': host, 'loss_pct': 0.0, 'avg_ms': 3.5})

    def fake_timed(c, method, url, **kw):
        calls.append(url)
        return 0.8, Response(), None
    monkeypatch.setattr(pfc, 'timed', fake_timed)
    ref = pfc.path_reference(run)
    assert ref['tls_median_s'] == 1.1 and ref['bad'] is True and ref['tls_samples'] == 3
    assert [p['host'] for p in ref['ping']] == ['192.0.2.1', '1.1.1.1']
    assert len(calls) == 20 and calls[0].endswith('/p0') and len(ref['remeasured']) == 20
    assert ref['remeasured'][0] == {'path': '/p0', 's': 0.8, 'edge': 'LAX MISS', 'err': None, 'tls_s': None}
    assert run.failures == before and run.checks == 26   # the verdict keeps the first values

    good = pfc.Run()
    good.tls = [0.3, 0.32]
    good.ok('pages', 'time /slow', False, '2s', 2.0)
    calls.clear()
    ref = pfc.path_reference(good)
    assert ref['bad'] is False and 'remeasured' not in ref and calls == []


def test_ping_reads_loss_and_round_trip(monkeypatch):
    class Done:
        stdout = ('--- 1.1.1.1 ping statistics ---\n20 packets transmitted, 19 packets received, 5.0% packet loss\n'
                  'round-trip min/avg/max/stddev = 3.4/3.52/3.6/0.05 ms\n')
    monkeypatch.setattr(pfc.subprocess, 'run', lambda *a, **k: Done())
    assert pfc.ping('1.1.1.1') == {'host': '1.1.1.1', 'loss_pct': 5.0, 'avg_ms': 3.52}


def test_a_failed_check_names_its_time_and_the_full_cf_ray_of_the_last_response(monkeypatch):
    """R2 (PM 11-18): so a failure can be matched to Cloudflare and origin logs. The ray is the full '<id>-<airport>'
    of the last response this process read; before any response it is empty."""
    class Headers(dict):
        def get(self, key, default=''):
            return super().get(key, default)

    class Fake:
        status_code, text = 200, ''
        headers = Headers({'cf-ray': '9f1a2b3c4d5e6f70-ICN'})

    class Client:
        def request(self, method, url, **kw):
            return Fake()
    monkeypatch.setattr(pfc, 'GAP', 0)
    monkeypatch.setitem(pfc._LAST, 'ray', '')
    run = pfc.Run()
    run.ok('pages', 'first', False, 'before any response')
    pfc.timed(Client(), 'GET', 'https://agentconcierge.biz/')
    run.ok('pages', 'second', False, 'after a response')
    run.ok('pages', 'fine', True)
    first, second = run.failures
    assert first['last_ray'] == '' and second['last_ray'] == '9f1a2b3c4d5e6f70-ICN'
    assert len(first['at']) == 8 and first['at'][2] == ':' and second['at'][5] == ':'
