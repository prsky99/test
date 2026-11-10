"""Optional OpenSearch lexical candidates for Explore; PostgreSQL stays the source of truth.

Settings live in <project>/gateway-data/explore-opensearch.json (owner-only 0600/0400), e.g.
{"mode": "shadow", "url": "http://127.0.0.1:9200", "index": "agentcon-lexical", "timeout_ms": 300, "shadow_rate": 0.2}
- off (default, also for a missing or invalid file): PostgreSQL only.
- shadow: PostgreSQL serves; a sample of searches is repeated on OpenSearch in the background
  and only the overlap and latency are logged.
- on: OpenSearch serves; any failure or timeout uses PostgreSQL and pauses OpenSearch for a while.
Candidates only widen recall: ranking_rows() re-reads active, health and security in PostgreSQL,
so a stale index can delay a new listing but never admit a withdrawn one.
"""
import collections
import ipaddress
import json
import logging
import os
import queue
import random
import re
import stat
import threading
import time
import urllib.parse
import urllib.request

MODES = ('off', 'shadow', 'on')
SIZE = 300
PAUSE_SECONDS = 30.0
RELOAD_SECONDS = 5.0
_log = logging.getLogger(__name__)


class Unavailable(Exception):
    pass


def settings_path():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return os.path.join(root, 'gateway-data', 'explore-opensearch.json') if root else None


def parse_settings(raw):
    """Validated settings, or None (off). Only a loopback HTTP endpoint is accepted."""
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if type(value) is not dict or value.get('mode') not in MODES:
        return None
    if value['mode'] == 'off':
        return None
    url = urllib.parse.urlsplit(str(value.get('url') or ''))
    try:
        host_ok = url.hostname == 'localhost' or ipaddress.ip_address(url.hostname or '').is_loopback
        port = url.port
    except ValueError:
        return None
    index = value.get('index', 'agentcon-lexical')
    timeout = value.get('timeout_ms', 300)
    rate = value.get('shadow_rate', 0.2)
    if (url.scheme != 'http' or not host_ok or url.path not in ('', '/') or url.query or url.username
            or type(index) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', index)
            or type(timeout) is not int or not 50 <= timeout <= 2000
            or type(rate) not in (int, float) or not 0 <= rate <= 1):
        return None
    base = f'http://{url.hostname if url.hostname != "::1" else "[::1]"}:{port or 9200}'
    return {'mode': value['mode'], 'search': f'{base}/{index}/_search', 'timeout': timeout / 1000, 'rate': float(rate)}


class _Settings:
    def __init__(self):
        self.lock, self.checked, self.key, self.value = threading.Lock(), 0.0, None, None

    def current(self):
        now = time.monotonic()
        with self.lock:
            if now - self.checked < RELOAD_SECONDS:
                return self.value
            self.checked = now
        path, value, key = settings_path(), None, None
        if path:
            try:
                info = os.lstat(path)
                key = (info.st_ino, info.st_mtime_ns, info.st_size)
                if key == self.key:
                    return self.value
                if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) in (0o400, 0o600) and info.st_size <= 4096):
                    with open(path, 'rb') as stream:
                        value = parse_settings(stream.read(4096))
            except OSError:
                value = None
        with self.lock:
            self.key, self.value = key, value
        return value


_settings = _Settings()


def query_body(words, joiner, kind, category, size=SIZE):
    """The PostgreSQL lexical predicate as BM25: every word (any inflection) for ' ', any word for ' OR '."""
    from .discovery import LEXICAL_FORMS
    def phrase(form):
        return {'multi_match': {'query': form, 'fields': ['name^2', 'description'], 'type': 'phrase'}}
    forms = [list(LEXICAL_FORMS.get(word, (word,))) for word in words]
    if joiner == ' ':
        match = {'bool': {'must': [{'bool': {'should': [phrase(f) for f in group], 'minimum_should_match': 1}}
                                   for group in forms]}}
    else:
        match = {'bool': {'should': [phrase(f) for group in forms for f in group], 'minimum_should_match': 1}}
    filters = [{'term': {'eligible': True}}]
    if kind:
        filters.append({'term': {'kind': kind}})
    if category:
        filters.append({'term': {'category': category}})
    return {'size': size, '_source': False, 'track_total_hits': False,
            'query': {'bool': {'must': [match], 'filter': filters}},
            'sort': ['_score', {'last_ok_at': 'desc'}]}


