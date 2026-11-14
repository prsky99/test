"""Ads never touch verification, ranking, pearl judgement or necklace member choice (PM 11-14, user direction).

The guarantee is structural, so these tests pin the structure:
1. Outside agent_market/ad_coin, only the frontend wiring (concierge/front.py) imports advertising code, and only
   the router factories it mounts. No collector, gateway, ranking, evaluation, pearl or necklace module can read
   an ad, a booking or a coin balance.
2. The main application's SQL (application_store_sql.json, the only SQL the app's store may run) never names an
   advertising table, so judging code cannot query ad data even through the shared database.
3. Advertising SQL writes only advertising tables (adc2_*, ad_coin_*), so an ad cannot change a listing's
   grade, test report, health, rank or a necklace.
4. The Sponsored answer is a separate block: label, disclosure, no reward, cards with an advertiser name and text
   only (no rank, score, grade or position).
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'agent_market'
ALLOWED_IMPORTERS = {
    'agent_market/concierge/front.py': {
        'ad_coin.api.router_for',
        'ad_coin.private_workflows.customer_identity_for',
        'ad_coin.private_workflows.reader_for',
        'ad_coin.private_workflows.run_reader_for',
        'ad_coin.v2.live_service.is_v2_enabled',
        'ad_coin.v2.live_service.create_live_ad_coin_v2_router',
    },
    # 11-14 growth /advertise page: reads only whether USDC payments are switched on (wording on the page)
    'agent_market/concierge/advertise_page.py': {'ad_coin.v2.paid_bookings.enabled'},
}
SQL_KEYWORDS = {'ON', 'OR', 'SET', 'SKIP'}   # "INSERT OR", "DO UPDATE SET", "FOR UPDATE SKIP", "ON CONFLICT"


def _ad_imports(path):
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if 'ad_coin' in a.name}
        elif isinstance(node, ast.ImportFrom) and 'ad_coin' in (node.module or ''):
            module = node.module.split('ad_coin', 1)[1]
            found |= {'ad_coin' + module + '.' + a.name for a in node.names}
    return found


def test_only_the_frontend_wiring_imports_advertising_code():
    importers = {}
    for path in PACKAGE.rglob('*.py'):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith('agent_market/ad_coin/'):
            continue
        names = _ad_imports(path)
        if names:
            importers[relative] = names
    assert set(importers) <= set(ALLOWED_IMPORTERS), sorted(set(importers) - set(ALLOWED_IMPORTERS))
    for relative, names in importers.items():
        assert names <= ALLOWED_IMPORTERS[relative], (relative, sorted(names - ALLOWED_IMPORTERS[relative]))


def test_main_application_sql_never_names_an_advertising_table():
    text = (PACKAGE / 'application_store_sql.json').read_text()
    assert not re.search(r'adc2_|ad_coin', text)


def test_advertising_sql_writes_only_advertising_tables():
    statements = json.loads((PACKAGE / 'ad_coin/sql_registry.json').read_text())['statements']
    text = json.dumps(statements)
    targets = set(re.findall(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Za-z_][A-Za-z0-9_.]*)', text, re.I))
    outside = {t for t in targets - SQL_KEYWORDS if not re.match(r'(adc2_|ad_coin_|ad_coin_v2\.)', t)}
    assert outside == set(), sorted(outside)


def test_sponsored_cards_carry_no_rank_score_or_grade():
    from agent_market.ad_coin.v2.sponsored import DISCLOSURE, LABEL, SponsoredSlots

    class Store:
        def atomic(self):
            from contextlib import nullcontext
            return nullcontext()

        def all(self, name, args):
            return [{'id': 'c1', 'payload_json': json.dumps({'name': 'AgentValCon', 'creative_text': 'text'}),
                     'ends_ms': 2 ** 62, 'task_category': 'research', 'region': 'US'}] if 'booked' in name else []

    body = SponsoredSlots(Store(), taxonomy={'research'}, regions={'US'}).response('research', 'US', 'explore', 2, False)
    assert body['label'] == LABEL == 'Sponsored' and body['reward'] is None and 'never change' in DISCLOSURE
    assert body['cards'] and all(set(card) == {'id', 'label', 'advertiser', 'text'} for card in body['cards'])
