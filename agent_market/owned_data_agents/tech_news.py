"""Technology news from a stored GDELT bundle (PM 11-16 decision).

GDELT's DOC API answered 429 and took 12.9 s on 11-16, so a request never calls it. Instead one bundle of recent
technology articles (titles, outlets, dates and links only; never the article text) is fetched at most once an hour
in a background thread and stored in a shared file; every request filters that bundle by the query words in a few
milliseconds. A failed refresh keeps the previous bundle for up to MAX_STALE (6 hours) and the answer states when it
was collected; past that the agent says it is busy. When no stored article matches the query, the newest articles are
returned instead and the answer says so.

Kept apart from catalog.py, engine.py, english.py and dispatch.py, which are hashed into the research/news adapter
digest. Source terms: The GDELT Project allows unlimited and unrestricted use, including commercial, with a citation
and link (https://www.gdeltproject.org/about.html#termsofuse).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
TTL = 3600            # refresh an hour after the last collection
MAX_STALE = 21600     # serve a bundle up to 6 hours old
RETRY = 300           # after a failed refresh, wait 5 minutes before the next try
MAX_RECORDS = 250
# Technology outlets (GDELT domain filter): every stored article is from one of them.
TECH_OUTLETS = ('techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com', 'zdnet.com', 'engadget.com',
                'venturebeat.com', 'theregister.com', 'techradar.com', 'cnet.com')
ROOT = Path(__file__).resolve().parents[2]
# Services run from the repository root (a release folder has no gateway-data): one shared file for every process.
PATH = Path(os.environ.get('OWNED_NEWS_BUNDLE') or ((ROOT if (ROOT / 'gateway-data').is_dir() else Path.cwd())
                                                   / 'gateway-data/owned-data-agents/tech-news.json'))
WORD = re.compile(r'[0-9A-Za-z][0-9A-Za-z+#.-]*')


class Busy(ValueError):
    """No bundle fresh enough to answer from (none yet, or older than MAX_STALE)."""


def bundle_query() -> str:
    return '(' + ' OR '.join('domainis:' + d for d in TECH_OUTLETS) + ')'


def parse(raw: dict, now: datetime) -> list[dict]:
    """GDELT artlist JSON -> [{title, url, published_at, source}] from technology outlets, newest first."""
    from .engine import clean, public_link
    rows, seen = [], set()
    for art in raw.get('articles') or []:
        if type(art) is not dict:
            continue
        link, title = public_link(art.get('url')), clean(art.get('title'))
        outlet = clean(art.get('domain'), 100).lower()
        stamp = str(art.get('seendate') or '')
        if not (link and title and outlet in TECH_OUTLETS and re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', stamp)):
            continue
        at = datetime.strptime(stamp, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        if at > now or link in seen:
            continue
        rows.append({'title': title, 'url': link, 'published_at': at.isoformat().replace('+00:00', 'Z'),
                     'source': outlet})
        seen.add(link)
    rows.sort(key=lambda r: r['published_at'], reverse=True)
    return rows[:MAX_RECORDS]


def select(articles: list[dict], query: str, limit: int) -> tuple[list[dict], str | None]:
    """Articles whose title holds every query word (3+ letters; shorter words only when nothing else is given);
    when none match, the newest articles and a note saying so."""
    words = [w.casefold() for w in WORD.findall(query)]
    words = [w for w in words if len(w) >= 3] or words
    def hit(row):
        title = row['title'].casefold()
        return all(re.search(r'(?<![0-9a-z])' + re.escape(w) + r'(?![0-9a-z])', title) for w in words)
    found = [r for r in articles if hit(r)] if words else []
    if found:
        return found[:limit], None
    return articles[:limit], 'No stored technology article matched the query; these are the latest technology news.'


class Store:
    """The bundle in memory and on disk, with one background refresh at a time across processes."""

    def __init__(self, fetch, path: Path | None = None, clock=time.time, utc_now=None, background=True):
        self.fetch, self.path, self.clock = fetch, Path(path or PATH), clock   # PATH read now: tests repoint it
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.background = background
        self.lock = threading.Lock()
        self.memo = None            # (mtime, bundle)
        self.refreshing = False
        self.next_try = 0.

    def read(self) -> dict | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if self.memo and self.memo[0] == mtime:
            return self.memo[1]
        try:
            bundle = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(bundle, dict) or not isinstance(bundle.get('articles'), list):
            return None
        self.memo = (mtime, bundle)
        return bundle

    def get(self) -> tuple[dict, int]:
        """(bundle, age seconds); starts a refresh when it is due; Busy when nothing usable is stored."""
        bundle = self.read()
        age = int(max(0, self.clock() - bundle['fetched_epoch'])) if bundle else None
        if bundle is None or age >= TTL:
            self.refresh_soon()
            if not self.background:              # a synchronous store (tests, warm-up) answers from the new bundle
                bundle = self.read() or bundle
                age = int(max(0, self.clock() - bundle['fetched_epoch'])) if bundle else None
        if bundle is None or age > MAX_STALE:
            raise Busy('The data source is busy. Try again later.')
        return bundle, age

    def refresh_soon(self):
        with self.lock:
            if self.refreshing or self.clock() < self.next_try:
                return
            self.refreshing = True
        if self.background:
            threading.Thread(target=self._refresh, name='owned-tech-news-refresh', daemon=True).start()
        else:
            self._refresh()

    def _refresh(self):
        ok = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path.with_suffix('.lock'), 'a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return                       # another process is refreshing
                current = self.read()
                if current and self.clock() - current['fetched_epoch'] < TTL:
                    ok = True
                    return                       # refreshed by another process meanwhile
                raw = self.fetch()
                now = self.utc_now()
                articles = parse(raw, now)
                if not articles:
                    return
                tmp = self.path.with_suffix('.tmp')
                tmp.write_text(json.dumps({'fetched_at': now.isoformat().replace('+00:00', 'Z'),
                                           'fetched_epoch': self.clock(), 'articles': articles}))
                os.replace(tmp, self.path)
                ok = True
        except Exception:      # noqa: BLE001 - a failed refresh keeps the previous bundle
            pass
        finally:
            with self.lock:
                self.refreshing = False
                if not ok:
                    self.next_try = self.clock() + RETRY
