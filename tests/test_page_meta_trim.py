"""11-13 PM 22:5x decision (b): a page carries the page:* meta of its own panel and of the home page only.

All nine live pages carried 67 page:* tags for every panel (2.0-2.5 KB gzip of the TCP first flight). The full set
moved to /page-metadata.json (linked from each page with rel=alternate) and to "Page Metadata" in /llms-full.txt.
The pages themselves never read these tags (screen changes use operating.js PAGE_METAS).
"""
import ast
import json
import re
from pathlib import Path

import pytest

from agent_market.concierge.pearl_view import LIVE_PANELS, PAGE_METADATA_PATH, page_metadata
from agent_market.concierge.public_http_contract import DISCOVERY_CACHE
from tests.test_pearl_frontend import client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'new/en/index.html').read_text()
META = re.compile(r'<meta name="page:([a-z-]+):([a-z0-9:-]+)" content="([^"]*)">')


def test_the_panel_names_are_the_build_names():
    tree = ast.parse((ROOT / 'new/build_en.py').read_text())
    built = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'PANELS')
    assert LIVE_PANELS == built


@pytest.mark.parametrize('name', sorted(LIVE_PANELS))
def test_a_page_keeps_its_own_and_the_home_meta_and_links_the_rest(client, name):  # noqa: F811
    path = '/' if name == 'index.html' else '/new/en/' + name
    html = client.get(path, headers={'Accept': 'text/html'}).text
    panels = {m[1] for m in META.finditer(html)}
    assert 'overview' in panels and panels <= {'overview', LIVE_PANELS[name]}
    own = {(m[1], m[2]) for m in META.finditer(SOURCE) if m[1] == LIVE_PANELS[name]}
    assert own <= {(m[1], m[2]) for m in META.finditer(html)}  # nothing of the page's own panel is lost
    assert html.count('<link rel="alternate" type="application/json" title="Page metadata of every Agent Concierge page" '
                      'href="%s">' % PAGE_METADATA_PATH) == 1


def test_the_document_holds_every_panel_as_published(client):  # noqa: F811
    r = client.get(PAGE_METADATA_PATH)
    assert r.status_code == 200 and r.headers['content-type'].startswith('application/json')
    assert r.headers['cache-control'] == DISCOVERY_CACHE
    body = r.json()
    assert body['meta'] == page_metadata(SOURCE)
    assert set(body['meta']) == {m[1] for m in META.finditer(SOURCE)}
    assert sum(len(v) for v in body['meta'].values()) == len(META.findall(SOURCE)) == 67
    head = client.head(PAGE_METADATA_PATH)
    assert head.status_code == 200 and not head.content


def test_llms_full_names_the_document_and_each_page(client):  # noqa: F811
    text = client.get('/llms-full.txt').text
    assert PAGE_METADATA_PATH in text and '## 8. Page Metadata' in text
    meta = page_metadata(SOURCE)
    for panel in ('about', 'chat', 'explore', 'learn', 'register', 'test', 'workflows'):
        assert json.dumps(meta[panel]['title'])[1:-1] in text or meta[panel]['title'] in text, panel
