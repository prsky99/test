"""public_full_check judges the explore API by the explore target (final 2 s, interim 3 s noted), not the 1 s page
target (PM 11-16 04:3x: the 03:53 check failed 'send email 232' at 1.45 s)."""
from scripts import public_full_check as pfc


class Response:
    status_code = 200
    headers = {}

    def json(self):
        return {'total': 3, 'items': []}


class Run:
    def __init__(self):
        self.rows = {}

    def ok(self, part, name, cond, detail='', took=None, ref=None):
        self.rows[name] = (cond, detail)


def judge(monkeypatch, explore_s):
    def timed(c, method, url, **kw):
        return (explore_s if url.endswith('/api/explore') else 0.1), Response(), None
    monkeypatch.setattr(pfc, 'timed', timed)
    run = Run()
    pfc.part_api(run, None)
    return run.rows['explore time']


def test_the_explore_api_uses_the_explore_target_not_the_page_target(monkeypatch):
    assert pfc.PAGE_S == 1.0 and pfc.EXPLORE_S == 2.0 and pfc.EXPLORE_INTERIM_S == 3.0
    ok, detail = judge(monkeypatch, 1.45)
    assert ok and detail.endswith(': 1.45s')


def test_over_the_final_target_fails_and_says_where_it_stands_against_the_interim(monkeypatch):
    ok, detail = judge(monkeypatch, 2.4)
    assert not ok and detail.endswith('2.4s > 2.0s (within interim 3.0s)')
    ok, detail = judge(monkeypatch, 3.2)
    assert not ok and detail.endswith('3.2s > 2.0s (over interim 3.0s)')
