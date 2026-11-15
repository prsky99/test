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
    assert '/new/en/assets/styles.css' in r.text
    assert "'self'" in style_src(r), (path, r.headers.get('content-security-policy'))


def test_necklace_page_allows_its_stylesheets_and_script(client, tmp_path, monkeypatch, snapshot):  # noqa: F811
    (tmp_path / 'gateway-data/necklaces').mkdir(parents=True)
    (tmp_path / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps(snapshot))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    r = client.get('/necklaces/paper-digest', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and '/new/en/assets/necklace.css' in r.text
    assert "'self'" in style_src(r)
    assert "script-src 'self'" in r.headers['content-security-policy']   # app.js (theme button) runs
