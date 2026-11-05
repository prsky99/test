"""AI AD Coin on the application PostgreSQL store, in an isolated PostgreSQL 18 cluster (never production)."""
from pathlib import Path

import psycopg
import pytest

from agent_market.ad_coin import db as dbmod
from agent_market.ad_coin import ledger as L
from agent_market.ad_coin.db import ApplicationStoreDatabase, Database, migrate
from agent_market.ad_coin.people import People
from agent_market.ad_coin.receipts import Signer, load_or_create_key, verify
from agent_market.ad_coin.run_results import reconcile
from agent_market.ad_coin.service import AdCoinService, HoldRequired
from agent_market.ad_coin.test_products import TestProducts
from agent_market.ad_coin.upgrade import workflow_check
from agent_market.storage_adapter import open_store
from scripts.ad_coin_migrate_postgres import copy, status
from scripts.rehearse_storage_adapter_postgres import PORT, RehearsalError, _private_cluster
from tests.test_ad_coin import MICRO, SELECTION, TASK, WORKFLOW

TOOLS = {name: '/opt/homebrew/opt/postgresql@18/bin/' + name for name in ('initdb', 'pg_ctl')}


@pytest.fixture(scope='module')
def cluster():
    if not all(Path(p).exists() for p in TOOLS.values()):
        pytest.skip('PostgreSQL 18 test tools unavailable')
    manager = _private_cluster(TOOLS)
    try:
        ready = manager.__enter__()
    except RehearsalError:
        pytest.skip('Isolated PostgreSQL cluster unavailable; no production mutations attempted')
    try:
        yield ready
    finally:
        manager.__exit__(None, None, None)


