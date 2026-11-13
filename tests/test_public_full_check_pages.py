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
    assert pfc.split(Timed(), 3.54) == {'server_s': 2.32, 'outside_s': 1.22, 'edge': 'LAX DYNAMIC'}

    class Untimed:
        headers = {'cf-ray': 'x-SEA'}
    assert pfc.split(Untimed(), 2.4) == {'server_s': None, 'outside_s': None, 'edge': 'SEA -'}
    assert pfc.split(None, 2.4) is None
