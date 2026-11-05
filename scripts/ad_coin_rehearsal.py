"""AI AD Coin operating rehearsal: the real API on the real application PostgreSQL
store, in an isolated PostgreSQL 18 cluster tuned like production, driven by an
open-loop (constant arrival rate) load of synthetic but production-shaped data.

  nice -n 10 .venv-tests/bin/python -m scripts.ad_coin_rehearsal --stage smoke
  stages: smoke, small, medium, large, extreme (or --stage all)

Never touches the production database. The catalog sample comes from the local
read-only snapshot (real prices, grades and categories). Reports go to
reports/ad-coin-rehearsal-<date>/.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PORT = 55448
APP_PORT = 55449     # the rehearsal API server, its own process like production (127.0.0.1 only)
TOOLS = {name: '/opt/homebrew/opt/postgresql@18/bin/' + name for name in ('initdb', 'pg_ctl')}
# Production postgresql.conf / auto.conf values (2026-11-05). shared_buffers is smaller here
# because production's own 2GB instance runs on the same machine; the data set fits easily.
PG_SETTINGS = {'shared_buffers': '512MB', 'work_mem': '48MB', 'maintenance_work_mem': '128MB',
               'effective_cache_size': '6GB', 'random_page_cost': '1.1', 'effective_io_concurrency': '200',
               'jit': 'off', 'max_wal_size': '1GB', 'max_connections': '48'}
STAGES = {
    'smoke':   {'users': 10,      'advertisers': 3,    'campaigns': 6,    'rate': 2,   'seconds': 15, 'workers': 4},
    'small':   {'users': 1_000,   'advertisers': 20,   'campaigns': 100,  'rate': 10,  'seconds': 45, 'workers': 8},
    'medium':  {'users': 10_000,  'advertisers': 200,  'campaigns': 1_000, 'rate': 25, 'seconds': 60, 'workers': 12},
    'large':   {'users': 100_000, 'advertisers': 1_000, 'campaigns': 5_000, 'rate': 40, 'seconds': 90, 'workers': 16},
    'extreme': {'users': 100_000, 'advertisers': 1_000, 'campaigns': 5_000, 'rate': 120, 'seconds': 45, 'workers': 32},
}
# Behaviour (docs/AD_COIN_TARGETS.md): rewarded opt-in 40-70% -> 55%, completion 85-95% -> 92%.
ACCEPT, COMPLETE, CORRECT, PROVIDER_OK, P2_SHARE, TRANSFER_SHARE, PROBE_SHARE = 0.55, 0.92, 0.8, 0.97, 0.15, 0.05, 0.03
EXPECTED_REFUSALS = {'reservation_closed', 'exposure_incomplete', 'confirmation_required', 'insufficient_coins',
                     'rate_limited'}
ADMIN_TOKEN = 'rehearsal-admin-token-' + 'x' * 16


def _run(cmd, env, timeout=60):
    import subprocess
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('command failed: ' + ' '.join(cmd[:2]) + ': ' + result.stderr[-400:])


@contextmanager
def cluster():
    import shutil
    import tempfile
    if not all(Path(p).exists() for p in TOOLS.values()):
        raise SystemExit('PostgreSQL 18 tools are missing.')
    root = Path(tempfile.mkdtemp(prefix='ad-coin-rehearsal-', dir='/private/tmp'))
    data, sock = root / 'data', root / 'socket'
    sock.mkdir(mode=0o700)
    env = {**os.environ, 'LC_ALL': 'en_US.UTF-8', 'PGHOST': str(sock)}
    try:
        _run([TOOLS['initdb'], '-D', str(data), '--username=postgres', '--auth-local=trust', '--auth-host=reject',
              '--no-locale', '--encoding=UTF8'], env, timeout=120)
        options = '-k %s -p %d -c listen_addresses= -c unix_socket_permissions=0700 ' % (sock, PORT)
        options += ' '.join('-c %s=%s' % (k, v) for k, v in PG_SETTINGS.items())
        _run([TOOLS['pg_ctl'], '-D', str(data), '-l', str(root / 'server.log'), '-o', options, '-w', 'start'], env)
        yield {'socket': str(sock), 'root': str(root)}
    finally:
        if (data / 'postmaster.pid').exists():
            for mode in ('fast', 'immediate'):
                try:
                    _run([TOOLS['pg_ctl'], '-D', str(data), '-m', mode, '-w', 'stop'], env, timeout=30)
                except Exception:
                    pass
                if not (data / 'postmaster.pid').exists():
                    break
        shutil.rmtree(root, ignore_errors=True)


def catalog_sample(limit=6000, seed=7):
    """Real catalog rows (read-only local snapshot): paid coin-eligible x402 agents and free MCP agents."""
    db = sqlite3.connect('file:' + str(ROOT / 'gateway-data/collector.sqlite3') + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    cols = 'id,name,kind,price_usdc,eval_grade,health_status,category,active'
    paid = [dict(r) for r in db.execute(
        "SELECT " + cols + " FROM resources WHERE active=1 AND kind='x402' AND price_usdc>0 AND eval_grade IN ('A','B') "
        "AND health_status IN ('healthy','reachable') ORDER BY id LIMIT ?", (limit,))]
    free = [dict(r) for r in db.execute(
        "SELECT " + cols + " FROM resources WHERE active=1 AND kind='mcp' AND (price_usdc IS NULL OR price_usdc=0) "
        "AND eval_grade='A' ORDER BY id LIMIT ?", (limit // 3,))]
    db.close()
    return {r['id']: r for r in paid + free}, paid, free


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.internal, self.client, self.status, self.codes, self.unexpected = {}, {}, {}, {}, []
        self.probes = {'attempted': 0, 'blocked': 0, 'leaked': []}
        self.missed = 0
        self.unexpected_other = 0
        self.parts = {}     # name -> {'adc-queue': [...], 'adc-work': [...], 'adc-cpu': [...]} from Server-Timing

    def add(self, name, internal_ms, client_ms, status, code, timing=''):
        with self.lock:
            for item in timing.split(','):
                key, _, dur = item.strip().partition(';dur=')
                if key.startswith('adc-') and dur:
                    self.parts.setdefault(name, {}).setdefault(key, []).append(float(dur))
            self.internal.setdefault(name, []).append(internal_ms)
            self.client.setdefault(name, []).append(client_ms)
            self.status[status] = self.status.get(status, 0) + 1
            if code:
                self.codes[code] = self.codes.get(code, 0) + 1
            # security probes are meant to be refused; Recorder.probe judges them
            if status >= 500 or (status >= 400 and code not in EXPECTED_REFUSALS and not name.startswith('probe_')):
                if not (status == 503 and code == 'busy'):
                    self.unexpected_other += 1        # every unexpected answer other than load shedding
                if len(self.unexpected) < 50:
                    self.unexpected.append({'name': name, 'status': status, 'code': code})

    def probe(self, ok, detail):
        with self.lock:
            self.probes['attempted'] += 1
            if ok:
                self.probes['blocked'] += 1
            elif len(self.probes['leaked']) < 20:
                self.probes['leaked'].append(detail)


def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(math.ceil(p / 100 * len(ordered))) - 1)], 2)


def summarize(values):
    return {'n': len(values), 'p50': pct(values, 50), 'p95': pct(values, 95), 'p99': pct(values, 99),
            'max': round(max(values), 2) if values else None,
            'mean': round(statistics.fmean(values), 2) if values else None}


def make_app(store, catalog, users, settings_overrides=None, sessions=None):
    """The real AI AD Coin router on the application PostgreSQL store, with catalog reads from the sample."""
    from fastapi import FastAPI, Request
    from agent_market.ad_coin import api as api_module
    from agent_market.ad_coin.config import Settings
    from agent_market.ad_coin.db import ApplicationStoreDatabase, PooledPostgresDatabase
    from agent_market.ad_coin.receipts import Signer, load_or_create_key
    from agent_market.ad_coin.service import AdCoinService

    class Catalog:
        def resource(self, rid):
            return catalog.get(rid)
    invited = frozenset(hashlib.sha256(token.encode()).hexdigest() for token in users)
    settings = Settings(enabled=True, store='application', receipt_key_path=':memory:', admin_token=ADMIN_TOKEN,
                        invited=invited, write_per_minute=600, read_per_minute=3000, server_timing=True,
                        **(settings_overrides or {}))
    # Production wiring (api.build_service): AI AD Coin's own session pool when a session factory exists.
    database = PooledPostgresDatabase(sessions) if sessions else ApplicationStoreDatabase(store)
    service = AdCoinService(database, Signer(load_or_create_key(':memory:'),
                                                                    'https://agentconcierge.biz'))
    router = api_module.router_for(settings, service=service, store=Catalog())
    app = FastAPI()

    @app.middleware('http')
    async def timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        response.headers['x-internal-ms'] = '%.3f' % ((time.perf_counter() - start) * 1000)
        return response
    app.include_router(router)
    return app, router


def serve_child(socket_dir, users_count):
    """Run the API in its own process with uvicorn, as production does; the load generator stays outside."""
    import psycopg
    import uvicorn
    catalog, _paid, _free = catalog_sample()
    users = ['rehearsal-user-%07d' % i for i in range(users_count)]
    sessions = lambda: psycopg.connect(host=socket_dir, port=PORT, dbname='postgres', user='postgres', autocommit=True)
    app, _router = make_app(None, catalog, users, sessions=sessions)
    interval = float(os.environ.get('AD_COIN_REHEARSAL_SWITCH_INTERVAL', '0') or 0)
    if interval:
        sys.setswitchinterval(interval)     # experiment only: GIL hand-off interval (default 0.005 s)
    uvicorn.run(app, host='127.0.0.1', port=APP_PORT, log_level='warning', access_log=False)


@contextmanager
def server_process(socket_dir, users_count):
    import subprocess
    import urllib.request
    child = subprocess.Popen([sys.executable, '-m', 'scripts.ad_coin_rehearsal', '--serve-child', socket_dir,
                              '--users', str(users_count)], cwd=str(ROOT))
    try:
        deadline = time.time() + 60
        while True:
            try:
                urllib.request.urlopen('http://127.0.0.1:%d/api/ad-coin/v1/status' % APP_PORT, timeout=1).read()
                break
            except Exception:
                if child.poll() is not None or time.time() > deadline:
                    raise SystemExit('The rehearsal API server did not start.')
                time.sleep(0.3)
        yield 'http://127.0.0.1:%d' % APP_PORT
    finally:
        child.terminate()
        try:
            child.wait(10)
        except Exception:
            child.kill()


def seed(router, stage, paid, rng):
    """Advertisers and campaigns through the real console; budgets Zipf-distributed."""
    console = router.ad_coin_console
    categories = {}
    for row in paid:
        from agent_market.ad_coin.upgrade import category_of
        cat = category_of(row['category'])
        categories[cat] = categories.get(cat, 0) + 1
    ranked = sorted(categories, key=lambda c: -categories[c])
    weights = [categories[c] for c in ranked]
    console.fund_platform_reserve(10_000_000, 'rehearsal-reserve')
    advertisers = []
    for i in range(stage['advertisers']):
        customer = 'cus_rehearsal_%05d' % i
        console.people.invite(customer)
        adv = console.create_advertiser(customer, name='Advertiser %05d' % i, website='https://adv%05d.example' % i)
        if rng.random() < 0.8:
            console.set_verification(adv['id'], 'verified')
        advertisers.append((customer, adv['id']))
    t0 = time.time()
    for j in range(stage['campaigns']):
        customer, adv = advertisers[j % len(advertisers)]
        cats = rng.choices(ranked, weights=weights, k=rng.choice((1, 1, 2)))
        rank = j + 1
        daily = max(5_000, int(2_000_000 / rank ** 0.9) // 10 * 10)          # Zipf-like budgets
        bid = rng.choice((1_200, 1_500, 2_000, 3_000, 5_000, 8_000))
        objective = 'S1' if rng.random() < 0.8 else 'P2'
        if objective == 'P2':
            bid = rng.choice((600, 800, 1_000))
        daily = max(daily, bid * 3)        # the console refuses a daily budget below one bid
        c = console.create_campaign(adv, customer, {
            'objective': objective, 'name': 'Campaign %06d' % j, 'categories': sorted(set(cats)), 'bid_won': bid,
            'daily_budget_won': daily, 'creative': {
                'title': 'Offer %06d' % j, 'body': 'A tool that helps with %s work.' % cats[0],
                'question': 'What does it help with?', 'answer': cats[0],
                'public_url': 'https://adv%05d.example/offer/%d' % (advertisers.index((customer, adv)), j)}})
        console.fund(adv, customer, c['id'], daily * 7, 'seed-%d' % j)
    return {'categories': len(ranked), 'seed_seconds': round(time.time() - t0, 1)}


def journey(client, rec, rng, token, paid, free, catalog, admin_headers):
    """One person's visit: upgrade check, quote, maybe a sponsored view, maybe a run and its settlement."""
    headers = {'X-Visitor-Token': token, 'X-Agent-Name': 'agent-%d' % (hash(token) % 50)}

    def call(name, method, path, body=None, hdr=None):
        started = time.perf_counter()
        response = client.request(method, '/api/ad-coin/v1' + path, json=body, headers=hdr or headers)
        client_ms = (time.perf_counter() - started) * 1000
        try:
            data = response.json()
        except ValueError:
            data = {}
        code = data.get('error') if isinstance(data, dict) else None
        rec.add(name, float(response.headers.get('x-internal-ms', client_ms)), client_ms, response.status_code, code,
                response.headers.get('server-timing', ''))
        return response.status_code, data
    target = rng.choice(paid)
    unit = max(1, round(target['price_usdc'] * 1380 / 1_000_000))
    calls = max(1, min(1000, math.ceil(rng.uniform(600, 3000) / unit)))
    steps = [{'resource_id': target['id'], 'calls': calls}]
    if free and rng.random() < 0.5:
        steps.append({'resource_id': rng.choice(free)['id'], 'calls': 1})
    status, check = call('upgrade_check', 'POST', '/upgrade-check', {'bundle': steps})
    if status != 200 or not check.get('quote_request'):
        return
    status, packet = call('quote', 'POST', '/quotes', check['quote_request'])
    if status != 200:
        return
    options = packet.get('funding_options', [])
    run = next((o for o in options if o['type'] == 'sponsored_run'), None)
    coins = next((o for o in options if o['type'] == 'coin_reward'), None)
    holds = ([run['reservation_id']] if run else []) + ([i['reservation_id'] for i in coins['items']] if coins else [])
    if rng.random() < PROBE_SHARE and holds:
        # security probe: someone else tries to consent to and view this person's offer
        other = {'X-Visitor-Token': 'rehearsal-user-%07d' % rng.randrange(10 ** 6, 2 * 10 ** 6)}
        s1, _ = call('probe_consent', 'POST', '/consents', {'reservation_id': holds[0]}, hdr=other)
        rec.probe(s1 in (403, 404), {'probe': 'foreign_consent', 'status': s1})
        s2, _ = call('probe_forged_key', 'GET', '/wallets', hdr={'X-Ad-Coin-Agent-Key': 'ack_' + 'f' * 43})
        rec.probe(s2 == 403, {'probe': 'forged_agent_key', 'status': s2})
        s3, _ = call('probe_negative_transfer', 'POST', '/transfers', {'from': 'wallet:user:x', 'to': 'wallet:user:y',
                                                                       'coins': -5, 'idempotency_key': 'neg'})
        rec.probe(s3 in (400, 403, 404), {'probe': 'negative_transfer', 'status': s3})
    chosen = None
    if coins and rng.random() < P2_SHARE:
        chosen = coins['items']
    elif run and rng.random() < ACCEPT:
        chosen = [run]
    for hold in holds:
        if not chosen or hold not in [c['reservation_id'] for c in chosen]:
            call('decline', 'POST', '/declines', {'reservation_id': hold})
    for option in chosen or []:
        status, consent = call('consent', 'POST', '/consents', {'reservation_id': option['reservation_id']})
        if status != 200:
            continue
        shown = 15000 if rng.random() < COMPLETE else rng.randrange(2000, 14000)
        answer = 'x' if rng.random() > CORRECT else 'tool'
        status, award = call('exposure', 'POST', '/exposures', {
            'reservation_id': option['reservation_id'], 'consent_id': consent['consent_id'], 'displayed_ms': shown,
            'answer': answer, 'foreground': True})
        if status == 200 and rng.random() < PROBE_SHARE:
            again, _ = call('probe_replay_exposure', 'POST', '/exposures', {
                'reservation_id': option['reservation_id'], 'consent_id': consent['consent_id'], 'displayed_ms': 15000,
                'answer': answer, 'foreground': True})
            rec.probe(again == 409, {'probe': 'replay_exposure', 'status': again})
        if status == 200 and award.get('voucher_id'):
            status, started = call('redeem', 'POST', '/vouchers/redeem', {'voucher_id': award['voucher_id']})
            if status == 200:
                lines = started['provider_request'].get('lines') or []
                ok = rng.random() < PROVIDER_OK
                body = {'execution_id': started['execution_id'], 'ok': ok,
                        'result_digest': 'sha256:' + hashlib.sha256(started['execution_id'].encode()).hexdigest()}
                if lines and not ok:                       # a partly failed bundle: some lines succeeded
                    body['line_results'] = [rng.random() < 0.5 for _ in lines]
                call('settle', 'POST', '/admin/executions/complete', body, hdr=admin_headers)
    if rng.random() < TRANSFER_SHARE:
        status, wallets = call('wallets', 'GET', '/wallets')
        if status == 200:
            agent = next((w for w in wallets['wallets'] if w['kind'] == 'agent' and w['available_coins'] > 0), None)
            master = next((w for w in wallets['wallets'] if w['kind'] == 'user'), None)
            if agent and master:
                call('transfer', 'POST', '/transfers', {'from': agent['account'], 'to': master['account'],
                                                        'coins': max(1, agent['available_coins'] // 2),
                                                        'idempotency_key': 'k%d' % rng.randrange(10 ** 9)})


def race_double_spend(client, rec, svc, token, threads=24):
    """Many concurrent spends against one wallet: exactly floor(balance/price) may succeed, none overdraw."""
    from agent_market.ad_coin import ledger as L
    from agent_market.ad_coin.api import user_ref_of
    who = user_ref_of(token)
    wallet = svc._ensure_wallet(who, 'racer')
    svc.ledger.post('promo', 'race-' + token, [(L.EXTERNAL_FUNDING, -1000), (wallet, 1000)])
    headers = {'X-Visitor-Token': token, 'X-Agent-Name': 'racer'}
    results = []

    def one(i):
        response = client.post('/api/ad-coin/v1/spends', headers=headers, json={
            'wallet': wallet, 'provider': 'r1', 'task_ref': 'race', 'price_coins': 30, 'idempotency_key': 'race-%d' % i})
        results.append(response.status_code)
    with cf.ThreadPoolExecutor(threads) as pool:
        list(pool.map(one, range(threads)))
    ok = results.count(200)
    balance = svc.ledger.balance(wallet)
    passed = ok == 1000 // 300 and balance == 1000 - ok * 300 and balance >= 0
    rec.probe(passed, {'probe': 'double_spend_race', 'ok': ok, 'balance': balance})
    return {'concurrent_spends': threads, 'succeeded': ok, 'final_balance_won': balance, 'passed': passed}


def prod_health_sample():
    """A light read of the public site: shows whether the rehearsal slowed production."""
    import urllib.request
    try:
        start = time.perf_counter()
        request = urllib.request.Request('https://agentconcierge.biz/status.json',
                                         headers={'User-Agent': 'agentconcierge-ad-coin-rehearsal/1'})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return round((time.perf_counter() - start) * 1000)
    except Exception:
        return None


def run_stage(name, args):
    import httpx
    import psycopg
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.db import migrate
    from agent_market.storage_adapter import open_store
    stage = dict(STAGES[name])
    if args.seconds:
        stage['seconds'] = args.seconds
    rng = random.Random(20261105)
    catalog, paid, free = catalog_sample()
    users = ['rehearsal-user-%07d' % i for i in range(stage['users'])]
    load_before = os.getloadavg()
    health_before = [prod_health_sample() for _ in range(3)]
    with cluster() as pg:
        connection = psycopg.connect(host=pg['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        store = open_store('postgresql', connection=connection, initialize=True, workflow_key=b'r' * 32)
        store._admin_read_pool = None
        migrate(store)
        sessions = lambda: psycopg.connect(host=pg['socket'], port=PORT, dbname='postgres', user='postgres',
                                           autocommit=True)
        app, router = make_app(store, catalog, users, sessions=sessions)
        svc = router.ad_coin_service
        seeded = seed(router, stage, paid, rng)
        # Production keeps planner statistics fresh (autovacuum); a freshly seeded copy has none yet.
        connection.execute('ANALYZE')
        rec = Recorder()
        local = threading.local()
        admin_headers = {'Authorization': 'Bearer ' + ADMIN_TOKEN}
        served = server_process(pg['socket'], stage['users']) if args.server == 'process' else None
        base = served.__enter__() if served else None

        def client():
            if not hasattr(local, 'client'):
                local.client = (httpx.Client(base_url=base, timeout=10) if base
                                else TestClient(app, base_url='https://rehearsal.test'))
            return local.client

        def worker(seed_value, token):
            journey(client(), rec, random.Random(seed_value), token, paid, free, catalog, admin_headers)
        interval = 1.0 / stage['rate']
        total = int(stage['rate'] * stage['seconds'])
        start = time.perf_counter()
        futures, lags = [], []
        health_during = []
        finished = threading.Event()

        def watch_production():
            # Sampled on its own thread: a slow sample must never pause the arrival schedule.
            while not finished.wait(stage['seconds'] / 4):
                health_during.append(prod_health_sample())
        watcher = threading.Thread(target=watch_production, daemon=True)
        watcher.start()
        with cf.ThreadPoolExecutor(stage['workers']) as pool:
            for i in range(total):
                due = start + i * interval
                delay = due - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                lags.append(max(0.0, (time.perf_counter() - due) * 1000))
                futures.append(pool.submit(worker, i, users[rng.randrange(len(users))]))
            done, _ = cf.wait(futures)
        finished.set()
        elapsed = time.perf_counter() - start
        failures = [f.exception() for f in done if f.exception()]
        race = race_double_spend(httpx.Client(base_url=base, timeout=10) if base
                                 else TestClient(app, base_url='https://rehearsal.test'), rec, svc, users[0])
        if served:
            served.__exit__(None, None, None)
        svc.expire()
        invariant = svc.ledger.invariant()
        counts = {}
        for table in ('ad_coin_journals', 'ad_coin_postings', 'ad_coin_reservations', 'ad_coin_exposures',
                      'ad_coin_vouchers', 'ad_coin_executions', 'ad_coin_receipts', 'ad_coin_campaigns'):
            counts[table] = svc.db.one('SELECT COUNT(*) AS n FROM ' + table)['n']
        awarded = svc.db.one("SELECT COUNT(*) AS n FROM ad_coin_reservations WHERE status='awarded'")['n']
        award_journals = svc.db.one("SELECT COUNT(*) AS n FROM ad_coin_journals WHERE kind='award'")['n']
        double_awards = svc.db.one("SELECT COUNT(*) AS n FROM (SELECT idem FROM ad_coin_journals GROUP BY idem "
                                   "HAVING COUNT(*) > 1) AS d")['n']
        over_budget = svc.db.one(
            "SELECT COUNT(*) AS n FROM (SELECT r.campaign_id, SUM(r.amount_won) AS s, m.daily_budget_won FROM "
            "ad_coin_reservations r JOIN ad_coin_campaign_meta m ON m.campaign_id=r.campaign_id WHERE "
            "r.status='awarded' GROUP BY r.campaign_id, m.daily_budget_won) AS t WHERE t.s > t.daily_budget_won")['n']
        circuit = svc.circuit()
        daily_drift = svc.daily_drift()
        deadlocks = connection.execute("SELECT deadlocks FROM pg_stat_database WHERE datname='postgres'").fetchone()[0]
        pool = svc.db.stats() if hasattr(svc.db, 'stats') else None
        svc.db.close()
        store.close()
        connection.close()
    requests_total = sum(len(v) for v in rec.internal.values())
    report = {
        'stage': name, 'config': stage, 'seeded': seeded, 'elapsed_seconds': round(elapsed, 1),
        'journeys_scheduled': total, 'journeys_failed_with_exception': len(failures),
        'exceptions': [repr(e)[:200] for e in failures[:5]],
        'requests': requests_total, 'requests_per_second': round(requests_total / elapsed, 1),
        'schedule_lag_ms': summarize(lags),
        'status_counts': rec.status, 'refusal_codes': rec.codes, 'unexpected_errors': rec.unexpected,
        'unexpected_other_than_busy': rec.unexpected_other,
        'internal_ms': {k: summarize(v) for k, v in sorted(rec.internal.items())},
        'internal_parts_ms': {k: {part: summarize(v) for part, v in sorted(parts.items())}
                              for k, parts in sorted(rec.parts.items())},
        'client_ms': {k: summarize(v) for k, v in sorted(rec.client.items())},
        'security_probes': rec.probes, 'double_spend_race': race,
        'integrity': {'invariant_ok': invariant['ok'], 'problems': invariant['problems'],
                      'unbalanced_journals': invariant['unbalanced_journals'],
                      'negative_accounts': invariant['negative_accounts'], 'circuit_open': circuit['open'],
                      'awarded_reservations': awarded, 'award_journals': award_journals,
                      'duplicate_idempotency_keys': double_awards, 'campaigns_over_daily_budget': over_budget,
                      'daily_spend_drift': daily_drift},
        'rows': counts, 'session_pool': pool, 'postgres_deadlocks': deadlocks, 'machine': {'load_before': [round(x, 2) for x in load_before],
                                    'load_after': [round(x, 2) for x in os.getloadavg()]},
        'production_status_ms': {'before': health_before, 'during': health_during},
    }
    report['gates'] = gates(report)
    return report


TARGETS = {'upgrade_check': 20, 'quote': 50, 'consent': 50, 'exposure': 50, 'redeem': 50, 'transfer': 50,
           'decline': 50, 'settle': 200, 'wallets': 200}


def gates(report):
    """docs/AD_COIN_TARGETS.md: security first, then quality, then speed."""
    sec = report['security_probes']
    integrity = report['integrity']
    security = sec['attempted'] > 0 and sec['blocked'] == sec['attempted'] and report['double_spend_race']['passed']
    quality = (integrity['invariant_ok'] and not integrity['unbalanced_journals'] and not integrity['negative_accounts']
               and not integrity['circuit_open'] and integrity['awarded_reservations'] == integrity['award_journals']
               and not integrity['duplicate_idempotency_keys'] and not report['unexpected_errors']
               and not report['journeys_failed_with_exception'] and not integrity['campaigns_over_daily_budget']
               and not integrity.get('daily_spend_drift'))
    if report['stage'] == 'extreme':
        # Past capacity the right behaviour is a fast, clean refusal (503 busy) with every balance kept;
        # quality then means intact integrity and no 5xx other than 'busy'.
        others = [e for e in report['unexpected_errors'] if not (e['status'] == 503 and e['code'] == 'busy')]
        quality = (integrity['invariant_ok'] and not integrity['unbalanced_journals']
                   and not integrity['negative_accounts'] and not integrity['circuit_open']
                   and not integrity['duplicate_idempotency_keys'] and not integrity['campaigns_over_daily_budget']
                   and not integrity.get('daily_spend_drift') and not others
                   and not report['unexpected_other_than_busy'] and not report['journeys_failed_with_exception'])
        busy = report['status_counts'].get(503, 0) + report['status_counts'].get('503', 0)
        return {'security': security, 'quality': quality, 'speed': {}, 'speed_passed': None,
                'load_shedding': {'busy_503': busy, 'requests': report['requests'],
                                  'busy_share': round(busy / max(1, report['requests']), 4)}}
    speed = {}
    for name, limit in TARGETS.items():
        stats = report['internal_ms'].get(name)
        if stats and stats['p99'] is not None:
            speed[name] = {'p99_ms': stats['p99'], 'gate_ms': limit, 'passed': stats['p99'] <= limit}
    return {'security': security, 'quality': quality, 'speed': speed,
            'speed_passed': all(v['passed'] for v in speed.values()) if speed else False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--stage', default='smoke', choices=list(STAGES) + ['all'])
    parser.add_argument('--seconds', type=int, default=0, help='override the stage duration')
    parser.add_argument('--out', default='')
    parser.add_argument('--server', default='process', choices=('process', 'inproc'),
                        help='process: the API in its own uvicorn process (production shape); inproc: TestClient')
    parser.add_argument('--serve-child', default='', help=argparse.SUPPRESS)
    parser.add_argument('--users', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve_child:
        serve_child(args.serve_child, args.users)
        return 0
    names = list(STAGES) if args.stage == 'all' else [args.stage]
    out = Path(args.out or ROOT / ('reports/ad-coin-rehearsal-' + time.strftime('%Y-%m-%d')))
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for name in names:
        report = run_stage(name, args)
        (out / (name + '.json')).write_text(json.dumps(report, indent=1, ensure_ascii=False))
        g = report['gates']
        print('%s: %d requests in %.0fs (%.1f/s) security=%s quality=%s speed=%s' % (
            name, report['requests'], report['elapsed_seconds'], report['requests_per_second'],
            g['security'], g['quality'], g['speed_passed']))
        for key, value in report['internal_ms'].items():
            parts = report['internal_parts_ms'].get(key, {})
            print('  %-16s n=%-5d p50=%-6s p99=%-6s max=%-6s | p99 work=%s cpu=%s db=%s pool=%s lock=%s hold=%s | sql=%s' % (
                key, value['n'], value['p50'], value['p99'], value['max'],
                *(parts.get(part, {}).get('p99') for part in ('adc-work', 'adc-cpu', 'adc-db', 'adc-pool', 'adc-lock', 'adc-hold')),
                parts.get('adc-sql', {}).get('p50')))
        results.append(report)
    return 0 if all(r['gates']['security'] and r['gates']['quality'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
