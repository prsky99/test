"""Round 20: no screen hides content or controls that scrolling cannot reach (UI policy 11-01).

Every public page, a Chat page with results, and the customer workspace pages are checked
at desktop and phone widths with tests/data/screen_hidden_audit.js. Findings are written to
reports/screen-hidden-audit-2026-11-01/ so the round report can quote them.
"""
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_front_first_entry_browser import cold_page, ORIGIN  # noqa: F401
from tests.test_owned_data_agents_activation import operating  # noqa: F401
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_workspace_entry_progress_browser import entry_page
from tests.test_workspace_prelaunch_browser import (  # noqa: F401
    customer_flow, typed_release_world, typed_world, routing,
)

ROOT = Path(__file__).resolve().parents[1]
AUDIT = '\n'.join(line for line in (ROOT / 'tests/data/screen_hidden_audit.js').read_text().splitlines()
                  if not line.startswith('//')).strip()
PROOF = ROOT / 'reports/screen-hidden-audit-2026-11-01'
PUBLIC = ['index', 'agent-status', 'explore', 'learn', 'test', 'workflows', 'chat', 'list-agent', 'about']


def audit(page, name):
    found = page.evaluate(AUDIT)
    PROOF.mkdir(parents=True, exist_ok=True)
    (PROOF / (name + '.json')).write_text(json.dumps(found, indent=1, ensure_ascii=False))
    return found


def assert_clear(found):
    problems = {key: value for key, value in found.items() if value}
    assert not problems, json.dumps(problems, indent=1, ensure_ascii=False)[:3000]


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('name', PUBLIC)
def test_public_pages_hide_nothing(cold_page, name, width):  # noqa: F811
    page, _, _, _, _, _, errors, _ = cold_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(ORIGIN + '/new/en/' + name + '.html', wait_until='networkidle')
    page.wait_for_timeout(300)
    assert_clear(audit(page, name + '-' + str(width)))
    assert not errors


@pytest.mark.parametrize('width', [1440, 390])
def test_chat_results_reach_the_end_by_page_scroll(cold_page, width):  # noqa: F811
    page, _, _, _, _, _, errors, _ = cold_page
    page.set_viewport_size({'width': width, 'height': 800})
    page.goto(ORIGIN + '/new/en/chat.html', wait_until='networkidle')
    for task in ['Find research sources', 'Find documentation', 'Find technology news']:
        page.locator('#chatInput').fill(task)
        page.locator('#chatSubmit').click()
        expect(page.locator('#chatSubmit')).to_be_enabled()
    expect(page.locator('.chat-recommendation').first).to_be_visible()
    messages = page.locator('#chatMessages')
    # Results flow with the page: the log itself never needs its own scroll bar.
    assert messages.evaluate('(n)=>n.scrollHeight<=n.clientHeight+2')
    last = page.locator('.chat-recommendation').last
    last.scroll_into_view_if_needed()
    expect(last).to_be_in_viewport()
    # Wheel over the results moves the page itself (no nested box swallows it).
    box = last.bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + 10)
    before = page.evaluate('scrollY')
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(300)
    assert page.evaluate('scrollY') > before or page.evaluate('scrollY + innerHeight >= document.documentElement.scrollHeight - 4')
    assert_clear(audit(page, 'chat-results-' + str(width)))
    assert not errors


@pytest.mark.parametrize('width', [1440, 390])
def test_workspace_pages_hide_nothing(customer_flow, browser, width):  # noqa: F811
    x = customer_flow
    context, page, errors, _ = entry_page(x, browser, width)
    pages = {
        'workspaces': '/customer/workspaces',
        'overview': '/customer/organizations',
        'flows': '/customer/organizations/' + x.ws + '/flows',
        'connections': '/customer/organizations/' + x.ws + '/connections',
        'plan': '/customer/plan',
        'support': '/customer/support',
    }
    try:
        for name, path in pages.items():
            page.goto('https://customer.test' + path)
            expect(page.locator('body')).not_to_have_attribute('data-workspace-loading', 'true')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(300)
            assert_clear(audit(page, 'workspace-' + name + '-' + str(width)))
        assert not errors
    finally:
        context.close()
