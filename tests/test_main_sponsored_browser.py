"""11-11 Sponsored on main Explore and Chat (docs/AD_COIN_SPONSORED_CONTRACT.md, PM rules).

Labelled and separate from results and answers; requested only after results are shown, without the query,
cookies or ids; nothing drawn when no card is booked, on errors or when the switch is off; quality bar kept."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright import sync_api as playwright

from tests.test_single_agent_chat_browser import chat_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

AUDIT_JS = (Path(__file__).resolve().parents[1] / 'scripts/ui_audit.js').read_text()
SHOTS = Path(__file__).resolve().parents[1] / 'reports/sponsored-main-2026-11-11'
CARD = {'id': 'cmp_1', 'label': 'Sponsored', 'advertiser': 'Research Agent Co',
        'text': 'Weather data for agents: hourly forecasts and alerts with a free tier.'}


def sponsor(page, cards, status=200):
    seen = []
    def answer(route):
        seen.append({'query': parse_qs(urlsplit(route.request.url).query), 'headers': dict(route.request.headers)})
        route.fulfill(status=status, content_type='application/json', body=json.dumps(
            {'label': 'Sponsored', 'disclosure': 'Sponsored by the advertiser. Ads never change which agents are recommended.',
             'reward': None, 'placement': 'explore', 'cards': cards}))
    page.route('**/api/ad-coin/v2/sponsored*', answer)
    return seen


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
def test_explore_and_chat_show_booked_sponsored_cards_apart_from_results(chat_page, monkeypatch):  # noqa: F811
    page, requests, bodies, errors, best = chat_page
    monkeypatch.setenv('MAIN_SPONSORED', '1')
    seen = sponsor(page, [CARD])
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.goto('https://agentconcierge.biz/#explore')
    box = page.locator('.pearl-sponsored[data-placement="explore"]')
    playwright.expect(box).to_be_visible()
    playwright.expect(box).to_contain_text('Sponsored')
    playwright.expect(box).to_contain_text('Research Agent Co')
    playwright.expect(box).to_contain_text('Ads never change which agents are recommended')
    assert page.locator('#xResults .pearl-sponsored').count() == 0  # never inside the result list
    assert page.evaluate("document.getElementById('xResults').nextElementSibling.classList.contains('pearl-sponsored')")
    query = seen[0]['query']
    assert set(query) == {'placement', 'category', 'limit'} and query['placement'] == ['explore']
    assert 'cookie' not in {k.lower() for k in seen[0]['headers']}
    box.scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / 'explore-with-booking-1280.png'))
    m = page.evaluate(AUDIT_JS)
    assert not any(m[k] for k in ('small_targets', 'overlaps', 'misaligned', 'contrast_failures')), {k: m[k] for k in ('small_examples', 'overlap_examples', 'misaligned_examples', 'contrast_examples')}

    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('free MCP weather agent')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatMessages .chat-recommendation').first).to_be_visible()
    chat_box = page.locator('.pearl-sponsored[data-placement="chat"]')
    playwright.expect(chat_box).to_be_visible()
    assert page.locator('#chatMessages .chat-bubble .pearl-sponsored').count() == 0  # never inside the answer
    assert any(s['query']['placement'] == ['chat'] for s in seen)
    assert not any('free' in json.dumps(s['query']) for s in seen)  # the question is never sent
    chat_box.scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / 'chat-with-booking-1280.png'))
    assert not errors


@pytest.mark.parametrize('chat_page', ['published'], indirect=True)
@pytest.mark.parametrize('case', ['empty', 'error', 'switch_off'])
def test_nothing_is_drawn_without_a_booking_or_when_off(chat_page, monkeypatch, case):  # noqa: F811
    page, requests, bodies, errors, best = chat_page
    if case != 'switch_off':
        monkeypatch.setenv('MAIN_SPONSORED', '1')
    else:
        monkeypatch.delenv('MAIN_SPONSORED', raising=False)
    seen = sponsor(page, [] if case == 'empty' else [CARD], status=500 if case == 'error' else 200)
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.add_init_script("""window.__cls=0;new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__cls+=e.value}).observe({type:'layout-shift',buffered:true});""")
    page.goto('https://agentconcierge.biz/#explore')
    playwright.expect(page.locator('#xResults .acard').first).to_be_visible()
    page.wait_for_timeout(900)
    assert page.locator('.pearl-sponsored').count() == 0
    assert (len(seen) == 0) if case == 'switch_off' else (len(seen) >= 1)
    if case == 'empty':
        page.screenshot(path=str(SHOTS / 'explore-without-booking-1280.png'))
    assert not errors
