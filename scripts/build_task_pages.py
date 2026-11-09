"""Build the task-page snapshot by hand through the public Explore API (read-only, sequential, rate-limited).

    .venv/bin/python -m scripts.build_task_pages --out logs/service-frontend/public-pages/task-pages.json

The jobs service refreshes the same snapshot daily from its own store (concierge/task_pages_job.py).
This script is for a first build or a manual rebuild. The task list, the relevance rule and the
assembly live in agent_market/concierge/task_catalog.py.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from agent_market.concierge.task_catalog import TASKS, Assembler, plan, relevant, slugify, write  # noqa: F401 (re-exported for tests)

USER_AGENT = 'AgentConcierge-task-pages/1.0 (site owner test)'


def fetch(base, query, verified, limit, **filters):
    params = {'q': query, 'limit': str(limit), **{k: v for k, v in filters.items() if v}}
    if verified:
        params['verified'] = '1'
    request = urllib.request.Request(base.rstrip('/')+'/api/explore?'+urllib.parse.urlencode(params),
                                     headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response).get('items') or []
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(65)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5*(attempt+1))
    return []


def search(base, step):
    if step[0] == 'task':
        return fetch(base, step[2], step[3], step[4])
    return fetch(base, '', step[3], step[4], category=step[1], kind=step[2])


def status(base):
    request = urllib.request.Request(base.rstrip('/')+'/status.json', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response).get('catalog_snapshot')


def main(argv=None):
    from agent_market.broker.categories import CATEGORIES
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='https://agentconcierge.biz')
    parser.add_argument('--out', default='logs/service-frontend/public-pages/task-pages.json')
    parser.add_argument('--pause', type=float, default=0.7, help='seconds between requests (Explore allows about 120 a minute)')
    parser.add_argument('--only', nargs='*', help='task slugs to build (for a quick check)')
    parser.add_argument('--no-catalog', action='store_true')
    parser.add_argument('--extend', action='store_true',
                        help='no searches: add the catalog-based task pages to the existing snapshot (keeps its capture time)')
    args = parser.parse_args(argv)
    if args.extend:
        with open(args.out, encoding='utf-8') as handle:
            snapshot = json.load(handle)
        from agent_market.concierge.growth_pages import clean_agent
        from agent_market.concierge.task_catalog import catalog_tasks
        catalog = [a for a in map(clean_agent, snapshot.get('catalog') or []) if a]
        before = len(snapshot['tasks'])
        snapshot['tasks'] = catalog_tasks(snapshot['tasks'], catalog)
        write(args.out, snapshot)
        print(json.dumps({'tasks_before': before, 'tasks': len(snapshot['tasks']), 'out': args.out}))
        return
    assembler = Assembler()
    steps = plan([] if args.no_catalog else CATEGORIES, set(args.only) if args.only else None)
    for number, step in enumerate(steps, 1):
        if assembler.needs(step):
            assembler.add(step, search(args.base, step))
            time.sleep(args.pause)
        if number % 20 == 0:
            print(f'{number}/{len(steps)} catalog={len(assembler.catalog)}', file=sys.stderr, flush=True)
    snapshot = assembler.snapshot(None if args.no_catalog else status(args.base))
    write(args.out, snapshot)
    print(json.dumps({'tasks': len(snapshot['tasks']), 'catalog': len(snapshot['catalog']),
                      'captured_at': snapshot['captured_at'], 'out': args.out}))


if __name__ == '__main__':
    main()
