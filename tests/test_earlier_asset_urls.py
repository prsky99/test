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


PAGE = ('<main><template data-inactive-panel="learn"><section>Learn v1</section></template></main>'
        '<script src="/new/en/assets/bundle.js?f=app&amp;v=0000000000000000" defer></script>')


def test_a_panels_digest_from_before_a_deploy_is_served_exactly_from_disk(deployed):
    # 11-12 (PM: swr on public HTML): HTML cached before a deploy names its panels.js digest; the new process never
    # rendered it, so the script is kept on disk beside the releases and served as it was.
    client, *_ = deployed
    pearl_view._panels.clear()
    value = pearl_view.split_panels(PAGE)
    version = value.split('panels.js?v=')[1][:16]
    kept = pearl_view.panels_dir() / (version + '.js')
    assert kept.is_file() and b'Learn v1' in kept.read_bytes()
    pearl_view._panels.clear()  # a new process or release: nothing rendered yet
    pearl_view._panels_rebuilt['at'] = pearl_view.time.monotonic()  # and no rebuild this minute
    r = client.get('/new/en/assets/panels.js?v=' + version)
    assert r.status_code == 200 and r.content == kept.read_bytes()
    assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'


def test_a_changed_or_odd_panels_file_is_not_served_as_its_digest(deployed):
    client, *_ = deployed
    folder = pearl_view.panels_dir()
    folder.mkdir(exist_ok=True)
    (folder / 'abcdefabcdefabcd.js').write_bytes(b'not what that digest stands for')
    assert pearl_view.panels_from_disk('abcdefabcdefabcd') is None
    assert pearl_view.panels_from_disk('../../escape') is None and pearl_view.panels_from_disk('') is None


def test_outside_a_releases_folder_panels_stay_in_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(pearl_view, 'ROOT', tmp_path / 'new')
    assert pearl_view.panels_dir() is None
    pearl_view.keep_panels_on_disk('abcdefabcdefabcd', b'x')  # nothing written, nothing raised
    assert not list(tmp_path.rglob('*.js'))
