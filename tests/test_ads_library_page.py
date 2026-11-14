"""Public ad library /ads/library (agent ad plan, PM 11-14): current and past placements with advertiser, payer,
dates, text and why shown; rendered here, data and route from the AD Coin side; never imports ad_coin."""
import ast
import json
import re
from pathlib import Path

from agent_market.concierge import ads_library_page as lib

ROWS = [{'campaign_id': 'c1', 'advertiser': 'Acme Weather', 'paid_by': 'Acme Inc.', 'task_category': 'research',
         'region': 'US', 'starts': '2026-11-19', 'ends': '2026-11-19', 'state': 'running',
         'text': 'Sponsored: Free 100 calls a day.', 'why_shown': 'Booked for the research task category in US.',
         'surfaces': ['explore', 'chat', 'mcp'], 'offer': {'tool': 'forecast', 'endpoint': 'https://acme.example/mcp',
                                                            'free_trial': '100 calls a day', 'secret': 'x'}},
        {'campaign_id': 'c0', 'advertiser': '<b>Old</b>', 'state': 'ended', 'starts': '2026-11-01', 'text': 'Old ad'},
        {'campaign_id': '', 'advertiser': 'No id'}, 'junk']


def text(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', value))


def test_current_and_past_rows_with_payer_dates_text_and_reason():
    page = lib.page_html(ROWS)
    t = text(page)
    for expected in ('Running and booked (1)', 'Past placements (1)', 'Acme Inc.', '2026-11-19 to 2026-11-19',
                     'research · US', 'explore, chat, mcp', 'Sponsored: Free 100 calls a day.', 'Booked for the research',
                     'Free trial', '100 calls a day', 'ads=none', 'never inside them'):
        assert expected in t, expected
    assert '<b>Old</b>' not in page and '&lt;b&gt;Old&lt;/b&gt;' in page
    assert 'href="/methodology"' in page and 'href="/advertise"' in page and 'No id' not in t
    for word in ('guaranteed', '#1', ' best '):
        assert word not in t


def test_machine_view_keeps_known_fields_only_and_empty_states_read_plainly():
    data = lib.machine(ROWS, updated='2026-11-19T00:00:00Z')
    json.dumps(data)
    assert [r['campaign_id'] for r in data['current']] == ['c1'] and [r['campaign_id'] for r in data['past']] == ['c0']
    assert 'secret' not in data['current'][0]['offer'] and data['rules']['changes_results'] is False
    empty = text(lib.page_html([]))
    assert 'No placement is running or booked right now.' in empty and 'No past placements yet.' in empty


def test_renderer_never_imports_the_ad_side_and_the_page_is_kept_ten_minutes():
    tree = ast.parse(Path('agent_market/concierge/ads_library_page.py').read_text())
    names = {n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any('ad_coin' in n for n in names)
    from agent_market.concierge import public_http_contract as c
    assert {'/ads/library', '/ads/library.json'} <= c.EDGE_DOCUMENTS and c.shared_path('/ads/library')
