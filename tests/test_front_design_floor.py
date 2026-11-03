"""Web award stage 4: a 12px text floor, 24px checkboxes, access facts on cards and folding phone filters."""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'new/en/assets'
CSS = (ASSETS / 'pearl-live.css').read_text()
UI = (ASSETS / 'pearl-ui.js').read_text()


def test_the_last_shared_stylesheet_lifts_every_small_text_rule_to_12px():
    floor = CSS[CSS.index('/* Web award stage 4 (2026-11-02)'):]
    for selector in ('body .chip', 'body .kind-badge', 'body th', 'body .ux-agent-category', 'body .eyebrow',
                     'body #secExplore .pearl-search-results .acard .m .chip', 'body .pearl-example-state'):
        assert selector in floor
    for size in ('10px', '10.5px', '11px', '11.5px'):
        assert f'body [style*="font-size:{size}"]' in floor and f'body [style*="font-size: {size}"]' in floor
    assert not re.search(r'font-size:\s*1[01](\.5)?px', floor.split('*/', 1)[1].replace('[style*="font-size', ''))
    assert 'body .pearl-menu-page input[type=checkbox]' in floor and 'height:24px!important' in floor


def test_cards_always_show_access_and_x402_price():
    facts = UI[UI.index("if(item.catalog_status==='historical')items.push"):UI.index("facts.replaceChildren")]
    assert "if(item.auth_required===0&&item.kind!=='x402')items.push(['No account required',''])" in facts
    assert "usd(item.price_usdc)+' per call'" in facts and '!items.length' not in facts


def test_phone_filters_fold_behind_one_labelled_button():
    fold = UI[UI.index("// Phones: category, evidence filters and common tasks fold"):]
    fold = fold[:fold.index('})();') + 5]
    assert "matchMedia('(max-width:700px)')" in fold and "aria-controls" in fold and "aria-expanded" in fold
    assert "' filters and common tasks'" in fold and "' on)'" in fold


def test_wide_workflow_screens_reserve_one_line_for_the_selected_name():
    tail = CSS[CSS.index('item 13 (2026-11-02)'):]
    assert '@media(min-width:1100px){body #secWorkflows #frontWfActiveName{min-height:36px}' in tail
    assert 'body #secWorkflows #pearlWorkflowDescription{min-height:45px' in tail
