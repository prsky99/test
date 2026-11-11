"""scripts/warm_edge.py finds every bundle and versioned asset a public page names."""
from scripts import warm_edge


def test_assets_of_a_page_are_its_versioned_bundles_and_files():
    page = ('<link rel="stylesheet" href="/new/en/assets/bundle.css?f=tokens,styles&amp;v=abc">'
            '<script src="/new/en/assets/bundle.js?f=app&amp;v=def" defer></script>'
            '<img src="/new/en/assets/pearl.webp?v=123"><a href="/new/en/assets/plain.css">')
    assert warm_edge.assets_of(page) == ['/new/en/assets/bundle.css?f=tokens,styles&v=abc',
                                         '/new/en/assets/bundle.js?f=app&v=def', '/new/en/assets/pearl.webp?v=123']


def test_the_pages_are_the_public_live_pages_and_the_request_is_a_first_visit():
    assert '/' in warm_edge.PAGES and len(warm_edge.PAGES) == 10
    assert 'text/html' in warm_edge.HEADERS['Accept'] and 'Cookie' not in warm_edge.HEADERS
