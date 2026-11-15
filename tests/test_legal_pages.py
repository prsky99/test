"""/privacy and /terms are permanent redirects to the one published copy of each policy (11-15)."""
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_short_addresses_point_at_the_policy_pages(client):  # noqa: F811
    for path, target in (('/privacy', '/new/en/privacy.html'), ('/terms', '/new/en/terms.html')):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers['location'] == target, path
        page = client.get(target, headers={'Accept': 'text/html'})
        assert page.status_code == 200, target


def test_footer_links_point_at_the_policy_pages():
    from agent_market.concierge.growth_pages import FOOTER
    assert ('Terms of Service', '/new/en/terms.html') in FOOTER and ('Privacy Policy', '/new/en/privacy.html') in FOOTER
