"""Explore announces search results and Chat offers a next step when nothing matches (web award stage 2)."""
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / 'new/en/assets/operating.js').read_text()


def body(name):
    start = SCRIPT.index(name)
    return SCRIPT[start:start + 1600]


def test_explore_status_line_reports_how_many_agents_a_search_shows():
    found = body('function exploreFoundText(')
    assert 'agents' in found and 'shown for' in found and 'if (!q) return ""' in found
    assert 'exploreFoundText(resultsEl.querySelectorAll(".acard:not(.skeleton-card)").length, q)' in SCRIPT
    # The status line it fills is the live region screen readers hear.
    assert 'id="uxExploreStatus" class="caption" role="status" aria-live="polite"' in (
        Path(__file__).resolve().parents[1] / 'new/en/explore.html').read_text()


def test_desktop_search_brings_results_into_view_without_taking_focus_from_the_box():
    branch = body('} else if (userInitiated && !isLoadMore && $("xTitle").getBoundingClientRect().top > innerHeight * 0.6)')
    assert 'scrollIntoView' in branch and 'prefers-reduced-motion: reduce' in branch
    assert '.focus(' not in branch.split('}', 1)[0]


def test_chat_without_a_match_offers_to_edit_the_same_request():
    branch = body('if (outcome === "no_eligible_match") {')
    assert 'Edit this request' in branch and 'requestNote.dataset.request' in branch and '$("chatInput")' in branch
    assert 'question.dataset.request=String(contentText??"").slice(0,500);' in SCRIPT
    assert 'Browse unverified listings in Explore' in SCRIPT