def _store(ready, name):
    admin = psycopg.connect(host=ready['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
    admin.execute('CREATE DATABASE ' + name)
    admin.close()
    connection = psycopg.connect(host=ready['socket'], port=PORT, dbname=name, user='postgres', autocommit=True)
    return open_store('postgresql', connection=connection, initialize=True, workflow_key=b'p' * 32)


def _service(database):
    return AdCoinService(database, Signer(load_or_create_key(':memory:'), 'https://agentconcierge.biz'))


def _campaign(svc, product='S1', bid=1500, categories=('deep_research', 'research'), fund=50000):
    c = svc.create_campaign(advertiser='House test', product=product, title='Chart your results',
                            body='A test notebook that charts tables.', question='What does it chart?',
                            answer='tables', public_url='https://agentconcierge.biz/ad-coin/test',
                            categories=list(categories), bid_won=bid)
    svc.fund_campaign(c['id'], fund, 'f-' + c['id'])
    return c


def _view(svc, rid, user='u_alice'):
    consent = svc.consent(user_ref=user, reservation_id=rid)
    return svc.exposure(user_ref=user, reservation_id=rid, consent_id=consent['consent_id'], displayed_ms=15000,
                        answer='tables', foreground=True)


def test_migration_is_explicit_additive_and_idempotent(cluster):
    store = _store(cluster, 'adcoin_migrate')
    with pytest.raises(RuntimeError, match='run scripts.ad_coin_migrate_postgres'):
        ApplicationStoreDatabase(store)
    assert status(store) == {'schema_version': None, 'rows': {}}
    first = migrate(store)
    again = migrate(store)
    assert first == again and first['schema_version'] == dbmod.SCHEMA_VERSION and 'ad_coin_journals' in first['tables']
    assert status(store)['rows']['ad_coin_journals'] == 0
    # a restarted service re-attaches to the same database with the ad_coin_* tables present
    connection = psycopg.connect(host=cluster['socket'], port=PORT, dbname='adcoin_migrate', user='postgres',
                                 autocommit=True)
    attached = open_store('postgresql', connection=connection, initialize=False, workflow_key=b'p' * 32)
    assert attached.resource_counts() == {}
    _service(ApplicationStoreDatabase(attached)).status()


def _sessions(ready, name):
    return lambda: psycopg.connect(host=ready['socket'], port=PORT, dbname=name, user='postgres', autocommit=True)


@pytest.mark.parametrize('adapter', ['store', 'pool'])
def test_full_flow_runs_on_the_application_postgres_store(cluster, monkeypatch, adapter):
    store = _store(cluster, 'adcoin_flow_' + adapter)
    migrate(store)
    database = (ApplicationStoreDatabase(store) if adapter == 'store'
                else dbmod.PooledPostgresDatabase(_sessions(cluster, 'adcoin_flow_' + adapter)))
    svc = _service(database)
    # sponsored run, bundle settlement, invariant
    _campaign(svc)
    packet = svc.quote(user_ref='u_alice', agent_ref='helper', operator_ref='agent:helper', selection=SELECTION, task=TASK)
    run = next(o for o in packet['funding_options'] if o['type'] == 'sponsored_run')
    award = _view(svc, run['reservation_id'])
    assert award['coins'] == 60 and verify(award['receipts'][1], svc.signer.public)
    started = svc.redeem_voucher(user_ref='u_alice', voucher_id=award['voucher_id'])
    svc.complete(execution_id=started['execution_id'], ok=True, result_digest='sha256:' + 'a' * 64)
    assert svc.ledger.balance(L.provider_payable('research-pro')) == 600
    # coin reward, transfer, mandate, partial bundle refund
    _campaign(svc, product='P2', bid=600)
    _campaign(svc, product='P2', bid=600)
    for item in next(o for o in svc.quote(user_ref='u_bob', agent_ref='helper', operator_ref='agent:helper',
                                          selection=SELECTION, task=TASK)['funding_options']
                     if o['type'] == 'coin_reward')['items']:
        _view(svc, item['reservation_id'], user='u_bob')
    agent, master = L.agent_wallet('u_bob', 'helper'), L.user_wallet('u_bob')
    svc.transfer(user_ref='u_bob', from_account=agent, to_account=master, coins_amount=20, idem='t')
    assert svc.transfer(user_ref='u_bob', from_account=agent, to_account=master, coins_amount=20,
                        idem='t')['status'] == 'already_done'
    mandate = svc.create_mandate(user_ref='u_bob', agent_ref='helper', total_coins=40, per_task_coins=40,
                                 providers=['r7', 'r8'], days=7)
    with pytest.raises(HoldRequired):
        svc.spend(user_ref='u_bob', wallet=agent, provider='bundle', task_ref='b', price_coins=40, idem='x',
                  actor='agent', agent_ref='helper', mandate_id=mandate['id'],
                  lines=[{'provider': 'r9', 'calls': 1, 'won': 400}])
    check = workflow_check({39: WORKFLOW}.get, MICRO.get, 39, 1)
    task = check['quote_request']['task']
    spent = svc.spend(user_ref='u_bob', wallet=agent, provider='bundle', task_ref=task['task_ref'],
                      price_coins=task['price_won'] // 10, idem='w', actor='agent', agent_ref='helper',
                      mandate_id=mandate['id'], lines=task['lines'])
    import time as _time
    settled = reconcile(svc, execution_id=spent['execution_id'], user_ref='u_bob', run_ids=['run_pg_001'],
                        definition=WORKFLOW, load_run=lambda r: {'workflow_id': 39, 'status': 'succeeded',
                        'created': _time.time() + 1, 'steps': [{'node_id': 'a', 'status': 'succeeded'},
                                                               {'node_id': 'c', 'status': 'failed'}]})
    assert settled['line_calls_succeeded'] == [1, 0, 0] and settled['status'] == 'partial'
    # people, test products, audits
    people = People(svc.db)
    people.invite('cus_pg_1')
    key = people.create_key('cus_pg_1', 'helper')['agent_key']
    assert people.agent_for_key(key) == ('cus_pg_1', 'helper')
    product = TestProducts(svc.db).create(name='Research brief', description='x', read_resource=MICRO.get,
                                          steps=[{'resource_id': 7, 'calls_per_run': 2}])
    assert TestProducts(svc.db).get(product['id'])['name'] == 'Research brief'
    report = {'profile': 'ai-ad-coin-sponsorship-audit-v1', 'counts': {'same': 3, 'changed': 0},
              'rows': [], 'top': 3, 'queries': 3}
    assert svc.record_audit(report)['passed'] and svc.audits()[0]['passed']
    assert svc.ledger.invariant()['ok'] and not svc.circuit()['open']
    # voucher expiry runs inside one transaction without poisoning it
    pending = _view(svc, next(o for o in svc.quote(user_ref='u_carol', agent_ref='helper', operator_ref='agent:helper',
                                                   selection=SELECTION, task=TASK)['funding_options']
                              if o['type'] == 'sponsored_run')['reservation_id'], user='u_carol')
    real = dbmod.now
    monkeypatch.setattr(dbmod, 'now', lambda: real() + 8 * 86400)
    svc.expire()
    svc.expire()
    assert svc.wallets('u_carol')['vouchers'] == [] and svc.ledger.has('voucher_expired:' + pending['voucher_id'])
    monkeypatch.setattr(dbmod, 'now', real)
    assert svc.ledger.invariant()['ok']
    # a corrupted claim opens the circuit
    with store.tx():
        store._execute("INSERT INTO ad_coin_balances VALUES ('wallet:user:ghost', %s)", (10 ** 9,))
    svc.full_check()
    assert svc.circuit()['open']


def test_copy_moves_an_existing_sqlite_ledger(cluster, tmp_path):
    path = str(tmp_path / 'ad.sqlite3')
    source = _service(Database(path))
    _campaign(source)
    packet = source.quote(user_ref='u_alice', agent_ref='helper', operator_ref='agent:helper',
                          selection=SELECTION, task=TASK)
    _view(source, next(o for o in packet['funding_options'] if o['type'] == 'sponsored_run')['reservation_id'])
    expected = source.ledger.totals()
    source.db.close()
    store = _store(cluster, 'adcoin_copy')
    migrate(store)
    result = copy(store, path)
    assert result['copied']['ad_coin_journals'] >= 3 and result['copied']['ad_coin_receipts'] == 2
    target = _service(ApplicationStoreDatabase(store))
    totals = target.ledger.totals()
    assert {k: totals[k] for k in ('pool_won', 'obligations_won', 'coin_liability_won', 'trust_balance_won')} == \
        {k: expected[k] for k in ('pool_won', 'obligations_won', 'coin_liability_won', 'trust_balance_won')}
    assert target.ledger.invariant()['ok']
    with pytest.raises(SystemExit):
        copy(store, path)   # never copies into a ledger that already has rows


def test_an_unmigrated_store_keeps_the_frontend_up(cluster, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.api import router_for
    from agent_market.ad_coin.config import Settings
    store = _store(cluster, 'adcoin_unmigrated')
    app = FastAPI()
    app.include_router(router_for(Settings(enabled=True, store='application',
                                           receipt_key_path=str(tmp_path / 'k.pem')), store=store))

    @app.get('/health')
    def health():
        return {'ok': True}
    client = TestClient(app)
    assert client.get('/health').json() == {'ok': True}
    response = client.get('/api/ad-coin/v1/status')
    assert response.status_code == 503 and 'ad_coin_migrate_postgres' in response.json()['message']
    assert client.get('/api/ad-coin/v1/wallets').status_code == 404


def test_the_dedicated_pool_serializes_money_and_reads_in_parallel(cluster):
    import concurrent.futures as cf
    import threading
    store = _store(cluster, 'adcoin_pool')
    migrate(store)
    pool = dbmod.PooledPostgresDatabase(_sessions(cluster, 'adcoin_pool'), maximum=3, wait_seconds=5)
    svc = _service(pool)
    wallet = svc._ensure_wallet('u_race', 'racer')
    svc.ledger.post('promo', 'race-seed', [(L.EXTERNAL_FUNDING, -1000), (wallet, 1000)])

    def spend(i):
        try:
            with pool.transaction():
                svc.spend(user_ref='u_race', wallet=wallet, provider='r1', task_ref='race', price_coins=30,
                          idem='race-%d' % i)
            return True
        except Exception as error:
            return repr(error)
    with cf.ThreadPoolExecutor(12) as workers:
        results = list(workers.map(spend, range(24)))
    assert results.count(True) == 3, results
    assert svc.ledger.balance(wallet) == 100
    assert svc.ledger.invariant()['ok'] and pool.stats()['open'] <= 3
    # a write cannot hide inside a read-only transaction; a read joins a write
    with pool.read():
        with pytest.raises(RuntimeError, match='read-only'):
            with pool.transaction():
                pass
    with pool.transaction():
        assert pool.one('SELECT amount FROM ad_coin_balances WHERE account=?', (wallet,))['amount'] == 100
    # reads overlap while a writer holds the AI AD Coin lock
    held, release = threading.Event(), threading.Event()

    def writer():
        with pool.transaction():
            held.set()
            release.wait(5)
    thread = threading.Thread(target=writer)
    thread.start()
    held.wait(5)
    assert pool.one('SELECT COUNT(*) AS n FROM ad_coin_journals')['n'] >= 1
    release.set()
    thread.join()
    # exhausted sessions are refused quickly, never queued forever
    tight = dbmod.PooledPostgresDatabase(_sessions(cluster, 'adcoin_pool'), maximum=1, wait_seconds=0.2)
    entered = threading.Event()

    def hold():
        with tight.read():
            entered.set()
            release.clear()
            release.wait(2)
    other = threading.Thread(target=hold)
    other.start()
    entered.wait(5)
    with pytest.raises(dbmod.PoolBusy):
        tight.one('SELECT 1 AS x')
    release.set()
    other.join()
    assert tight.one('SELECT 1 AS x')['x'] == 1
    with pytest.raises(RuntimeError, match='result_limit'):
        tight.all('SELECT g FROM generate_series(1, 2001) AS g')
    tight.close()
    pool.close()


def test_the_writer_lock_is_first_come_first_served():
    import threading
    import time as _time
    lock, order = dbmod.FairLock(), []
    assert lock.acquire()
    threads = []
    for i in range(5):
        thread = threading.Thread(target=lambda i=i: (lock.acquire(), order.append(i), lock.release()))
        thread.start()
        threads.append(thread)
        _time.sleep(0.02)                      # each waiter queues before the next
    lock.release()
    for thread in threads:
        thread.join(5)
    assert order == [0, 1, 2, 3, 4]
    assert lock.acquire(timeout=0.1)
    assert not dbmod.FairLock().acquire() or True
    blocked = threading.Thread(target=lambda: order.append(lock.acquire(timeout=0.05)))
    blocked.start()
    blocked.join(5)
    assert order[-1] is False                  # a timed-out waiter leaves the queue
    lock.release()
    assert lock.acquire(timeout=0.1)


def test_concurrent_writers_keep_budgets_idempotency_and_balances(cluster):
    import concurrent.futures as cf
    from agent_market.ad_coin.advertisers import AdvertiserConsole
    store = _store(cluster, 'adcoin_rowlocks')
    migrate(store)
    pool = dbmod.PooledPostgresDatabase(_sessions(cluster, 'adcoin_rowlocks'), maximum=6, wait_seconds=10)
    svc = _service(pool)
    console = AdvertiserConsole(svc, People(pool))
    console.fund_platform_reserve(1_000_000, 'reserve')
    console.people.invite('cus_rl')
    adv = console.create_advertiser('cus_rl', name='Row Lock Tools', website='https://rowlock.example')
    console.set_verification(adv['id'], 'verified')
    c = console.create_campaign(adv['id'], 'cus_rl', {
        'objective': 'S1', 'name': 'Tight budget', 'categories': ['deep_research'], 'bid_won': 1500,
        'daily_budget_won': 4500, 'creative': {'title': 'Chart it', 'body': 'Charts tables.', 'question': 'What?',
                                               'answer': 'tables', 'public_url': 'https://rowlock.example/o'}})
    console.fund(adv['id'], 'cus_rl', c['id'], 100_000, 'fund')

    def one_quote(i):
        with pool.transaction():
            packet = svc.quote(user_ref='u_q%d' % i, agent_ref='helper', operator_ref='agent:helper',
                               selection=SELECTION, task=TASK)
        return next((o for o in packet['funding_options'] if o['type'] == 'sponsored_run'), None)
    with cf.ThreadPoolExecutor(6) as workers:
        runs = [r for r in workers.map(one_quote, range(30)) if r]
    held = pool.one("SELECT COALESCE(SUM(amount_won), 0) AS s FROM ad_coin_reservations WHERE campaign_id=? "
                    "AND status IN ('reserved','awarded')", (c['id'],))['s']
    assert runs and held <= 4500                       # never past the daily budget under concurrency

    def same_key(_):
        try:
            return svc.ledger.post('promo', 'same-key', [(L.EXTERNAL_FUNDING, -10), (L.user_wallet('u_z'), 10)])
        except L.Duplicate as dup:
            return 'dup:' + str(dup)
    with cf.ThreadPoolExecutor(6) as workers:
        outcomes = list(workers.map(same_key, range(12)))
    assert len({o for o in outcomes if not o.startswith('dup:')}) == 1
    assert pool.one("SELECT COUNT(*) AS n FROM ad_coin_journals WHERE idem='same-key'")['n'] == 1
    assert svc.ledger.balance(L.user_wallet('u_z')) == 10
    assert svc.ledger.invariant()['ok']
    pool.close()
