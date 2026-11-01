"""Generate index-time query expansions for recommendable listings (read-only catalog).

Usage: python -m scripts.build_query_expansions [--limit N] [--workers 4]

The catalog is read in read-only transactions; only the expansion file under
gateway-data/search/ is written. Listings with an unchanged source keep their
entry, so the job resumes. A2A and MCP listings that passed a call check come
first because Chat can recommend them.
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ELIGIBLE = ("active=1 AND health_status IN ('healthy','reachable') AND COALESCE(eval_security,'') NOT IN ('quarantine','review') "
            "AND trial_ok=1 AND kind IN ('mcp','a2a')")


def open_catalog():
    from scripts.agentcon_config import read_settings, read_local_model_settings
    settings = read_settings(str(ROOT / 'gateway-data/agentcon.env'))
    settings.update(read_local_model_settings(str(ROOT / 'gateway-data/local-model.env')))
    for key in ('GATEWAY_DB', 'APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE'):
        if settings.get(key) and not Path(settings[key]).is_absolute():
            settings[key] = str(ROOT / settings[key])
    os.environ.update(settings)
    for name in [n for n in os.environ if n.startswith('PG')]:
        os.environ.pop(name)
    from agent_market import application_runtime as runtime
    from agent_market.config import GatewayConfig

    def read_only(dsn):
        connection = runtime._connect(dsn)
        connection.execute('SET default_transaction_read_only=on')
        return connection
    config = GatewayConfig.from_env()
    storage = runtime.open_runtime_storage(config.db_path, values=dict(os.environ), connector=read_only)
    return storage, settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=30000)
    parser.add_argument('--workers', type=int, default=4)
    # Prefer the standby endpoint so visitor-facing generation keeps its capacity.
    parser.add_argument('--endpoint', choices=('primary', 'standby'), default='standby')
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or not 1 <= args.limit <= 100000:
        raise SystemExit('Choose 1-8 workers and a limit up to 100000.')
    import httpx
    from agent_market.concierge import query_expansion as qe
    from agent_market.concierge.selection import _advertised_tools
    storage, settings = open_catalog()
    store = storage.store
    out = ROOT / 'gateway-data' / 'search' / 'query-expansions.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out.is_file():
        for line in out.open(encoding='utf-8'):
            try:
                row = json.loads(line)
                done[int(row['id'])] = row['hash']
            except (ValueError, KeyError, TypeError):
                continue
    with store.tx(readonly=True):
        ids = [row[0] for row in store._connection.execute(
            f"SELECT id FROM public.resources WHERE {ELIGIBLE} ORDER BY (kind='mcp') DESC, last_ok_at DESC NULLS LAST LIMIT %s",
            (args.limit,)).fetchall()]
    from scripts.agentcon_config import read_local_model_fallback_settings
    standby = read_local_model_fallback_settings(ROOT / 'gateway-data/local-model-fallback.env').get('WORKSPACE_MODEL_FALLBACK_URL')
    endpoint = standby if args.endpoint == 'standby' and standby else settings['WORKSPACE_MODEL_URL']
    model = settings['WORKSPACE_MODEL_NAME']
    http = httpx.Client(timeout=90)
    lock = threading.Lock()
    by_source, counts = {}, {'written': 0, 'reused': 0, 'skipped': 0, 'failed': 0}
    started = time.monotonic()

    def work(rid):
        with lock:
            resource = store.resource(rid)
        if not resource:
            return
        tools = _advertised_tools(resource)
        digest = qe.source_hash(resource, tools)
        if done.get(rid) == digest:
            counts['skipped'] += 1
            return
        # Sibling listings often repeat one card; generate once per identical source text.
        key = qe.source_hash({'name': resource.get('name'), 'description': resource.get('description')}, tools)
        queries = by_source.get(key)
        if queries is None:
            try:
                # The model server queues requests; a short timeout only turns queueing into failures.
                queries = qe.generate(http, endpoint, model, resource, tools, timeout=90)
            except Exception:
                counts['failed'] += 1
                return
            by_source[key] = queries
        else:
            counts['reused'] += 1
        if not queries:
            counts['failed'] += 1
            return
        line = json.dumps({'id': rid, 'kind': resource['kind'], 'hash': digest, 'profile': qe.PROFILE,
                           'queries': queries}, ensure_ascii=True)
        with lock:
            with out.open('a', encoding='utf-8') as handle:
                handle.write(line + '\n')
            counts['written'] += 1
            if counts['written'] % 200 == 0:
                print(json.dumps({**counts, 'seconds': round(time.monotonic() - started)}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, ids))
    print(json.dumps({**counts, 'total': len(ids), 'seconds': round(time.monotonic() - started)}), flush=True)


if __name__ == '__main__':
    main()
