"""/customer/sign-in as a page the edge may keep (PM 11-16 04:3x).

The sign-in page carries nothing personal: whether the visitor is signed in and the provider list are fetched by its
script after it opens (/api/customer-auth/status, /api/customer-auth/options), and the sign-in flow cookie is set by
the POST that the button sends. Its only per-request value was the CSP nonce, and with it 163 KB of inline CSS went
out on every request with no-store (1.39 s from Korea in the 03:53 full check, two round trips with the old 308).

cacheable() turns the rendered page into the same bytes for everyone:
- every <style> block, in document order, moves into one content-addressed stylesheet,
  /customer/assets/sign-in.<digest>.css, kept immutable (same cascade: the blocks were all in <head>, in this order);
- nonces are removed and each inline script is allowed by its sha256 instead;
- the browser keeps the page a short while and the edge longer; X-Robots-Tag noindex and the frame and type headers stay.
Only the sign-in page goes through here; the signed-in customer pages keep their nonce and no-store.
"""
import base64
import collections
import hashlib
import re
import threading
from pathlib import Path

CSS_PREFIX = '/customer/assets/sign-in.'   # + <16 hex digest> + '.css' (in the path: some layers drop query strings)
CSS_ROUTE = CSS_PREFIX + '{version}.css'
CSS_PATH = re.compile(r'/customer/assets/sign-in\.[0-9a-f]{16}\.css')
STYLE_BLOCK = re.compile(r'<style(?: nonce="[^"]*")?>(.*?)</style>', re.S)
NONCE_ATTR = re.compile(r' nonce="[^"]*"')
INLINE_SCRIPT = re.compile(r'<script>(.*?)</script>', re.S)
BROWSER_CACHE = 'public, max-age=300'
EDGE_CACHE = 'public, max-age=21600, stale-while-revalidate=86400'  # PM 11-18 06:40: was 3600; the two-hourly check met it expired
_css = collections.OrderedDict()
_lock = threading.Lock()


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def shared_dir():
    """gateway-data/services/sign-in-css beside the releases folder, shared by every release; None elsewhere.
    PM 11-16 04:5x: the edge may hand out yesterday's sign-in HTML for up to a day (stale-while-revalidate), naming the
    stylesheet digest of the previous release; the new release never rendered it, so each digest is kept on disk."""
    release = Path(__file__).resolve().parents[1]
    return release.parent.parent / 'sign-in-css' if release.parent.name == 'releases' else None


DISK_KEPT = 16


def _keep_on_disk(version, css, folder=None):
    folder = folder if folder is not None else shared_dir()
    if folder is None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (version + '.css')
        if not path.exists():
            tmp = folder / ('.' + version + '.tmp')
            tmp.write_text(css, encoding='utf-8')
            tmp.replace(path)
        kept = sorted(folder.glob('*.css'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in kept[DISK_KEPT:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _from_disk(version, folder=None):
    folder = folder if folder is not None else shared_dir()
    if folder is None:
        return None
    try:
        return (folder / (version + '.css')).read_text(encoding='utf-8')
    except OSError:
        return None


def _keep(version, css):
    with _lock:
        known = version in _css
        _css[version] = css
        _css.move_to_end(version)
        while len(_css) > 8:
            _css.popitem(last=False)
    if not known:
        _keep_on_disk(version, css)


def cacheable(response):
    """The sign-in HTMLResponse with its styles linked, its scripts allowed by hash and public cache headers."""
    from fastapi.responses import HTMLResponse
    if 'set-cookie' in response.headers:   # PM 11-16 04:5x: a page that sets a cookie is never made shareable
        return response
    html = response.body.decode('utf-8')
    css = '\n'.join(STYLE_BLOCK.findall(html))
    version = _digest(css)
    _keep(version, css)
    first = [True]

    def place(_match):
        if first[0]:
            first[0] = False
            return '<link rel="stylesheet" href="' + CSS_PREFIX + version + '.css">'
        return ''
    html = STYLE_BLOCK.sub(place, html)
    html = NONCE_ATTR.sub('', html)
    hashes = sorted({base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode('ascii')
                     for body in INLINE_SCRIPT.findall(html)})
    policy = ("default-src 'none'; script-src " + ' '.join("'sha256-" + h + "'" for h in hashes)
              + "; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; "
                "object-src 'none'; frame-ancestors 'none'; form-action 'self'")
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'cache-control',
                                                                               'pragma', 'expires',
                                                                               'content-security-policy')}
    headers.update({'Content-Security-Policy': policy, 'Cache-Control': BROWSER_CACHE,
                    'Cloudflare-CDN-Cache-Control': EDGE_CACHE})
    return HTMLResponse(html, status_code=response.status_code, headers=headers)


def stylesheet(version, render):
    """(status, css): the stylesheet a page names, rendering the page once in this process if needed (several
    processes serve the site, and the one asked for the stylesheet may not have rendered the page yet)."""
    if not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{16}', version):
        return 404, None
    with _lock:
        css = _css.get(version)
    if css is None:
        css = _from_disk(version)          # a digest an earlier release rendered (edge-kept old HTML)
    if css is None:
        cacheable(render())
        with _lock:
            css = _css.get(version)
    return (200, css) if css is not None else (404, None)


def router(render):
    """render(next_value) -> the sign-in HTMLResponse (customer_identity_view.sign_in_page with a checked destination)."""
    from fastapi import APIRouter, Request
    from fastapi.responses import Response
    api = APIRouter()

    @api.get('/customer/sign-in', include_in_schema=False)
    def sign_in(request: Request):
        return cacheable(render(request.query_params.get('next')))

    @api.get(CSS_ROUTE, include_in_schema=False)
    def sign_in_css(version: str):
        status, css = stylesheet(version, render)
        if css is None:
            return Response(status_code=404, headers={'Cache-Control': 'no-store'})
        return Response(css, media_type='text/css; charset=utf-8',
                        headers={'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff'})

    return api
