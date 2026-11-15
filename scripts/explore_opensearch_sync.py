"""Keep the local OpenSearch lexical index for Explore in step with the listings.

Reads listings read-only from the application PostgreSQL (one connection). A full build makes a new index, checks
it, warms it, points the alias at it and removes older builds; a failed build never replaces the serving index.
Between full builds (11-15 운영·SRE 16:4x: a full build every 10.5 minutes took 26-70 s of CPU and left an empty
page cache just before user_slo's 15:09 measurement, 6.72 s), each round writes only the listings whose indexed
fields changed (about 150 in 10 minutes) and deletes the ones gone, into the serving index; the index and its caches
stay. One full build a night (FULL_HOUR, minutes :20-:45, away from the hourly :55-:10 measurement), or when the
saved state does not match the serving index or a round changes more than MAX_CHANGE of it.
Usage: explore_opensearch_sync.py [--loop SECONDS] [--full] [--url http://127.0.0.1:9200]
"""
import argparse
import hashlib
import os
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
STATE = ROOT / 'gateway-data/opensearch/lexical-state.json'   # serving index name and a digest per listing
FULL_HOUR, FULL_MINUTES = 3, (20, 45)
MAX_CHANGE = 0.2
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
ELIGIBLE = """(r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review'))"""
FROM = "FROM public.resources r JOIN public.resources_fts f ON f.rowid=r.id"
LISTINGS = f"SELECT r.id, f.name, f.description, r.kind, r.category, {ELIGIBLE}, r.last_ok_at {FROM}"
# 11-15 16:4x: reading every listing's text took about 6 of the first update round's 8.8 s. The database computes a
# short digest per listing instead (about 2 s for 427,935), and only changed listings are read in full.
DIGESTS = (f"SELECT r.id::text, left(md5(concat_ws(chr(31), f.name, f.description, r.kind, r.category, {ELIGIBLE}::text, "
           f"r.last_ok_at::text)), 16) {FROM}")
CHANGED = LISTINGS + " WHERE r.id = ANY(%s)"


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


def digest(source):
    return hashlib.blake2b(json.dumps(source, sort_keys=True).encode(), digest_size=8).hexdigest()


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
        # a delete that finds nothing is not an error for us (the listing is gone either way)
        bad = [item for item in result.get('items') or [] for op, r in item.items()
               if r.get('error') and not (op == 'delete' and r.get('status') == 404)]
        if bad or not result.get('items'):
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


class NeedFull(Exception):
    """The incremental round cannot be trusted; the caller builds a full index instead."""


class RowSource:
    """Listings as rows, digested here (tests, and any caller without the database's digest)."""
    kind = 'py'

    def __init__(self, rows_for):
        self.rows_for = rows_for

    def rows(self):
        return self.rows_for()

    def digests(self):
        return {action['index']['_id']: digest(source) for action, source in documents(self.rows())}

    def fetch(self, ids):
        wanted = set(ids)
        return [row for row in self.rows() if str(row[0]) in wanted]


class SqlSource:
    """Listings from the application database: digests computed there, full rows read only when asked."""
    kind = 'md5-16'

    def __init__(self, connection):
        self.connection = connection

    def rows(self):
        cursor = self.connection.cursor(name=f'explore_opensearch_sync_{time.monotonic_ns()}')
        cursor.itersize = 5000
        cursor.execute(LISTINGS)
        return cursor

    def digests(self):
        with self.connection.cursor() as cursor:
            cursor.execute(DIGESTS)
            return {rid: d for rid, d in cursor}

    def fetch(self, ids):
        if not ids:
            return []
        with self.connection.cursor() as cursor:
            cursor.execute(CHANGED, ([int(i) for i in ids],))
            return cursor.fetchall()


