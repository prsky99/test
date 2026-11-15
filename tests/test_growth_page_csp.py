"""Pages built on the growth-page shell load their own stylesheets (F17 audit, 11-15).

/advertise, /methodology, /methodology/changelog and /necklaces/<slug> returned HTML without a CSP of their own, so
the default one (style-src 'unsafe-inline', script-src 'none', form-action 'none') applied: the browser refused
operating.css, styles.css, necklace.css and pearl-live.css and production showed those pages unstyled. Every page that
links the shell's stylesheets must allow them."""
import json
import re

import pytest

from tests.test_necklace_surface import snapshot  # noqa: F401 - fixture
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def style_src(response):
    policy = response.headers.get('content-security-policy', '')
    found = re.search(r"style-src ([^;]*)", policy)
    return found.group(1).split() if found else []


@pytest.mark.parametrize('path', ['/advertise', '/methodology', '/methodology/changelog'])
def test_shell_pages_allow_their_own_stylesheets(client, path):  # noqa: F811
    r = client.get(path, headers={'Accept': 'text/html'})
    assert r.status_code == 200
    assert re.search(r'/new/en/assets/bundle\.css\?f=[a-z,-]*\bstyles\b', r.text)   # one bundle (PM 14:38)
    assert "'self'" in style_src(r), (path, r.headers.get('content-security-policy'))


def test_necklace_page_allows_its_stylesheets_and_script(client, tmp_path, monkeypatch, snapshot):  # noqa: F811
    (tmp_path / 'gateway-data/necklaces').mkdir(parents=True)
    (tmp_path / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps(snapshot))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    r = client.get('/necklaces/paper-digest', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and re.search(r'/new/en/assets/bundle\.css\?f=[a-z,-]*\bnecklace\b', r.text)
    assert "'self'" in style_src(r)
    assert "script-src 'self'" in r.headers['content-security-policy']   # app.js (theme button) runs


def test_shell_bundle_is_served_as_css_and_kept(client):  # noqa: F811
    """PM 14:38: the shell's one stylesheet is the content-addressed bundle; the browser and the edge may keep it."""
    page = client.get('/methodology', headers={'Accept': 'text/html'}).text
    url = re.search(r'href="(/new/en/assets/bundle\.css\?[^"]+)"', page).group(1).replace('&amp;', '&')
    r = client.get(url)
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/css')
    assert 'immutable' in r.headers.get('cache-control', '') and len(r.content) > 1000


def test_shell_pages_name_their_stylesheet_as_a_preload(client):  # noqa: F811
    """PM 14:38: Cloudflare Early Hints sends only rel=preload links; the shell's one bundle is named, the agent links stay."""
    r = client.get('/methodology', headers={'Accept': 'text/html'})
    url = re.search(r'href="(/new/en/assets/bundle\.css\?[^"]+)"', r.text).group(1).replace('&amp;', '&')
    link = r.headers['link']
    assert '<' + url + '>; rel=preload; as=style' in link and 'rel="agent-card"' in link
    other = client.get('/llms.txt')
    assert 'rel=preload' not in other.headers.get('link', '')
