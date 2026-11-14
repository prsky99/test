"""11-11 first paint: pages ask for one stylesheet and one deferred script, and inline the tiny blocking bootstrap."""
import re

from tests.test_pearl_frontend import client  # noqa: F401


def test_pages_load_one_stylesheet_and_one_deferred_script(client):  # noqa: F811
    html = client.get('/new/en/index.html').text
    head = html[:html.index('</head>')]
    assert len(re.findall(r'<link rel="stylesheet"', head)) == 1
    deferred = re.findall(r'<script[^>]*src="/new/en/assets/([^"?]+)[^"]*"[^>]*defer', html)
    assert deferred == ['panels.js', 'bundle.js']  # 11-11: inactive panel markup in its own shared file, first
    assert 'session-bootstrap.js' not in html  # inlined, carries the page nonce like every script
    css = re.search(r'href="(/new/en/assets/bundle\.css\?f=([^"&]+)&amp;v=([0-9a-f]+))"', html)
    js = re.search(r'src="(/new/en/assets/bundle\.js\?f=([^"&]+)&amp;v=([0-9a-f]+))"', html)
    assert css and js
    assert css[2].split(',') == ['operating', 'styles', 'necklace', 'pearl-live', 'experience']
    # 11-14: consent and policy dialogs come first (site-policy.js), before the operating runtime that uses them
    assert js[2].split(',')[:3] == ['panels-bootstrap', 'site-policy', 'operating'] and js[2].split(',')[-1] == 'workflow-library'
    for match, kind in ((css, 'text/css'), (js, 'text/javascript')):
        r = client.get(match[1].replace('&amp;', '&'))
        assert r.status_code == 200 and r.headers['content-type'].startswith(kind)
        assert r.headers['cache-control'] == 'public, max-age=31536000, immutable' and r.headers['etag'] == '"' + match[3] + '"'
    body = client.get(css[1].replace('&amp;', '&')).text
    assert body.index('.pearl-sponsored') > body.index('html body') >= 0  # styles.css content kept, in order


def test_bundle_rejects_unknown_or_unsafe_names(client):  # noqa: F811
    for query in ('f=../../en-manifest', 'f=nope', 'f=', 'f=' + ','.join(['styles'] * 13)):
        assert client.get('/new/en/assets/bundle.css?' + query).status_code == 404
    assert client.get('/new/en/assets/bundle.css?f=styles&v=old').headers['cache-control'].startswith('public, max-age=300')


def test_legal_pages_with_relative_asset_links_are_bundled_too(client):  # noqa: F811
    html = client.get('/new/en/disclosures.html').text
    assert len(re.findall(r'<link rel="stylesheet"', html[:html.index('</head>')])) == 1
    assert re.search(r'href="/new/en/assets/bundle\.css\?f=styles,necklace&amp;v=[0-9a-f]+"', html)
    assert re.search(r'src="/new/en/assets/bundle\.js\?f=app,service-contacts&amp;v=[0-9a-f]+"[^>]*defer', html)


def test_every_page_bundle_is_served(client):  # noqa: F811
    from pathlib import Path
    seen = 0
    for page in sorted(Path('new/en').glob('*.html')):
        r = client.get('/new/en/' + page.name)
        if r.status_code != 200 or 'text/html' not in r.headers.get('content-type', ''):
            continue
        for url in re.findall(r'"(/new/en/assets/bundle\.(?:css|js)\?[^"]+)"', r.text):
            seen += 1
            assert client.get(url.replace('&amp;', '&')).status_code == 200, (page.name, url)
    assert seen >= 20


def test_bundle_css_points_images_at_the_same_versioned_address_as_the_page(client):  # noqa: F811
    html = client.get('/new/en/index.html').text
    css_url = re.search(r'href="(/new/en/assets/bundle\.css\?[^"]+)"', html)[1].replace('&amp;', '&')
    css = client.get(css_url).text
    img = re.search(r'/new/en/assets/pearl\.webp\?v=([0-9a-f]{16})', html)
    assert "url('pearl.webp')" not in css and "url('pearl.webp?v=" in css
    if img:
        assert "pearl.webp?v=" + img[1] in css
