"""Hourly record of vector index use (11-12 PM: watch the shared graph before it can be dropped).

Since D' (11-12 05:16) Explore and find_agents read the per-kind halfvec graphs; the shared graph
(embeddings_cosine_hnsw, 1.6 GB) is only maintained on every insert. It may be dropped (a separate,
approved DB change) once it has had no scans for 72 hours after the remaining kind=None readers move
to the per-kind graphs. This appends one line per run to logs/ops/vector-index-usage.jsonl with the
counters and the change since the previous line: scans, buffer hits, buffer reads, hit rate.

One read-only connection (default_transaction_read_only=on); nothing is written to the database.
Usage: .venv/bin/python -m scripts.vector_index_usage [--dsn-file PATH] [--out PATH]
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DSN = ROOT / 'gateway-data/postgres18/application.dsn'
OUT = ROOT / 'logs/ops/vector-index-usage.jsonl'
QUERY = """SELECT s.indexrelname, s.idx_scan, io.idx_blks_hit, io.idx_blks_read, pg_relation_size(s.indexrelid)
    FROM pg_stat_all_indexes s JOIN pg_statio_all_indexes io USING (indexrelid)
    WHERE s.schemaname='agentcon_search' AND s.indexrelname LIKE 'embeddings_%%' ORDER BY 1"""
FIELDS = ('scans', 'hit', 'read')


def counters(rows):
    return {name: {'scans': scans, 'hit': hit, 'read': read, 'bytes': size} for name, scans, hit, read, size in rows}


def change(before, after):
    """Per-index difference between two counter snapshots; a reset (smaller value) counts from zero."""
    out = {}
    for name, now in after.items():
        old = (before or {}).get(name) or {}
        delta = {key: now[key] - old[key] if key in old and now[key] >= old[key] else now[key] for key in FIELDS}
        total = delta['hit'] + delta['read']
        delta['hit_rate'] = round(100.0 * delta['hit'] / total, 1) if total else None
        out[name] = delta
    return out


def last_line(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dsn-file', default=str(DSN))
    parser.add_argument('--out', default=str(OUT))
    args = parser.parse_args(argv)
    import psycopg
    dsn = Path(args.dsn_file).read_text().strip()
    with psycopg.connect(dsn, autocommit=True,
                         options='-c default_transaction_read_only=on -c statement_timeout=5000') as connection:
        now = counters(connection.execute(QUERY).fetchall())
    previous = last_line(args.out)
    record = {'at': time.strftime('%Y-%m-%d %H:%M'), 'ts': round(time.time()),
              'since_ts': previous.get('ts') if previous else None,
              'counters': now, 'change': change(previous.get('counters') if previous else None, now)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'a') as stream:
        stream.write(json.dumps(record) + '\n')
    shared = record['change'].get('embeddings_cosine_hnsw') or {}
    print(json.dumps({'at': record['at'], 'shared_graph_scans': shared.get('scans'), 'shared_graph_read': shared.get('read'),
                      'kind_scans': {name: value['scans'] for name, value in record['change'].items() if name.startswith('embeddings_half_')}}))


if __name__ == '__main__':
    main()