def update(client, index, source, hashes):
    """Write the listings whose digest changed and delete the ones gone, into INDEX (the serving index). HASHES is
    the saved digest per id and is replaced in place only when the round succeeds."""
    fresh = source.digests()
    changed = [rid for rid, d in fresh.items() if hashes.get(rid) != d]
    gone = [rid for rid in hashes if rid not in fresh]
    if hashes and len(changed) + len(gone) > MAX_CHANGE * len(hashes):
        raise NeedFull(f'{len(changed)} changed and {len(gone)} gone of {len(hashes)}')
    ops = [[json.dumps(action), json.dumps(doc)] for action, doc in documents(source.fetch(changed))]
    if len(ops) != len(changed):
        raise NeedFull(f'{len(changed)} changed but {len(ops)} read')
    ops += [[json.dumps({'delete': {'_id': rid}})] for rid in gone]   # one op = its lines (index two, delete one)
    for start in range(0, len(ops), BATCH):
        _bulk(client, index, [line for op in ops[start:start + BATCH] for line in op])
    if ops:
        client.call('POST', f'/{index}/_refresh')
    count = client.call('GET', f'/{index}/_count')['count']
    if count != len(fresh):
        raise NeedFull(f'serving index holds {count}, listings {len(fresh)}')
    hashes.clear(); hashes.update(fresh)
    return {'index': index, 'mode': 'update', 'count': count, 'upserted': len(changed), 'deleted': len(gone)}


def load_state(path=None):
    try:
        state = json.loads(Path(path or STATE).read_text())
        return state if isinstance(state.get('hashes'), dict) and state.get('index') else None
    except (OSError, ValueError, AttributeError):
        return None


def save_state(state, path=None):
    path = Path(path or STATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


def full_due(state, now):
    """A full build once a night: FULL_HOUR, minutes FULL_MINUTES, when none was built that local day."""
    local = time.localtime(now)
    if local.tm_hour != FULL_HOUR or not FULL_MINUTES[0] <= local.tm_min <= FULL_MINUTES[1]:
        return False
    return time.strftime('%Y-%m-%d', time.localtime(state.get('built_at') or 0)) != time.strftime('%Y-%m-%d', local)


def sync_rows(client, source, *, full=False, now=time.time, state_path=None):
    """One round. SOURCE is a RowSource/SqlSource, or a callable that opens a fresh listing iterator."""
    source = source if hasattr(source, 'digests') else RowSource(source)
    state, at = load_state(state_path), now()
    serving = current_targets(client)
    reason = ('asked' if full else 'no saved state' if state is None else
              'serving index differs from the saved state' if serving != [state['index']] else
              'digest kind changed' if state.get('digest', 'py') != source.kind else
              'nightly' if full_due(state, at) else None)
    if reason is None:
        try:
            result = update(client, state['index'], source, state['hashes'])
            save_state(state, state_path)
            return result
        except NeedFull as exc:
            reason = f'update refused: {exc}'
    result = rebuild(client, source.rows(), now=now)
    save_state({'index': result['index'], 'built_at': at, 'digest': source.kind, 'hashes': source.digests()}, state_path)
    return {**result, 'mode': 'full', 'reason': reason}


def run_once(client, full=False):
    started = time.time()
    with read_listings() as connection:
        # one snapshot for the round: the digests saved after a full build describe exactly the rows it indexed
        import psycopg
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with connection.transaction():
            result = sync_rows(client, SqlSource(connection), full=full)
    result['seconds'] = round(time.time() - started, 1)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9200')
    parser.add_argument('--loop', type=int, default=0, help='seconds between rounds; 0 runs once')
    parser.add_argument('--full', action='store_true', help='build a full new index this (first) round')
    args = parser.parse_args(argv)
    client = Client(args.url)
    full = args.full
    while True:
        try:
            print(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), **run_once(client, full)}), flush=True)
            full = False
        except Exception as exc:
            print(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'error': f'{type(exc).__name__}: {exc}'[:300]}), flush=True)
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        time.sleep(max(60, args.loop))


if __name__ == '__main__':
    sys.exit(main())
