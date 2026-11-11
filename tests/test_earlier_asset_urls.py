"""11-11 (PM: swr on public HTML only after a test proves old bundle URLs keep working after a deploy).

An edge may serve HTML cached before a deploy. That HTML names the previous bundle digests
(bundle.css?f=...&v=<old>). After the deploy the origin must still answer those URLs with the bytes the old
release served (200, immutable), found in the earlier release folders beside the running one.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge import pearl_view


def release(releases, name, files):
    root = releases / name / 'new'
    (root / 'en' / 'assets').mkdir(parents=True)
    (root / 'en-manifest.json').write_text(json.dumps({'live_pages': [], 'presentation_only_pages': []}))
    for path, text in files.items():
        (root / 'en' / 'assets' / path).write_bytes(text.encode())
    return root


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    releases = tmp_path / 'gateway-data' / 'services' / 'releases'
    old = release(releases, 'a-frontend-r1', {'a.css': '.a{color:red;background:url(pearl.webp)}', 'b.css': '.b{}',
                                              'app.js': 'old()', 'gone.js': 'removed()', 'pearl.webp': 'old-image'})
    new = release(releases, 'b-frontend-r1', {'a.css': '.a{color:blue;background:url(pearl.webp)}', 'b.css': '.b{}',
                                              'app.js': 'new()', 'pearl.webp': 'new-image'})
    import os
    os.utime(releases / 'a-frontend-r1', (1, 1))  # the older release
    monkeypatch.setattr(pearl_view, 'ROOT', new)
    pearl_view._earlier.clear()
    app = FastAPI()
    pearl_view.install(app, None, root=new)
    with TestClient(app) as client:
        yield client, old, new
    pearl_view._earlier.clear()


def test_the_previous_bundle_url_still_returns_its_own_bytes(deployed):
    client, old, new = deployed
    for kind, names in (('css', ['a', 'b']), ('js', ['app'])):
        before = pearl_view.bundle_body(names, kind, old)
        after = pearl_view.bundle_body(names, kind, new)
        assert before != after
        r = client.get('/new/en/assets/bundle.%s?f=%s&v=%s' % (kind, ','.join(names), pearl_view.asset_version(before)))
        assert r.status_code == 200 and r.content == before
        assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert r.headers['etag'] == '"%s"' % pearl_view.asset_version(before)
        r = client.get('/new/en/assets/bundle.%s?f=%s&v=%s' % (kind, ','.join(names), pearl_view.asset_version(after)))
        assert r.content == after and 'immutable' in r.headers['cache-control']


def test_old_css_keeps_pointing_at_the_old_image(deployed):
    client, old, _ = deployed
    css = pearl_view.bundle_body(['a', 'b'], 'css', old)
    image = pearl_view.asset_version(b'old-image')
    assert ('pearl.webp?v=' + image).encode() in css
    r = client.get('/new/en/assets/pearl.webp?v=' + image)
    assert r.status_code == 200 and r.content == b'old-image' and 'immutable' in r.headers['cache-control']


def test_a_file_the_new_release_dropped_is_served_only_by_its_old_digest(deployed):
    client, _, _ = deployed
    r = client.get('/new/en/assets/gone.js?v=' + pearl_view.asset_version(b'removed()'))
    assert r.status_code == 200 and r.content == b'removed()'
    assert client.get('/new/en/assets/gone.js').status_code == 404
    assert client.get('/new/en/assets/gone.js?v=0000000000000000').status_code == 404


def test_an_unknown_digest_gets_the_current_bytes_briefly(deployed):
    client, _, new = deployed
    r = client.get('/new/en/assets/bundle.js?f=app&v=0123456789abcdef')
    assert r.content == pearl_view.bundle_body(['app'], 'js', new)
    assert r.headers['cache-control'] == 'public, max-age=300, stale-while-revalidate=86400'


def test_no_path_escapes_an_earlier_release(deployed):
    client, old, _ = deployed
    (old / 'en' / 'secret.json').write_text('{}')
    assert pearl_view.earlier_file(old, 'assets/../secret.json') is None
    assert client.get('/new/en/assets/..%2Fsecret.json?v=' + pearl_view.asset_version(b'{}')).status_code == 404


def test_outside_a_releases_folder_nothing_is_searched(tmp_path, monkeypatch):
    monkeypatch.setattr(pearl_view, 'ROOT', tmp_path / 'repo' / 'new')
    assert pearl_view.earlier_roots() == []
