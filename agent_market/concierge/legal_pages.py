"""Plain pages for the privacy policy and the terms (E12, PM 11-15).

The Claude Connectors Directory asks for a privacy policy URL and a documentation URL. Until 11-15 the policy texts
lived only in the footer dialog of the main pages (site-policy.js LEGAL_DOCS, opened by script), and /privacy and
/terms answered 404. These pages show the same texts, word for word, in the growth-page frame and need no script.
The texts stay in one place: they are read from site-policy.js, and only the tags that file uses are let through.
"""
import html
import json
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'new' / 'en' / 'assets' / 'site-policy.js'
ENTRY = re.compile(r'"([a-z]+)": \{"title": "((?:[^"\\]|\\.)*)", "sub": "((?:[^"\\]|\\.)*)", "html": "((?:[^"\\]|\\.)*)"')
ALLOWED = re.compile(r'</?(?:h4|p|a|ul|ol|li|strong|em|code|br)\b[^<>]*>')
PAGES = {'/privacy': ('Privacy Policy', ('privacy', 'ccpa')), '/terms': ('Terms of Service', ('tos', 'ai'))}
_CACHE = {'key': None, 'docs': None}


def documents(path=SOURCE):
    """{key: (title, sub, html)} from site-policy.js, or {} when the file is missing or unreadable."""
    try:
        stat = Path(path).stat()
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CACHE['key'] == key:
        return _CACHE['docs']
    start = text.find('LEGAL_DOCS = {')
    docs = {}
    if start >= 0:
        for match in ENTRY.finditer(text[start:]):
            try:
                docs[match.group(1)] = tuple(json.loads('"' + part + '"') for part in match.group(2, 3, 4))
            except ValueError:
                continue
    _CACHE.update(key=key, docs=docs)
    return docs


def safe(body):
    """Our own policy HTML, with anything but its known tags escaped (and no event or script attributes)."""
    out, last = [], 0
    for tag in ALLOWED.finditer(body):
        out.append(html.escape(body[last:tag.start()], quote=False))
        value = tag.group(0)
        out.append(value if not re.search(r'\son\w+\s*=|javascript:', value, re.I) else html.escape(value))
        last = tag.end()
    out.append(html.escape(body[last:], quote=False))
    return ''.join(out)


def page_html(path, docs=None):
    from .growth_pages import ORIGIN, heading, shell
    docs = documents() if docs is None else docs
    title, keys = PAGES[path]
    parts = [docs[k] for k in keys if k in docs]
    if not parts:
        return None
    body = heading('AgentValCon', title, parts[0][1]) + ''.join(
        '<section class="card stack legal-doc"' + (' aria-labelledby="legal-' + str(i) + '"' if i else '') + '>'
        + ('<h2 id="legal-' + str(i) + '">' + html.escape(t) + '</h2><p class="caption">' + html.escape(sub) + '</p>' if i else '')
        + safe(text) + '</section>' for i, (t, sub, text) in enumerate(parts))
    return shell(title=title + ' | AgentValCon', description=title + ' of AgentValCon.', canonical=ORIGIN + path, body=body,
                 index=True)


def legal_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse
    from .growth_pages import PAGE_CSP
    router = APIRouter()

    def endpoint(path):
        def serve():
            value = page_html(path)
            if value is None:
                return HTMLResponse('<!doctype html><title>Not available</title><p>This page is not available right now.</p>',
                                    status_code=503, headers={'Cache-Control': 'no-store'})
            return HTMLResponse(value, headers={'Content-Security-Policy': PAGE_CSP})
        return serve

    for path in PAGES:
        router.add_api_route(path, endpoint(path), methods=['GET'], include_in_schema=False)
    return router
