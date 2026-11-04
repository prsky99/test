"""Five-point step 8: an empty or failed Explore search offers its next action in the results area."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'new/en/assets/operating.js').read_text()


def test_empty_search_offers_fewer_words_no_filters_and_chat():
    body = JS.split('function exploreEmptyState(q) {', 1)[1].split('\n}\n', 1)[0]
    assert 'Remove filters' in body and 'Search \u201c' in body and 'Ask Chat to recommend' in body
    # The visitor's words are set as text, never as markup.
    assert 'innerHTML' not in body and 'textContent' in body
    assert 'if (!items.length && !isReportFilter) $("xResults").replaceChildren(exploreEmptyState(q));' in JS


def test_failed_search_keeps_a_retry_in_place():
    branch = JS.split('const error=document.createElement("p");error.className="explore-search-error"', 1)[1][:600]
    assert '"Try again"' in branch and 'loadExplore(true,false,true)' in branch and 'role","alert"' in branch


def test_actions_meet_the_touch_target():
    css = (ROOT / 'new/en/assets/pearl-live.css').read_text()
    assert 'body #xResults .explore-empty .btn{min-height:44px}' in css


def test_dark_chat_submit_keeps_a_dark_label():
    css = (ROOT / 'new/en/assets/pearl-live.css').read_text()
    rule = 'body[data-theme="dark"] #chatSubmit,body[data-theme="dark"] #chatSubmit :is(span,svg){color:#0b1a1f}'
    assert rule in css and css.index(rule) > css.index('body[data-theme="dark"] .btn.primary,body[data-theme="dark"] .btn.primary :is(span,svg){color:#fff}')
