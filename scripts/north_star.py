"""Daily north star: successful executions by outside clients, with the funnel that leads to it (PM 11-12).

    .venv/bin/python -m scripts.north_star [--day YYYY-MM-DD] [--no-write]

The north star is the number of distinct (client, agent) pairs per KST day where an outside client got a
successful execution: a gateway MCP tools/call answered 2xx and not isError, a gateway A2A message/send answered,
the in-session MCP 'call' tool on /mcp that succeeded, or an edge run that succeeded. The funnel beside it: (1) outside recommendation requests (find_agents, Chat, MCP
search, A2A, Explore API), (2) gateway connection pairs (tools/list, A2A card), (3) successful execution pairs.
Internal requests (our User-Agents, X-Agentcon-QA, internal addresses, our edge principals), registry checkers,
evaluators and monitors ('probe'), marketing contacts ('outreach') and AI crawlers are not counted but kept in their
own columns; the names are in agent_market/concierge/traffic_classes.json. Nothing is excluded silently.

Sources: the frontend's anonymous day files (logs/service-frontend/traffic/<day>.<pid>.json; pairs are distinct
within one process, so a day with a deploy switch may count a pair twice — 'processes' says how many there were)
and edge_gateway_runs (one read-only connection). Before the frontend records the funnel (39140d17 and later),
the day files have no 'funnel' section; the line is then built from their older counters and says 'approx'.
"""
import argparse
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAFFIC = ROOT / 'logs/service-frontend/traffic'
OUT = ROOT / 'logs/ops/north-star.jsonl'
DSN = ROOT / 'gateway-data/postgres18/application.dsn'
INTERNAL_PRINCIPALS = ROOT / 'gateway-data/ops/internal-edge-principals.txt'
CLASSES = ('external', 'internal', 'probe', 'outreach', 'crawler')
# Client classes of the older day files (traffic.client_of) and the funnel class they stand for.
OLD_CLASS = {'internal': 'internal', 'ai_bot': 'crawler', 'verifier': 'probe', 'browser': 'external',
             'script': 'external', 'other': 'external', 'headless': 'external'}


def day_files(day, root=TRAFFIC):
    out = []
    for path in sorted(Path(root).glob(f'{day}.*.json')):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out


def from_funnel(files):
    """The recorded funnel, summed over the day's processes."""
    counts, distinct = Counter(), Counter()
    for data in files:
        counts.update(data.get('funnel') or {})
        distinct.update(data.get('funnel_distinct') or {})
    by = {cls: {'recommend': {'requests': 0, 'ok': 0, 'clients': distinct.get('recommend|' + cls, 0), 'surfaces': {}},
                'connect': {'pairs': distinct.get('connect|' + cls, 0), 'attempts': counts.get('connect|' + cls + '|attempt', 0),
                            'ok': counts.get('connect|' + cls + '|ok', 0)},
                'execute': {'pairs': distinct.get('execute|' + cls, 0), 'attempts': counts.get('execute|' + cls + '|attempt', 0),
                            'ok': counts.get('execute|' + cls + '|ok', 0)}} for cls in CLASSES}
    for key, value in counts.items():
        parts = key.split('|')
        if parts[0] == 'recommend' and len(parts) == 4 and parts[2] in by:
            block = by[parts[2]]['recommend']
            if parts[3] == 'all':
                block['requests'] += value
                block['surfaces'][parts[1]] = block['surfaces'].get(parts[1], 0) + value
            elif parts[3] == 'ok':
                block['ok'] += value
    return by


