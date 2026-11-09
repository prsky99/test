"""Markdown views of the public growth pages for agents that send Accept: text/markdown (11-10).

The HTML stays the single source: the <main> element of a rendered page is converted, so the
Markdown never says more than the page. Links become absolute, evidence rows become "label: value"
list items, code blocks stay fenced, and scripts, styles, buttons and SVG drawings are dropped.
"""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

ORIGIN = 'https://agentconcierge.biz'
SKIP = {'script', 'style', 'svg', 'button', 'template', 'noscript', 'head'}
BLOCK = {'p', 'div', 'section', 'article', 'ul', 'ol', 'dl', 'header', 'footer', 'nav', 'figure', 'figcaption', 'table', 'tr'}
VOID = {'br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'wbr'}


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.line = [], ''
        self.in_main = 0
        self.skip = 0
        self.pre = None
        self.links = []
        self.row = None
        self.list_depth = 0
        self.title = ''
        self.in_title = False
        self.canonical = None
        self.noindex = False

    def flush(self):
        text = re.sub(r'[ \t]+', ' ', self.line).strip()
        if text:
            self.lines.append(text)
        self.line = ''

    def blank(self):
        self.flush()
        if self.lines and self.lines[-1] != '':
            self.lines.append('')

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'meta' and attrs.get('name') == 'robots' and 'noindex' in (attrs.get('content') or ''):
            self.noindex = True
        if tag == 'main':
            self.in_main += 1
            return
        if not self.in_main or tag in VOID and tag != 'br':
            return
        if self.skip or tag in SKIP:
            self.skip += tag in SKIP
            return
        classes = (attrs.get('class') or '').split()
        if self.pre is not None:
            return
        if tag == 'pre':
            self.blank()
            self.pre = ''
        elif tag in ('h1', 'h2', 'h3', 'h4'):
            self.blank()
            self.line = '#'*int(tag[1])+' '
        elif tag == 'li' or attrs.get('role') == 'listitem':
            self.flush()
            self.line = '  '*max(0, self.list_depth-1)+'- ' if tag == 'li' else ''
            if tag != 'li':
                self.blank()
        elif tag in ('ul', 'ol'):
            self.flush()
            self.list_depth += 1
        elif 'history-row' in classes:
            self.flush()
            self.row = []
        elif tag == 'br':
            self.flush()
        elif tag in BLOCK:
            self.flush() if tag in ('div', 'tr') else self.blank()
        elif tag == 'a':
            if self.line.endswith(')'):
                self.line += ' '
            self.links.append((attrs.get('href') or '', len(self.line)))
        elif tag == 'code':
            self.line += '`'
        elif tag in ('strong', 'b'):
            self.line += '**'
        elif tag in ('td', 'th', 'dt', 'dd'):
            self.line += ' '
        if self.row is not None and tag == 'span':
            self.row.append('')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag == 'main':
            self.flush()
            self.in_main -= 1
            return
        if not self.in_main:
            return
        if self.skip:
            if tag in SKIP:
                self.skip -= 1
            return
        if tag == 'pre' and self.pre is not None:
            self.lines += ['```', *self.pre.strip('\n').split('\n'), '```', '']
            self.pre = None
        elif self.pre is not None:
            return
        elif tag in ('h1', 'h2', 'h3', 'h4'):
            self.blank()
        elif tag == 'a' and self.links:
            href, start = self.links.pop()
            label = self.line[start:].strip()
            if href and label and not href.startswith('#') and not href.startswith('javascript:'):
                self.line = self.line[:start]+'['+label+']('+urljoin(ORIGIN+'/', href)+')'
        elif tag == 'code':
            self.line += '`'
        elif tag in ('strong', 'b'):
            self.line += '**'
        elif tag in ('ul', 'ol'):
            self.list_depth = max(0, self.list_depth-1)
            self.blank()
        elif tag == 'li':
            self.flush()
        elif tag == 'div' and self.row is not None:
            parts = [p.strip() for p in self.row if p.strip()]
            self.row = None
            self.line = ''
            if parts:
                self.lines.append('- '+parts[0]+(': '+' '.join(parts[1:]) if len(parts) > 1 else ''))
        elif tag in BLOCK:
            self.flush() if tag in ('div', 'tr') else self.blank()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if not self.in_main or self.skip:
            return
        if self.pre is not None:
            self.pre += data
        elif self.row is not None and self.row:
            self.row[-1] += data
        elif self.row is None:
            self.line += data.replace('\n', ' ')


def html_to_markdown(html, info=None):
    parser = _Converter()
    parser.feed(html)
    parser.close()
    parser.flush()
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(parser.lines)).strip()
    if info is not None:
        info['noindex'] = parser.noindex
    footer = []
    if parser.canonical:
        footer.append('Canonical page: '+parser.canonical)
    footer.append('Agent instructions: '+ORIGIN+'/llms.txt · MCP: '+ORIGIN+'/mcp · Setup: '+ORIGIN+'/connect')
    return text+'\n\n---\n'+'\n'.join(footer)+'\n'


def route_class():
    """An APIRoute that answers explicit Markdown requests with the Markdown view of its HTML page."""
    from fastapi.routing import APIRoute
    from fastapi.responses import PlainTextResponse
    from .conditional_http import prefers_markdown

    class MarkdownRoute(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def handler(request):
                response = await original(request)
                if not (response.media_type or '').startswith('text/html') or b'<main' not in response.body:
                    return response  # not a page (e.g. a search-console ownership file)
                if prefers_markdown(request.headers.get('accept')):
                    headers = {k: v for k, v in response.headers.items()
                               if k.lower() in ('cache-control', 'x-robots-tag')}
                    headers['Vary'] = 'Accept'
                    info = {}
                    text = html_to_markdown(response.body.decode('utf-8'), info)
                    if info['noindex']:
                        headers['X-Robots-Tag'] = 'noindex'
                    return PlainTextResponse(text, status_code=response.status_code,
                                             media_type='text/markdown; charset=utf-8', headers=headers)
                response.headers['Vary'] = 'Accept'
                return response
            return handler

    return MarkdownRoute
