"""The Explore screen asks for 15 listings first and 45 more per Load more (11-12 PM decision (a)).

Measured 11-12 (public address, new connection, 30 each): 45 listings were 5.0 KB compressed and
p50 1.91 s, 10 listings 2.1 KB and p50 1.76 s; the server builds fewer cards for a smaller page."""
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'new' / 'en' / 'assets' / 'operating.js'


def test_first_page_is_small_and_load_more_adds_a_full_page():
    text = SOURCE.read_text()
    assert re.search(r'const EXPLORE_FIRST_PAGE = 15, EXPLORE_MORE_PAGE = 45;', text)
    assert 'const requestLimit = Math.min(isLoadMore ? EXPLORE_MORE_PAGE : EXPLORE_FIRST_PAGE,300-offset);' in text
    assert 'currentExploreLimit + EXPLORE_MORE_PAGE' in text
    assert 'Math.min(45,300-offset)' not in text
