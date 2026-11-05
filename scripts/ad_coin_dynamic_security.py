"""Dynamic security check of AI AD Coin over real HTTP (isolated PostgreSQL 18, never production).

Starts the real router the way production wires it (dedicated session pool, registered SQL)
on a private port with a stand-in sign-in core, seeds two advertisers and two people, then
sends attacker requests: missing or forged credentials, other people's objects (BOLA),
missing or forged CSRF proof and foreign origins, malformed and hostile input, money
tampering and replay, a concurrent double spend, method tampering, rate limits, and checks
the security headers and that no error leaks internals. Writes a JSON report.

    nice -n 10 .venv-tests/bin/python -m scripts.ad_coin_dynamic_security --out reports/<folder>
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN = 'dyn-admin-' + 'k' * 24
SESSIONS = {'cst_owner': 'cus_owner', 'cst_eve': 'cus_eve', 'cst_stranger': 'cus_stranger'}
LEAKS = re.compile(r'Traceback|File "|psycopg|sqlite|postgres|SELECT |INSERT |/Users/|\.venv|statement_failed', re.I)


class Identity:
    def actor(self, token):
        from agent_market.workspace_access import WorkspaceDenied
        if token not in SESSIONS:
            raise WorkspaceDenied()

        class Actor:
            customer_id = SESSIONS[token]
        return Actor()

    def csrf(self, token):
        return hashlib.sha256(('csrf:' + token).encode()).hexdigest()


class Report:
    def __init__(self):
        self.checks, self.lock = [], threading.Lock()

    def check(self, area, name, ok, detail=''):
        with self.lock:
            self.checks.append({'area': area, 'name': name, 'passed': bool(ok), 'detail': str(detail)[:300]})


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def serve(pg):
    import psycopg
    import uvicorn
    from fastapi import FastAPI
    from agent_market.ad_coin.api import router_for
    from agent_market.ad_coin.config import Settings
    from agent_market.ad_coin.db import PooledPostgresDatabase, migrate
    from agent_market.ad_coin.receipts import Signer, load_or_create_key
    from agent_market.ad_coin.service import AdCoinService
    from agent_market.storage_adapter import open_store
    from scripts.ad_coin_rehearsal import PORT, catalog_sample
    connection = psycopg.connect(host=pg['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=b'd' * 32)
    store._admin_read_pool = None
    migrate(store)
    sessions = lambda: psycopg.connect(host=pg['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
    service = AdCoinService(PooledPostgresDatabase(sessions), Signer(load_or_create_key(':memory:'), 'https://agentconcierge.biz'))
    catalog, paid, free = catalog_sample()

    class Catalog:
        def resource(self, rid):
            return catalog.get(rid)
    settings = Settings(enabled=True, store='application', receipt_key_path=':memory:', admin_token=ADMIN,
                        write_per_minute=40, read_per_minute=400)
    identity = Identity()
    router = router_for(settings, service=service, store=Catalog(), customer_identity=lambda: identity)
    for customer in ('cus_owner', 'cus_eve'):
        router.ad_coin_console.people.invite(customer)
    app = FastAPI()
    app.include_router(router)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, port, router, service, paid, store, connection


def run(out):
    import httpx
    from scripts.ad_coin_rehearsal import cluster
    rep = Report()
    with cluster() as pg:
        server, port, router, service, paid, store, connection = serve(pg)
        base = 'http://127.0.0.1:%d' % port
        api = base + '/api/ad-coin/v1'
        identity = Identity()

        def client(token=None):
            c = httpx.Client(base_url=api, timeout=15, headers={'Origin': base})
            if token:
                c.cookies.set('__Host-ac_customer_session', token)
            return c

        def csrf(token):
            return {'X-Customer-CSRF': identity.csrf(token)}
        owner, eve, stranger, anon = client('cst_owner'), client('cst_eve'), client('cst_stranger'), client()
        admin = httpx.Client(base_url=api, timeout=15, headers={'Authorization': 'Bearer ' + ADMIN})

        # ---- seed through the real API
        adv = owner.post('/advertisers', json={'name': 'Owner Tools', 'website': 'https://owner.example'},
                         headers=csrf('cst_owner')).json()
        eve_adv = eve.post('/advertisers', json={'name': 'Eve Tools', 'website': 'https://eve.example'},
                           headers=csrf('cst_eve')).json()
        admin.post('/admin/advertisers/verification', json={'advertiser_id': adv['id'], 'verification': 'verified'})
        camp = owner.post('/advertiser/campaigns', headers=csrf('cst_owner'), json={
            'advertiser_id': adv['id'], 'objective': 'S1', 'name': 'Owner campaign', 'categories': ['deep_research'],
            'bid_won': 3000, 'daily_budget_won': 30000, 'frequency_cap': 3, 'creative': {
                'title': 'Chart it', 'body': 'Charts tables.', 'question': 'What does it chart?', 'answer': 'tables',
                'public_url': 'https://owner.example/offer'}}).json()
        owner.post('/advertiser/campaigns/fund', headers=csrf('cst_owner'), json={
            'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'amount_won': 60000, 'idempotency_key': 'seed'})
        task = {'selection': {'items': [{'agent': 'free-agent'}, {'agent': 'paid-agent'}], 'chosen': 'paid-agent'},
                'task': {'provider': 'paid-agent', 'task_ref': 'dyn-task', 'price_won': 1200, 'category': 'deep_research'}}
        packet = owner.post('/quotes', json=task, headers=csrf('cst_owner')).json()
        run_opt = next((o for o in packet.get('funding_options', []) if o['type'] == 'sponsored_run'), None)
        rid = run_opt['reservation_id'] if run_opt else None
        rep.check('setup', 'seed through the API', bool(adv.get('id') and camp.get('id') and rid), packet.get('error'))
        wallets = owner.get('/wallets').json()
        owner_wallet = next((w['account'] for w in wallets.get('wallets', []) if w['kind'] == 'user'), 'wallet:user:x')

        # ---- A. authentication and function-level authorization
        routes = re.findall(r"@add\('(GET|POST|PUT)', '([^']+)', '(admin|advertiser|person|customer)'",
                            (ROOT / 'agent_market/ad_coin/api.py').read_text())
        for method, path, kind in routes:
            if kind == 'admin':
                for label, c in (('no token', anon), ('wrong token', httpx.Client(base_url=api, timeout=15, headers={
                        'Authorization': 'Bearer wrong-' + 'x' * 20})), ('customer session', owner)):
                    r = c.request(method, path, json={} if method != 'GET' else None,
                                  headers=csrf('cst_owner') if c is owner else None)
                    rep.check('authz', '%s %s admin route with %s' % (method, path, label), r.status_code == 403,
                              r.status_code)
            else:
                for label, c in (('anonymous', anon), ('not invited', stranger)):
                    r = c.request(method, path, json={} if method != 'GET' else None,
                                  headers=csrf('cst_stranger') if c is stranger else None)
                    ok = r.status_code in (401, 403) or (kind == 'person' and path in ('/upgrade-check',) and r.status_code in (401, 403))
                    rep.check('authz', '%s %s %s route %s' % (method, path, kind, label), ok, r.status_code)

        # ---- B. object-level authorization (BOLA): Eve against the owner's objects
        for method, path in (('GET', '/advertiser?advertiser_id=' + adv['id']),
                             ('GET', '/advertiser/campaigns?advertiser_id=' + adv['id']),
                             ('GET', '/advertiser/report?advertiser_id=' + adv['id']),
                             ('GET', '/advertiser/statement?advertiser_id=' + adv['id']),
                             ('GET', '/advertiser/history?advertiser_id=' + adv['id'])):
            r = eve.request(method, path)
            rep.check('bola', 'Eve reads ' + path.split('?')[0], r.status_code in (403, 404), r.status_code)
        for path, body in (('/advertiser/campaigns/update', {'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'status': 'paused'}),
                           ('/advertiser/campaigns/update', {'advertiser_id': eve_adv['id'], 'campaign_id': camp['id'], 'bid_won': 10}),
                           ('/advertiser/campaigns/fund', {'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'amount_won': 10, 'idempotency_key': 'e1'}),
                           ('/advertiser/members', {'advertiser_id': adv['id'], 'customer_id': 'cus_eve', 'role': 'owner'}),
                           ('/advertiser/creatives', {'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'title': 'x'})):
            r = eve.post(path, json=body, headers=csrf('cst_eve'))
            rep.check('bola', 'Eve writes %s %s' % (path, sorted(body)[:2]), r.status_code in (403, 404), r.status_code)
        for path, body in (('/consents', {'reservation_id': rid}), ('/declines', {'reservation_id': rid}),
                           ('/exposures', {'reservation_id': rid, 'consent_id': 'k_x', 'displayed_ms': 15000, 'answer': 'tables', 'foreground': True}),
                           ('/transfers', {'from': owner_wallet, 'to': 'wallet:user:u_eve', 'coins': 1, 'idempotency_key': 'x'}),
                           ('/spends', {'wallet': owner_wallet, 'provider': 'p', 'task_ref': 't', 'price_coins': 1, 'idempotency_key': 'y'})):
            r = eve.post(path, json=body, headers=csrf('cst_eve'))
            rep.check('bola', 'Eve uses the owner\'s %s' % path, r.status_code in (400, 403, 404, 409), r.status_code)
        mine = eve.get('/receipts').json()
        rep.check('bola', 'Eve sees no receipt of the owner', not any('cus_owner' in json.dumps(x) for x in mine.get('receipts', [])))

        # ---- C. CSRF and origin
        r = owner.post('/quotes', json=task)                                             # no proof
        rep.check('csrf', 'write without CSRF proof is refused', r.status_code in (401, 403), r.status_code)
        r = owner.post('/quotes', json=task, headers={'X-Customer-CSRF': '0' * 64})
        rep.check('csrf', 'write with a forged CSRF proof is refused', r.status_code in (401, 403), r.status_code)
        r = owner.post('/quotes', json=task, headers={**csrf('cst_eve')})
        rep.check('csrf', "another session's CSRF proof is refused", r.status_code in (401, 403), r.status_code)
        r = owner.post('/quotes', json=task, headers={**csrf('cst_owner'), 'Origin': 'https://evil.example'})
        rep.check('csrf', 'cross-origin write is refused', r.status_code in (401, 403), r.status_code)

        # ---- D. hostile input
        hostile = ["'; DROP TABLE ad_coin_journals; --", '<script>alert(1)</script>', '\u202eevil', 'x' * 5000,
                   '{{7*7}}', '../../etc/passwd', '\x00', '1 OR 1=1']
        for value in hostile:
            r = owner.post('/advertiser/campaigns', headers=csrf('cst_owner'), json={
                'advertiser_id': adv['id'], 'objective': 'S1', 'name': value, 'categories': [value[:40]], 'bid_won': 1500,
                'daily_budget_won': 5000, 'creative': {'title': value[:80], 'body': value[:400], 'question': 'q?',
                                                       'answer': 'a', 'public_url': 'https://owner.example/' }})
            rep.check('input', 'hostile campaign input %r is refused or stored inert' % value[:20],
                      r.status_code in (400, 422) or (r.status_code == 200 and r.headers['content-type'].startswith('application/json')),
                      r.status_code)
            rep.check('leak', 'no internals in the answer to %r' % value[:20], not LEAKS.search(r.text), r.text[:120])
        for value in ('https://192.168.0.1/x', 'https://localhost/', 'javascript:alert(1)', 'http://owner.example/'):
            r = owner.post('/advertiser/creatives', headers=csrf('cst_owner'), json={
                'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'title': 'T', 'body': 'B', 'question': 'Q?',
                'answer': 'a', 'public_url': value})
            rep.check('input', 'creative link %s is refused' % value, r.status_code in (400, 422), r.status_code)
        r = owner.post('/quotes', content=b'{"a":' + b'1' * 40000 + b'}', headers={**csrf('cst_owner'), 'Content-Type': 'application/json'})
        rep.check('input', 'oversized body is refused', r.status_code == 413, r.status_code)
        r = owner.post('/quotes', content=b'{not json', headers={**csrf('cst_owner'), 'Content-Type': 'application/json'})
        rep.check('input', 'malformed JSON is refused', r.status_code == 400, r.status_code)
        r = owner.get('/advertiser/report?advertiser_id=' + adv['id'] + '&days=-5')
        rep.check('input', 'out-of-range report period is refused', r.status_code == 400, r.status_code)
        r = owner.get('/advertiser/report.csv?advertiser_id=' + adv['id'] + '&days=abc')
        rep.check('input', 'non-numeric report period is refused', r.status_code == 400, r.status_code)

        # ---- E. money tampering and replay
        for amount in (-1000, 0, 15, 10.5, '1000', 10 ** 12, True):
            r = owner.post('/advertiser/campaigns/fund', headers=csrf('cst_owner'), json={
                'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'amount_won': amount, 'idempotency_key': 'bad-%r' % (amount,)})
            rep.check('money', 'fund amount %r is refused' % (amount,), r.status_code in (400, 422), r.status_code)
        first = owner.post('/advertiser/campaigns/fund', headers=csrf('cst_owner'), json={
            'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'amount_won': 1000, 'idempotency_key': 'replay-1'}).json()
        again = owner.post('/advertiser/campaigns/fund', headers=csrf('cst_owner'), json={
            'advertiser_id': adv['id'], 'campaign_id': camp['id'], 'amount_won': 1000, 'idempotency_key': 'replay-1'}).json()
        rep.check('money', 'a replayed funding is applied once', first.get('escrow_won') == again.get('escrow_won'), (first, again))
        if rid:
            c1 = owner.post('/consents', json={'reservation_id': rid}, headers=csrf('cst_owner')).json()
            short = owner.post('/exposures', headers=csrf('cst_owner'), json={'reservation_id': rid, 'consent_id': c1.get('consent_id'),
                                                                         'displayed_ms': 500, 'answer': 'tables', 'foreground': True})
            rep.check('money', 'a view shorter than 15 seconds earns nothing', short.status_code == 422, short.status_code)
            done = owner.post('/exposures', headers=csrf('cst_owner'), json={'reservation_id': rid, 'consent_id': c1.get('consent_id'),
                                                                        'displayed_ms': 15000, 'answer': 'tables', 'foreground': True})
            twice = owner.post('/exposures', headers=csrf('cst_owner'), json={'reservation_id': rid, 'consent_id': c1.get('consent_id'),
                                                                         'displayed_ms': 15000, 'answer': 'tables', 'foreground': True})
            rep.check('money', 'a view is rewarded once', done.status_code == 200 and twice.status_code == 409,
                      (done.status_code, twice.status_code))
        r = owner.post('/transfers', headers=csrf('cst_owner'), json={'from': owner_wallet, 'to': owner_wallet, 'coins': -5,
                                                                      'idempotency_key': 'neg'})
        rep.check('money', 'a negative transfer is refused', r.status_code in (400, 403, 422), r.status_code)

        # ---- F. concurrency: double spend against one wallet
        from agent_market.ad_coin import ledger as L
        from agent_market.ad_coin.people import user_ref_for_customer
        who = user_ref_for_customer('cus_owner')
        racer = service._ensure_wallet(who, 'racer')
        service.ledger.post('promo', 'dyn-race-seed', [(L.EXTERNAL_FUNDING, -1000), (racer, 1000)])

        def spend(i):
            return owner.post('/spends', headers={**csrf('cst_owner'), 'X-Agent-Name': 'racer'}, json={
                'wallet': racer, 'provider': 'r1', 'task_ref': 'race', 'price_coins': 30, 'idempotency_key': 'race-%d' % i}).status_code
        with cf.ThreadPoolExecutor(12) as pool:
            codes = list(pool.map(spend, range(24)))
        balance = service.ledger.balance(racer)
        rep.check('race', '24 concurrent spends of 300 won from 1,000 won: exactly 3 succeed, never negative',
                  codes.count(200) == 3 and balance == 100, (codes.count(200), balance))

        # ---- G. method tampering, rate limits, headers, leaks
        for method in ('DELETE', 'PATCH'):
            r = owner.request(method, '/quotes', headers=csrf('cst_owner'))
            rep.check('method', method + ' on a POST route is refused', r.status_code in (404, 405), r.status_code)
        codes = [stranger.get('/status').status_code for _ in range(3)]
        burst = [eve.post('/agent-keys', json={'agent': 'k%d' % i}, headers=csrf('cst_eve')).status_code for i in range(45)]
        rep.check('ratelimit', 'a burst of writes is rate limited', 429 in burst, burst[-5:])
        page = httpx.get(base + '/ad-coin/advertiser', timeout=15)
        csp = page.headers.get('content-security-policy', '')
        rep.check('headers', 'console CSP: no inline script, no framing', "script-src 'self'" in csp and 'unsafe-inline' not in csp
                  and "frame-ancestors 'none'" in csp, csp)
        r = anon.get('/status')
        rep.check('headers', 'API answers are no-store and not indexed',
                  'no-store' in r.headers.get('cache-control', '') and 'noindex' in r.headers.get('x-robots-tag', ''), dict(r.headers))
        rep.check('headers', 'no internal timing header in normal mode', 'server-timing' not in r.headers, r.headers.get('server-timing'))
        rep.check('headers', 'AI AD Coin sets no cookies', 'set-cookie' not in r.headers and 'set-cookie' not in page.headers)
        for c, path in ((anon, '/advertiser?advertiser_id=adv_x'), (owner, '/advertiser?advertiser_id=adv_missing'),
                        (admin, '/admin/campaigns/report?campaign_id=nope')):
            r = c.get(path)
            rep.check('leak', 'error for %s carries no internals' % path, not LEAKS.search(r.text), r.text[:120])

        # ---- H. integrity after all of it
        inv = service.ledger.invariant()
        rep.check('integrity', 'ledger invariant holds after the attack run', inv['ok'], inv['problems'])
        server.should_exit = True
        time.sleep(0.5)
        service.db.close()
        store.close()
        connection.close()
    failed = [c for c in rep.checks if not c['passed']]
    summary = {'checks': len(rep.checks), 'passed': len(rep.checks) - len(failed), 'failed': len(failed),
               'by_area': {}}
    for c in rep.checks:
        a = summary['by_area'].setdefault(c['area'], {'checks': 0, 'failed': 0})
        a['checks'] += 1
        a['failed'] += 0 if c['passed'] else 1
    out.mkdir(parents=True, exist_ok=True)
    (out / 'dynamic-security.json').write_text(json.dumps({'summary': summary, 'failed': failed, 'checks': rep.checks},
                                                          indent=1, ensure_ascii=False))
    return summary, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=str(ROOT / ('reports/ad-coin-security-' + time.strftime('%Y-%m-%d'))))
    args = parser.parse_args(argv)
    summary, failed = run(Path(args.out))
    print(json.dumps(summary, ensure_ascii=False))
    for c in failed:
        print('FAILED', c['area'], c['name'], c['detail'])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