def from_older_counters(files):
    """An approximation from the counters every day file has: requests per entry and client class, MCP/A2A
    methods for non-internal clients. Pairs cannot be told apart, so they are None; probes on /mcp are known
    only by MCP method kind ('probe')."""
    requests, status, rpc = Counter(), Counter(), Counter()
    for data in files:
        requests.update(data.get('requests') or {})
        status.update(data.get('status') or {})
        rpc.update(data.get('rpc') or {})
    by = {cls: {'recommend': {'requests': 0, 'ok': None, 'clients': None, 'surfaces': {}},
                'connect': {'pairs': None, 'attempts': 0, 'ok': None},
                'execute': {'pairs': None, 'attempts': None, 'ok': None}} for cls in CLASSES}

    def add(cls, surface, value):
        block = by[cls]['recommend']
        block['requests'] += value
        block['surfaces'][surface] = block['surfaces'].get(surface, 0) + value
    for key, value in requests.items():
        entry, _, client = key.partition('|')
        cls = OLD_CLASS.get(client, 'external')
        if entry in ('explore', 'chat'):
            add(cls, 'explore' if entry == 'explore' else 'rest_chat', value)
        elif entry == 'gateway':
            by[cls]['connect']['attempts'] += value
    for key, value in rpc.items():   # non-internal only; tools/call is any tool, not only recommendations
        entry, method, kind = (key.split('|') + ['', ''])[:3]
        cls = 'probe' if kind == 'probe' else 'external'
        if entry == 'mcp' and method == 'tools/call':
            add(cls, 'mcp_tools_call_any', value)
        elif entry == 'a2a' and method in ('message/send', 'SendMessage'):
            add(cls, 'a2a', value)
    for key, value in status.items():
        entry, client, klass = (key.split('|') + ['', ''])[:3]
        if entry == 'gateway' and klass == '2xx':
            block = by[OLD_CLASS.get(client, 'external')]['connect']
            block['ok'] = (block['ok'] or 0) + value
    return by


def edge_runs(day, dsn_file=DSN, principals_file=INTERNAL_PRINCIPALS, connect=None):
    """Succeeded edge runs of the day: distinct (principal, agent) pairs, ours apart."""
    start = datetime.strptime(day, '%Y-%m-%d').timestamp()
    ours = set()
    try:
        ours = {line.strip() for line in Path(principals_file).read_text().splitlines()
                if line.strip() and not line.startswith('#')}
    except OSError:
        pass
    if connect is None:
        import psycopg
        dsn = Path(dsn_file).read_text().strip()
        def connect():
            return psycopg.connect(dsn, autocommit=True,
                                   options='-c default_transaction_read_only=on -c statement_timeout=5000')
    with connect() as connection:
        rows = connection.execute('SELECT principal, resource_id, state FROM edge_gateway_runs WHERE created >= %s AND '
                                  'created < %s', (start, start + 86400)).fetchall()
    out = {'external': {'pairs': set(), 'attempts': 0, 'ok': 0}, 'internal': {'pairs': set(), 'attempts': 0, 'ok': 0}}
    for principal, rid, state in rows:
        block = out['internal' if principal in ours else 'external']
        block['attempts'] += 1
        if state == 'succeeded':
            block['ok'] += 1
            block['pairs'].add((principal, rid))
    return {cls: {**v, 'pairs': len(v['pairs'])} for cls, v in out.items()}


def build(day, files=None, edge=None):
    files = day_files(day) if files is None else files
    recorded = any('funnel' in data for data in files)
    by = from_funnel(files) if recorded else from_older_counters(files)
    edge = edge if edge is not None else edge_runs(day)
    external = by['external']
    origin_pairs = external['execute']['pairs']
    north = (origin_pairs or 0) + edge['external']['pairs']
    stages = (('recommend', external['recommend']['requests']), ('connect', external['connect']['pairs']
              if recorded else external['connect']['ok']), ('execute', north))
    breaks = next((name for name, value in stages if not value), None)
    fallbacks = Counter()
    for data in files:
        fallbacks.update({k.split('|', 1)[1]: v for k, v in (data.get('funnel') or {}).items() if k.startswith('edge_fallback|')})
    return {'day': day, 'at': time.strftime('%Y-%m-%d %H:%M'), 'north_star': north,
            'edge_fallbacks': dict(fallbacks),   # Edge -> Origin gateway hand-offs by reason (handshake, rate)
            'basis': 'recorded' if recorded else 'approx', 'processes': len(files),
            'breaks_at': breaks, 'funnel': external, 'edge': edge,
            'excluded': {cls: by[cls] for cls in ('internal', 'probe', 'outreach', 'crawler')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--day', default=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))
    parser.add_argument('--no-write', action='store_true')
    args = parser.parse_args(argv)
    record = build(args.day)
    if not args.no_write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, 'a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
