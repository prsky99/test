"""Rebuild the local OpenSearch lexical index for Explore and swap its alias atomically.

Reads listings read-only from the application PostgreSQL (one connection), builds a new index,
checks it, points the alias at it and removes older builds. A failed build never replaces the
serving index. Usage: explore_opensearch_sync.py [--loop SECONDS] [--url http://127.0.0.1:9200]
"""
import argparse
import ipaddress
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIAS = 'agentcon-lexical'
PREFIX = ALIAS + '-'
BATCH = 4000
MIN_RATIO = 0.9
# The index is small (~170 MB) and rebuilt every few minutes: preload its files into the page
# cache when it opens, so the first searches after an alias swap do not read from disk.
SETTINGS = {'number_of_shards': 1, 'number_of_replicas': 0, 'refresh_interval': '-1',
            'store': {'preload': ['nvd', 'dvd', 'tim', 'tip', 'doc', 'pos', 'pay']},
            'analysis': {'analyzer': {'folded': {'tokenizer': 'standard', 'filter': ['lowercase', 'asciifolding']}}}}
# Searches return ids only, so _source is not stored; filter-only fields need no doc values.
MAPPINGS = {'dynamic': 'strict', '_source': {'enabled': False}, 'properties': {
    'name': {'type': 'text', 'analyzer': 'folded'}, 'description': {'type': 'text', 'analyzer': 'folded'},
    'kind': {'type': 'keyword', 'doc_values': False}, 'category': {'type': 'keyword', 'doc_values': False},
    'eligible': {'type': 'boolean', 'doc_values': False}, 'last_ok_at': {'type': 'double'}}}
# Common task words; the new index answers them before it starts serving.
WARM_WORDS = ('weather forecast translate news search github issues pdf crypto price email image generation '
              'research papers stock quotes maps documentation database sql calendar sms payment agent').split()
LISTINGS = """SELECT r.id, f.name, f.description, r.kind, r.category,
    (r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')),
    r.last_ok_at FROM public.resources r JOIN public.resources_fts f ON f.rowid=r.id"""


class Client:
    def __init__(self, base, opener=urllib.request.urlopen):
        url = urllib.parse.urlsplit(base)
        if url.scheme != 'http' or not (url.hostname == 'localhost' or ipaddress.ip_address(url.hostname or '0.0.0.0').is_loopback):
            raise ValueError('OpenSearch must be a loopback http URL.')
        self.base, self.opener = base.rstrip('/'), opener

    def call(self, method, path, body=None, ndjson=False):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={
            'Content-Type': 'application/x-ndjson' if ndjson else 'application/json'})
        with self.opener(request, timeout=120) as response:
            return json.loads(response.read() or b'{}')


def documents(rows):
    for rid, name, description, kind, category, eligible, last_ok in rows:
        yield {'index': {'_id': str(rid)}}, {'name': name or '', 'description': description or '', 'kind': kind,
                                             'category': category, 'eligible': bool(eligible), 'last_ok_at': float(last_ok or 0)}


def current_targets(client):
    try:
        return sorted(client.call('GET', f'/_alias/{ALIAS}'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def rebuild(client, rows, *, now=time.time):
    """Load ROWS into a new index; swap the alias only when the new index looks complete."""
    name = PREFIX + time.strftime('%Y%m%d%H%M%S', time.gmtime(now()))
    client.call('PUT', '/' + name, {'settings': SETTINGS, 'mappings': MAPPINGS})
    try:
        sent, batch = 0, []
        for action, source in documents(rows):
            batch += [json.dumps(action), json.dumps(source)]
            if len(batch) >= 2 * BATCH:
                sent += _bulk(client, name, batch); batch = []
        if batch:
            sent += _bulk(client, name, batch)
        client.call('PUT', f'/{name}/_settings', {'index': {'refresh_interval': '1s'}})
        client.call('POST', f'/{name}/_refresh')
        count = client.call('GET', f'/{name}/_count')['count']
        previous = current_targets(client)
        before = sum(client.call('GET', f'/{old}/_count')['count'] for old in previous)
        if count != sent or count == 0 or (before and count < MIN_RATIO * before):
            raise RuntimeError(f'new index incomplete: sent={sent} count={count} serving={before}')
        warm(client, name)
        actions = [{'add': {'index': name, 'alias': ALIAS}}] + [{'remove': {'index': old, 'alias': ALIAS}} for old in previous]
        client.call('POST', '/_aliases', {'actions': actions})
    except BaseException:
        client.call('DELETE', '/' + name)
        raise
    for old in previous:
        client.call('DELETE', '/' + old)
    return {'index': name, 'count': count, 'replaced': previous}


def warm(client, name):
    """Run the adapter's own query shapes on the new index so its caches and JIT are warm."""
    from agent_market.concierge.opensearch_lexical import query_body
    for word in WARM_WORDS:
        for kind in ('a2a', 'mcp'):
            for joiner in (' ', ' OR '):
                client.call('POST', f'/{name}/_search', query_body([word], joiner, kind, None))


def _bulk(client, name, lines):
    result = client.call('POST', f'/{name}/_bulk', ('\n'.join(lines) + '\n').encode(), ndjson=True)
    if result.get('errors'):
        raise RuntimeError('bulk indexing reported errors')
    return len(lines) // 2


def read_listings():
    sys.path.insert(0, str(ROOT))
    from scripts.agentcon_config import read_settings
    from agent_market import application_runtime as rt
    settings = read_settings(str(ROOT / 'gateway-data/agentcon.env'))
    path = settings.get('APPLICATION_POSTGRES_DSN_FILE')
    if path and not Path(path).is_absolute():
        path = str(ROOT / path)
    dsn = rt._private_bytes(path, 16384).decode('utf-8').strip()
    connection = rt._connect(dsn)
    connection.execute('SET default_transaction_read_only=on')
    return connection


def run_once(client):
    started = time.time()
    with read_listings() as connection:
        with connection.transaction(), connection.cursor(name='explore_opensearch_sync') as cursor:
            cursor.itersize = 5000
            cursor.execute(LISTINGS)
            result = rebuild(client, cursor)
    result['seconds'] = round(time.time() - started, 1)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9200')
    parser.add_argument('--loop', type=int, default=0, help='seconds between rebuilds; 0 runs once')
    args = parser.parse_args(argv)
    client = Client(args.url)
    while True:
        try:
            print(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), **run_once(client)}), flush=True)
        except Exception as exc:
            print(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'error': f'{type(exc).__name__}: {exc}'[:300]}), flush=True)
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        time.sleep(max(60, args.loop))


if __name__ == '__main__':
    sys.exit(main())
