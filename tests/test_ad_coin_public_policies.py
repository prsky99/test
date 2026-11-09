"""Public policy pages describe AI AD Coin points and Sponsored content consistently (11-10 user instruction)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'new' / 'en'
PAGES = {path.name: path.read_text() for path in ROOT.glob('*.html')}
WITH_POLICIES = {name: text for name, text in PAGES.items() if 'Permitted use' in text}


def visible(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text)).replace('&quot;', '"')


def test_every_policy_copy_carries_the_points_and_sponsored_sections():
    assert len(WITH_POLICIES) >= 30
    for name, text in WITH_POLICIES.items():
        for heading in ('<h3>Points</h3>', '<h3>Sponsored content and advertisers</h3>',
                        '<h3>Fair use of points and coins</h3>', '<h3>Points, advertising and sponsored content</h3>',
                        '<h3>Sponsored content</h3>'):
            assert heading in text, (name, heading)


def test_points_rules_match_the_code():
    from agent_market.ad_coin.v2 import points
    terms = visible(PAGES['terms.html'])
    assert 'cannot be bought, sold, cashed out, exchanged for money or sent to another person' in terms
    assert 'no cash value' in terms
    assert 'expire after %d days without earning or using any' % points.POINTS_EXPIRY_DAYS in terms
    assert (points.POINTS_PER_WORKSPACE_CREDIT, points.MAX_CREDITS_PER_EXCHANGE, points.MAX_CREDITS_PER_MONTH) == (10, 10, 50)
    assert ('%d points for 1 credit, up to %d credits at a time and %d credits a month' % (
        points.POINTS_PER_WORKSPACE_CREDIT, points.MAX_CREDITS_PER_EXCHANGE, points.MAX_CREDITS_PER_MONTH)) in terms
    assert 'labelled "Sponsored", appears separately from recommendations' in terms


def test_privacy_and_cookie_statements_for_the_sponsored_area():
    privacy, cookies = visible(PAGES['privacy.html']), visible(PAGES['cookies.html'])
    assert 'does not use sign-in, cookies or personal information' in privacy
    assert 'deleted after 90 days' in privacy and 'at least five years' in privacy
    assert 'The Sponsored area sets no cookies' in cookies


def test_policy_pages_make_no_value_promises_and_carry_no_build_notes():
    for name, text in WITH_POLICIES.items():
        words = visible(text).lower()
        for phrase in ('investment', 'guaranteed return', 'profit', 'interest rate', 'design layout preview'):
            assert phrase not in words, (name, phrase)
    assert 'Updated November 10, 2026' in PAGES['terms.html']
