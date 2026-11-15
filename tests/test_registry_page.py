"""/registry (E7, PM 11-15): what the verified registry lists, what it leaves out and how to use it, linked from
/methodology. The disclaimer is the agent team's exact sentence; the steps follow GitHub's own page."""
import re

from agent_market.concierge import methodology_page as mp, registry_page as rp
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_the_page_states_criteria_leaving_reasons_and_the_disclaimer(client):  # noqa: F811
    r = client.get('/registry', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and "'self'" in re.search(r"style-src ([^;]*)", r.headers['content-security-policy']).group(1)
    assert 'public, max-age=600' in r.headers['cache-control']
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.text)).replace('&#x27;', "'").replace('&#39;', "'")
    assert rp.BASE in text and rp.DISCLAIMER in text
    for code, _ in rp.REASONS:
        assert code in text, code
    assert 'MCP Registry URL' in text and 'Registry only' in text and rp.GITHUB_DOC in r.text
    assert 'chat.mcp.gallery' not in r.text   # not described until its official documentation confirms it


def test_methodology_links_to_the_registry():
    page = mp.page_html(data={'version': 'v1.1', 'name': 'Verification method v1.1'}, log=[])
    assert 'href="/registry"' in page
