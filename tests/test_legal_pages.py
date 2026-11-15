"""/privacy and /terms (E12, PM 11-15): the footer dialog texts as plain pages, the same words, no script needed."""
import re

from agent_market.concierge import legal_pages
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_pages_show_the_dialog_texts_word_for_word(client):  # noqa: F811
    docs = legal_pages.documents()
    assert {'privacy', 'ccpa', 'tos', 'ai'} <= set(docs)
    for path, (_, keys) in legal_pages.PAGES.items():
        r = client.get(path, headers={'Accept': 'text/html'})
        assert r.status_code == 200, path
        assert "'self'" in re.search(r"style-src ([^;]*)", r.headers['content-security-policy']).group(1)
        assert 'public, max-age=600' in r.headers['cache-control'], path
        for key in keys:
            first = re.sub(r'<[^>]+>', ' ', docs[key][2]).split()[:6]
            assert ' '.join(first) in re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.text)), (path, key)


def test_only_known_tags_pass():
    out = legal_pages.safe('<p>ok <a href="/x">x</a></p><script>alert(1)</script><a href="/y" onclick="z()">y</a>')
    assert '<script>' not in out and '&lt;script&gt;' in out and 'onclick' not in out.replace('&lt;', '').split('>')[0]
    assert '<p>ok <a href="/x">x</a></p>' in out


def test_footer_links_point_at_the_pages():
    from agent_market.concierge.growth_pages import FOOTER
    assert ('Terms of Service', '/terms') in FOOTER and ('Privacy Policy', '/privacy') in FOOTER
