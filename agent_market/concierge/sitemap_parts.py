"""The sitemap as an index and parts small enough for one first flight (11-13 PM 20:5x).

One urlset of about 10,000 addresses was 630 KB, 39 KB with gzip. From Korea every response over the TCP first
flight (about 14.6 KB) paused on loss in 19 of 35 samples, and /sitemap.xml took 5-6 s on an edge HIT
(reports/page-body-time-2026-11-13). /sitemap.xml is now a sitemapindex naming /sitemaps/pages.xml (the public
pages, categories, task, best, compare and report pages) and /sitemaps/agents-N.xml (agent pages, AGENTS_PER_PART
each). The addresses and their order are the ones the single urlset had.
"""
import html
import re

NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'
ORIGIN = 'https://agentconcierge.biz'
AGENTS_PER_PART = 2000  # about 6.7 KB with gzip for /agent/<id> addresses (11-13 live data)
NAME = re.compile(r'^(?:pages|agents-[1-9][0-9]{0,2})$')
URL = re.compile(r'<url>.*?</url>', re.S)


def urlset(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="' + NS + '">\n'
            + ''.join('  ' + entry + '\n' for entry in entries) + '</urlset>')


def split(head, paths, origin=ORIGIN):
    """head: the urlset of the public panels (public_metadata.sitemap); paths: the other site paths, in order.
    Returns {part name: urlset xml}, 'pages' first."""
    pages = [entry for entry in URL.findall(head)]
    agents = []
    for path in paths:
        entry = '<url><loc>' + origin + html.escape(path) + '</loc></url>'
        (agents if path.startswith('/agent/') else pages).append(entry)
    parts = {'pages': urlset(pages)}
    for n, start in enumerate(range(0, len(agents), AGENTS_PER_PART), 1):
        parts['agents-%d' % n] = urlset(agents[start:start + AGENTS_PER_PART])
    return parts


def index(base, parts, lastmod=None):
    stamp = '<lastmod>' + lastmod + '</lastmod>' if lastmod else ''
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="' + NS + '">\n'
            + ''.join('  <sitemap><loc>' + html.escape(base.rstrip('/') + '/sitemaps/' + name + '.xml', quote=False)
                      + '</loc>' + stamp + '</sitemap>\n' for name in parts) + '</sitemapindex>')


def is_part(path):
    """True for /sitemaps/<part>.xml (the edge and HEAD treat the parts like /sitemap.xml)."""
    return path.startswith('/sitemaps/') and path.endswith('.xml') and bool(NAME.match(path[10:-4]))


def expand(get, url):
    """Every page address of a sitemap: follows an index to its parts. get(url) -> response text."""
    text = get(url)
    locs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', text)
    if '<sitemapindex' not in text:
        return locs
    found = []
    for part in locs:
        found += re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', get(part))
    return found
