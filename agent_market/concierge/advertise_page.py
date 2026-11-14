"""/advertise: why and how to advertise on AgentValCon (PM 11-14, user: coin revenue through ads, demand side).

The booking flow, prices and terms live with the AD Coin team (/ad-coin/v2/advertise, /ad-coin/v2#advertising); this
page adds the measured audience and the trust rules, and links there. Numbers come from logs/growth/usage-daily.jsonl
(anonymous daily counts, our own checks excluded); a missing value hides its line. USDC wording follows the payment
switch (AD_COIN_PAID_BOOKING_ENABLED, read without importing ad_coin). No promise words: no "best", "guaranteed" or "#1".
"""
import html
import json
import os
from pathlib import Path

PRICE_USDC = 5          # per placement per day (user decision 11-11 launch price, shown on /ad-coin/v2/advertise too)
APPLY = '/ad-coin/v2#advertising'
DETAILS = '/ad-coin/v2/advertise'


def usage_rows(path=None, days=7):
    if path is None:
        root = os.environ.get('AGENTCON_PROJECT_ROOT')
        if not root:
            return []
        path = Path(root) / 'logs/growth/usage-daily.jsonl'
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()[-days:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get('day'), str):
            rows.append(row)
    return rows


def audience(rows):
    """Sums over the days present, per measure, only for measures every row has."""
    measures = [('human_visitors', 'People visiting our pages'), ('explore_external', 'Explore searches from outside'),
                ('chat_external', 'Chat questions from outside'), ('mcp_sessions_real', 'MCP client sessions (checkers excluded)'),
                ('a2a_messages_external', 'A2A messages from outside agents')]
    out = []
    for key, label in measures:
        values = [r.get(key) for r in rows]
        if rows and all(isinstance(v, int) for v in values):
            out.append((label, sum(values)))
    return out


PAID_SWITCH = 'AD_COIN_PAID_BOOKING_ENABLED'  # same switch as ad_coin.v2.paid_bookings.ENABLED_ENV (sponsored.env)


def usdc_open():
    """On/off of the USDC booking switch, read from the environment only: organic modules never import ad_coin
    (tests/test_ad_coin.py::test_organic_selection_cannot_import_ad_coin, no exception, PM 11-14)."""
    return os.environ.get(PAID_SWITCH, '0') in ('1', 'true', 'True')


def page_html(base='https://agentconcierge.biz', rows=None, usdc=None):
    from .growth_pages import shell, heading
    esc = lambda v: html.escape(str(v), quote=True)
    rows = usage_rows() if rows is None else rows
    usdc = usdc_open() if usdc is None else usdc
    parts = [heading('Advertise · Agent Value Gateway', 'Advertise on AgentValCon',
                     'Reach people and AI agents while they choose an agent. Placements are labelled Sponsored and never '
                     'change what we test, score or recommend.')]
    measured = audience(rows)
    if measured:
        span = rows[0]['day'] + ' to ' + rows[-1]['day']
        parts.append('<section aria-labelledby="adAudience"><h2 id="adAudience">Who sees AgentValCon</h2>'
                     '<p class="muted">Measured from anonymous daily counts, ' + esc(span) + ' (UTC days); our own checks and known '
                     'registry checkers are not counted.</p><dl class="evidence-list">'
                     + ''.join('<dt>' + esc(k) + '</dt><dd>' + esc(f'{v:,}') + '</dd>' for k, v in measured)
                     + '</dl><p class="muted">Your own report shows how many times your placement was shown each day.</p></section>')
    parts.append('<section aria-labelledby="adWhere"><h2 id="adWhere">Where a placement appears</h2><ul>'
                 '<li>Explore: one card labelled “Sponsored” below the results for its task category.</li>'
                 '<li>Chat: one card labelled “Sponsored” below the answer, never inside it.</li>'
                 '<li>Sold by task category and broad region; each pair has two placements a day.</li></ul></section>')
    parts.append('<section aria-labelledby="adTrust"><h2 id="adTrust">What an ad never changes</h2><ul>'
                 '<li>Test results, scores and grades of any agent.</li>'
                 '<li>Which agents become pearls, and which necklaces are offered.</li>'
                 '<li>The order of search results and recommendations.</li>'
                 '<li>We do not track people for ads: no ad cookies, no profiles, no personal data in reports.</li></ul>'
                 '<p>How agents are tested: <a href="/methodology">our method</a>.</p></section>')
    pay = ('Pay ' + str(PRICE_USDC) + ' USDC on Base per placement per day, from your own wallet, when you book. '
           'There is no stored balance and no subscription. If we cannot show your placement for reasons on our side, '
           'we return the payment.') if usdc else (
          'Paid placements will cost ' + str(PRICE_USDC) + ' USDC on Base per placement per day, paid from your own wallet '
          'when you book. USDC payments are not open yet; you can apply now.')
    parts.append('<section aria-labelledby="adPrice"><h2 id="adPrice">Price and payment</h2><p>' + esc(pay) + '</p>'
                 '<p>Advertising is open to providers whose agent or tool is listed with us; we check that the listing is yours.</p>'
                 '<p><a class="btn primary" href="' + APPLY + '">Apply as an advertiser</a> '
                 '<a class="btn" href="' + DETAILS + '">How booking works</a></p>'
                 '<p class="muted">Questions: contact@agentconcierge.biz</p></section>')
    structured = {'@context': 'https://schema.org', '@type': 'WebPage', 'name': 'Advertise on AgentValCon',
                  'url': base + '/advertise', 'publisher': {'@type': 'Organization', 'name': 'AgentValCon', 'url': base + '/'}}
    return shell(title='Advertise on AgentValCon | Sponsored placements for AI agents',
                 description='Sponsored placements next to AI agent discovery: measured audience, placement rules, price in USDC.',
                 canonical=base + '/advertise', body='<div class="pearl-page">' + ''.join(parts) + '</div>', structured=structured)


def advertise_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse
    router = APIRouter()

    @router.get('/advertise', include_in_schema=False)
    def advertise():
        return HTMLResponse(page_html())

    return router