def search(config, words, joiner, kind, category, opener=urllib.request.urlopen):
    body = json.dumps(query_body(words, joiner, kind, category)).encode()
    request = urllib.request.Request(config['search'], data=body, headers={'Content-Type': 'application/json'})
    try:
        with opener(request, timeout=config['timeout']) as response:
            if response.status != 200:
                raise Unavailable('status')
            hits = json.loads(response.read(4 * 1024 * 1024))['hits']['hits']
        ids = [int(hit['_id']) for hit in hits]
    except Unavailable:
        raise
    except Exception as exc:
        raise Unavailable(type(exc).__name__) from None
    if len(ids) > SIZE or any(i <= 0 for i in ids):
        raise Unavailable('response')
    return ids


class _Breaker:
    def __init__(self, clock=time.monotonic):
        self.clock, self.until, self.lock = clock, 0.0, threading.Lock()

    def open(self):
        with self.lock:
            return self.clock() < self.until

    def trip(self):
        with self.lock:
            self.until = self.clock() + PAUSE_SECONDS


class _Shadow:
    """One background worker; a full queue drops the comparison, never the visitor's search."""

    def __init__(self, maximum=32, report_every=50):
        self.queue, self.thread, self.lock = queue.Queue(maximum), None, threading.Lock()
        self.report_every = report_every
        self.totals = collections.Counter()

    def submit(self, config, words, joiner, kind, category, postgres_ids, postgres_seconds):
        try:
            self.queue.put_nowait((config, list(words), joiner, kind, category, list(postgres_ids), postgres_seconds))
        except queue.Full:
            self.totals['dropped'] += 1
            return False
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name='explore-opensearch-shadow', daemon=True)
                self.thread.start()
        return True

    def compare(self, config, words, joiner, kind, category, postgres_ids, postgres_seconds, searcher=search):
        started = time.perf_counter()
        try:
            ids = searcher(config, words, joiner, kind, category)
        except Unavailable:
            self.totals['failed'] += 1
            return None
        seconds = time.perf_counter() - started
        both = set(ids) & set(postgres_ids)
        row = {'opensearch_ms': seconds * 1000, 'postgres_ms': postgres_seconds * 1000,
               'opensearch_hits': len(ids), 'postgres_hits': len(postgres_ids),
               'shared': len(both), 'jaccard': len(both) / max(1, len(set(ids) | set(postgres_ids)))}
        with self.lock:
            self.totals['compared'] += 1
            for name, value in row.items():
                self.totals[name] += value
            if self.totals['compared'] % self.report_every == 0:
                self.report()
        return row

    def report(self):
        n = max(1, self.totals['compared'])
        _log.info('Explore OpenSearch shadow: compared=%d failed=%d dropped=%d mean_ms opensearch=%.0f postgres=%.0f '
                  'mean_hits opensearch=%.0f postgres=%.0f mean_jaccard=%.3f', self.totals['compared'],
                  self.totals['failed'], self.totals['dropped'], self.totals['opensearch_ms'] / n,
                  self.totals['postgres_ms'] / n, self.totals['opensearch_hits'] / n,
                  self.totals['postgres_hits'] / n, self.totals['jaccard'] / n)

    def _run(self):
        while True:
            try:
                item = self.queue.get(timeout=30)
            except queue.Empty:
                return
            try:
                self.compare(*item)
            except Exception:
                _log.warning('Explore OpenSearch shadow comparison skipped', exc_info=False)


_breaker = _Breaker()
_shadow = _Shadow()


def lexical_ids(words, joiner, kind, category, postgres, *, config=None, searcher=search, sample=random.random):
    """Candidate ids for one lexical pass; POSTGRES() runs the existing SQL and stays the fallback."""
    config = _settings.current() if config is None else config
    if config is None:
        return postgres()
    if config['mode'] == 'on' and not _breaker.open():
        try:
            from .retrieval_metrics import stage
            with stage('opensearch'):
                return searcher(config, words, joiner, kind, category)
        except Unavailable as exc:
            _breaker.trip()
            _log.warning('Explore OpenSearch unavailable (%s); PostgreSQL serves for %.0fs', exc, PAUSE_SECONDS)
        return postgres()
    started = time.perf_counter()
    ids = postgres()
    if config['mode'] == 'shadow' and sample() < config['rate']:
        _shadow.submit(config, words, joiner, kind, category, ids, time.perf_counter() - started)
    return ids
