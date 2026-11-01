import pytest

from agent_market.gateway import crawler as crawler_module
from agent_market.gateway.crawler import Crawler


def _crawler(pages, monkeypatch):
    monkeypatch.setattr(crawler_module.time, 'sleep', lambda seconds: None)
    crawler = Crawler.__new__(Crawler)
    crawler.should_stop = lambda: False
    calls = []

    def get(url, params):
        calls.append(params['offset'])
        return pages.pop(0)

    crawler._get = get
    return crawler, calls


def test_a_transient_empty_page_inside_the_total_is_fetched_once_more(monkeypatch):
    item = {'resource': 'https://a.example/x', 'accepts': []}
    crawler, calls = _crawler([{'items': [], 'pagination': {'total': 500}},
                               {'items': [item], 'pagination': {'total': 500}}], monkeypatch)
    records, position = crawler._x402_page({'position': 200})
    assert calls == [200, 200]
    assert position == 300


def test_a_repeated_empty_page_still_fails_without_advancing(monkeypatch):
    crawler, calls = _crawler([{'items': [], 'pagination': {'total': 500}}] * 2, monkeypatch)
    with pytest.raises(ValueError, match='incomplete_registry_page'):
        crawler._x402_page({'position': 200})
    assert calls == [200, 200]


def test_the_end_of_the_list_needs_no_retry(monkeypatch):
    crawler, calls = _crawler([{'items': [], 'pagination': {'total': 200}}], monkeypatch)
    assert crawler._x402_page({'position': 200}) == ([], None)
    assert calls == [200]
