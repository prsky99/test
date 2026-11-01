"""Round 20 survey: hidden or unreachable content on the admin screens (records findings per tab)."""
# ruff: noqa: F401,F811
import json
from pathlib import Path

import pytest
from tests.test_admin_security_browser import admin_page
from tests.test_front_workflow_browser import browser

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')
ROOT = Path(__file__).resolve().parents[1]
AUDIT = '\n'.join(line for line in (ROOT / 'tests/data/screen_hidden_audit.js').read_text().splitlines()
                  if not line.startswith('//')).strip()
PROOF = ROOT / 'reports/screen-hidden-audit-2026-11-01/admin'


def test_admin_tabs_hidden_content_survey(admin_page):
    page, errors, external = admin_page
    page.wait_for_function('() => !refreshInFlight && Boolean(state.overview)')
    tabs = page.evaluate("() => [...document.querySelectorAll('[data-tab]')].filter(e => e.getClientRects().length).map(e => e.dataset.tab)")
    PROOF.mkdir(parents=True, exist_ok=True)
    summary = {}
    for tab in dict.fromkeys(tabs):
        page.locator('[data-tab="' + tab + '"]').first.click()
        page.wait_for_timeout(700)
        found = page.evaluate(AUDIT)
        (PROOF / (tab + '.json')).write_text(json.dumps(found, indent=1, ensure_ascii=False))
        summary[tab] = {key: len(value) for key, value in found.items() if value}
    (PROOF / 'summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    assert tabs and not external
