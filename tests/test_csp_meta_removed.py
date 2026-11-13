"""11-13 (PM 14 KB task B): the build's CSP meta leaves the response; the CSP header covers every directive.

The meta cost about 120 bytes of gzip in the first flight and only repeated (more loosely) what the header says.
This checks, on the published pages, that the header is at least as strict as the meta in every directive the meta
had, so dropping the meta loosens nothing.
"""
import html
import re
from pathlib import Path

import pytest

from tests.test_pearl_frontend import client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'chat.html', 'explore.html', 'about.html', 'test.html', 'privacy.html', 'terms.html')
STRICTER = ('privacy.html', 'terms.html')


def policy(text):
    return {part.split()[0]: part.split()[1:] for part in (p.strip() for p in text.split(';')) if part}


@pytest.mark.parametrize('name', PAGES)
def test_the_header_is_at_least_as_strict_as_the_meta_it_replaces(client, name):  # noqa: F811
    source = (ROOT / 'new/en' / name).read_text()
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', source)
    assert meta, 'the published page still carries the build meta; the response drops it'
    old = policy(html.unescape(meta[1]))
    r = client.get('/new/en/' + name)
    assert r.status_code == 200
    if name in STRICTER:  # their own meta forbids inline style and connections: kept
        assert policy(html.unescape(re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">',
                                              r.text)[1])) == old
        return
    assert 'http-equiv="Content-Security-Policy"' not in r.text
    new = policy(r.headers['content-security-policy'])
    assert new['default-src'] == ["'none'"]  # stricter than the meta's 'self'
    for directive, sources in old.items():
        if directive == 'default-src':
            continue
        assert directive in new, directive
        extra = [s for s in new[directive] if s not in sources]
        # The header may only add hashes of the page's own inline scripts.
        assert all(s.startswith("'sha256-") for s in extra) and directive == 'script-src' or not extra, (directive, extra)
    assert new['frame-ancestors'] == ["'none'"]
