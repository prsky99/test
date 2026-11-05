"""HTTP routes for AI AD Coin, mounted only when AD_COIN_ENABLED is on.

Hidden by default: with the flag off the router has no routes, so every path
returns 404. With it on, people need an invited visitor token and campaign
management needs the admin token. Test mode only; payments stay closed.
"""
import hashlib
import hmac
import json
import logging
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .db import Database, PoolBusy, take_db_calls, take_db_ms, take_waits
from .sql_registry import UnregisteredSql
from .receipts import Signer, load_or_create_key, public_jwk
from .service import AdCoinError, AdCoinService

PREFIX = '/api/ad-coin/v1'
MAX_BODY = 32768
AGENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
RETRIES = 3
RETRYABLE = ('DeadlockDetected', 'LockNotAvailable', 'SerializationFailure')
NO_STORE = {'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex'}


def build_service(settings, app_store=None):
    store_kind = settings.store
    if store_kind == 'auto':
        store_kind = 'application' if getattr(app_store, 'backend', '') == 'postgresql' else 'sqlite'
    if store_kind == 'application':
        from .db import ApplicationStoreDatabase, PooledPostgresDatabase
        if app_store is None or getattr(app_store, 'backend', '') != 'postgresql':
            raise RuntimeError('AD_COIN_STORE=application needs the application PostgreSQL store.')
        factory = getattr(app_store, '_connection_factory', None)
        if factory is not None and settings.pool_maximum > 0:
            # Own small session pool: AI AD Coin never queues behind the store's single session.
            database = PooledPostgresDatabase(factory, maximum=settings.pool_maximum)
        else:
            database = ApplicationStoreDatabase(app_store)
    elif store_kind == 'sqlite':
        database = Database(settings.db_path)
    else:
        raise RuntimeError('AD_COIN_STORE must be auto, sqlite or application.')
    signer = Signer(load_or_create_key(settings.receipt_key_path), settings.issuer, test_mode=True)
    return AdCoinService(database, signer, test_mode=True)


SECURITY = logging.getLogger('agent_market.ad_coin.security')
SECURITY_CODES = {401, 403, 429, 503}


def security_event(request, kind, response):
    """Refusals and operator writes, by fixed code and path only: never tokens, keys, people or bodies."""
    status = response.status_code
    code = ''
    if status >= 400:
        try:
            code = json.loads(response.body or b'{}').get('error', '')
        except ValueError:
            code = ''
    if status in SECURITY_CODES or (status == 404 and code.startswith('unknown_')):
        SECURITY.warning('ad_coin.security event=refused status=%d code=%s method=%s path=%s access=%s',
                         status, code[:60], request.method, request.url.path, kind)
    elif kind == 'admin' and request.method in ('POST', 'PUT') and status < 400:
        SECURITY.info('ad_coin.security event=admin_change method=%s path=%s', request.method, request.url.path)


def _json(value, status=200):
    return JSONResponse(value, status_code=status, headers=NO_STORE)


def _error(exc):
    return _json({'error': exc.code, 'message': str(exc)}, exc.status)


def user_ref_of(token):
    return 'u_' + hashlib.sha256(token.encode()).hexdigest()[:24]


def router_for(settings=None, service=None, store=None, workflow_reader=None, private_flow_reader=None,
               customer_identity=None, private_run_reader=None):
    """`store` is the catalog store, read only for the upgrade check.
    `workflow_reader(template_id)` returns a published workflow definition."""
    settings = settings or Settings.from_environment()
    router = APIRouter()
    if not settings.enabled:
        return router
    if service is None:
        try:
            service = build_service(settings, store)
        except RuntimeError as exc:
            # Never take the whole frontend down for this closed test: report and stay off.
            import logging
            reason = str(exc)
            logging.getLogger('agent_market.ad_coin').error('AI AD Coin unavailable: %s', reason)

            @router.get(PREFIX + '/status', include_in_schema=False)
            def unavailable():
                return _json({'enabled': True, 'available': False, 'error': 'ad_coin_unavailable',
                              'message': reason}, 503)
            return router
    from .test_products import ProductError, TestProducts
    products = TestProducts(service.db)
    from .people import People, PeopleError, customer_session, user_ref_for_customer
    people = People(service.db)
    from .advertisers import AdvertiserConsole
    console = AdvertiserConsole(service, people)
    from ..broker.server import RateLimiter
    write_limit, read_limit = RateLimiter(settings.write_per_minute), RateLimiter(settings.read_per_minute)

    def identity():
        return customer_identity() if callable(customer_identity) else customer_identity

    def is_admin(request):
        header = request.headers.get('authorization', '')
        token = header[7:] if header.lower().startswith('bearer ') else ''
        return bool(settings.admin_token) and bool(token) and hmac.compare_digest(token, settings.admin_token)

    def person(request):
        """Who acts, in order: an agent key, the signed-in invited customer, the admin,
        then a legacy invited visitor token. Refs are hashes; tokens and keys are never stored."""
        write = request.method in ('POST', 'PUT')
        key = request.headers.get('x-ad-coin-agent-key')
        if key:
            found = people.agent_for_key(key)
            if not found:
                SECURITY.warning('ad_coin.security event=agent_key_rejected path=%s', request.url.path)
                return None
            request.state.ad_coin = {'source': 'agent_key', 'customer_id': found[0], 'agent': found[1]}
            return user_ref_for_customer(found[0])
        customer = customer_session(identity(), request, write)
        if customer:
            if not people.invited(customer):
                return None
            request.state.ad_coin = {'source': 'customer', 'customer_id': customer, 'agent': None}
            return user_ref_for_customer(customer)
        if is_admin(request):
            request.state.ad_coin = {'source': 'admin', 'customer_id': None, 'agent': None}
            return 'u_admin'
        token = request.headers.get('x-visitor-token', '')
        if 8 <= len(token) <= 200 and hashlib.sha256(token.encode()).hexdigest() in settings.invited:
            request.state.ad_coin = {'source': 'legacy_visitor', 'customer_id': None, 'agent': None}
            return user_ref_of(token)
        return None

    def acting(request):
        return getattr(request.state, 'ad_coin', None) or {}

    def agent_of(request):
        fixed = acting(request).get('agent')
        if fixed:
            return fixed  # an agent key names exactly one agent
        name = request.headers.get('x-agent-name', '')
        return name if AGENT.fullmatch(name) else 'direct'

    def operator_of(request):
        from ..concierge.web_bot_auth import VERIFIED_READER
        reader = VERIFIED_READER.get()
        if isinstance(reader, dict) and re.fullmatch(r'[0-9a-f]{32}', str(reader.get('key', ''))):
            return 'web:' + reader['key']
        return 'agent:' + agent_of(request)

    async def body(request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise AdCoinError('body_too_large', status=413)
        try:
            value = json.loads(raw or b'{}')
        except ValueError:
            raise AdCoinError('invalid_json') from None
        if not isinstance(value, dict):
            raise AdCoinError('invalid_json')
        return value

    def guarded(kind, tx=None):
        """tx: 'write' (default for POST/PUT, takes AI AD Coin's writer lock), 'read' (default for GET) or
        'none' for handlers that never touch the AI AD Coin tables (they then queue behind no writer)."""
        def wrap(handler):
            async def endpoint(request: Request):
                response = await serve(request)
                security_event(request, kind, response)
                return response

            async def serve(request):
                try:
                    if kind == 'admin' and not is_admin(request):
                        return _json({'error': 'admin_required'}, 403)
                    if kind == 'advertiser':
                        if is_admin(request):
                            who = 'admin'
                        else:
                            await run_in_threadpool(person, request)
                            state = acting(request)
                            if state.get('source') != 'customer':
                                return _json({'error': 'customer_session_required',
                                              'message': 'Sign in to your workspace to manage advertising.'}, 403)
                            who = state['customer_id']
                    else:
                        who = await run_in_threadpool(person, request) if kind in ('person', 'customer') else None
                    if who and who not in ('admin', 'u_admin'):
                        limiter = write_limit if request.method in ('POST', 'PUT') else read_limit
                        if not limiter.allow(who):
                            return JSONResponse({'error': 'rate_limited', 'message': 'Too many requests; retry soon.'},
                                                status_code=429, headers={**NO_STORE, 'Retry-After': '60'})
                    if kind in ('person', 'customer') and not who:
                        return _json({'error': 'invitation_required',
                                      'message': 'AI AD Coin is in a closed test. Sign in with an invited account.'}, 403)
                    if kind == 'customer' and acting(request).get('source') != 'customer':
                        return _json({'error': 'customer_session_required',
                                      'message': 'Manage agent keys from your own signed-in session.'}, 403)
                    data = await body(request) if request.method == 'POST' or request.method == 'PUT' else {}

                    submitted = time.perf_counter()

                    def atomic():
                        # One transaction per request: atomic on PostgreSQL and far fewer round trips.
                        started, cpu = time.perf_counter(), time.thread_time()
                        take_db_ms(), take_db_calls(), take_waits()
                        mode = tx or ('write' if request.method in ('POST', 'PUT') else 'read')
                        for attempt in range(RETRIES):
                            try:
                                if mode == 'none':
                                    value = handler(request, who, data)
                                elif mode == 'write':
                                    with service.db.transaction():
                                        if who:
                                            service.db.lock_key('who:' + who)   # one person's writes in order
                                        value = handler(request, who, data)
                                else:
                                    with service.db.read():
                                        value = handler(request, who, data)
                                break
                            except Exception as exc:
                                # Concurrent writers that deadlock or time out on a lock are rolled back
                                # whole; the request runs again from the start (nothing was kept).
                                if type(exc).__name__ not in RETRYABLE or attempt == RETRIES - 1:
                                    raise
                                time.sleep(0.005 * (attempt + 1))
                        pool_ms, lock_ms, hold_ms, ahead = take_waits()
                        timing = ('adc-queue;dur=%.2f, adc-work;dur=%.2f, adc-cpu;dur=%.2f, adc-db;dur=%.2f, '
                                  'adc-sql;dur=%d, adc-pool;dur=%.2f, adc-lock;dur=%.2f, adc-hold;dur=%.2f, adc-ahead;dur=%d') % (
                            (started - submitted) * 1000, (time.perf_counter() - started) * 1000,
                            (time.thread_time() - cpu) * 1000, take_db_ms(), take_db_calls(), pool_ms, lock_ms, hold_ms, ahead)
                        return value, timing
                    value, timing = await run_in_threadpool(atomic)
                    response = _json(value)
                    if settings.server_timing:   # internal timing stays out of production responses
                        response.headers['Server-Timing'] = timing
                    return response
                except AdCoinError as exc:
                    return _error(exc)
                except PoolBusy:
                    return _json({'error': 'busy', 'message': 'Try again shortly.'}, 503)
                except UnregisteredSql as exc:
                    SECURITY.error('ad_coin.security event=unregistered_sql path=%s detail=%s', request.url.path, exc)
                    return _json({'error': 'internal_error', 'message': 'Something went wrong; nothing was changed.'}, 500)
            endpoint.__name__ = 'ad_coin_' + handler.__name__
            return endpoint
        return wrap

    def add(method, path, kind, tx=None):
        def deco(handler):
            router.add_api_route(PREFIX + path, guarded(kind, tx)(handler), methods=[method], include_in_schema=False)
            return handler
        return deco

    # ---- public facts ----
    @add('GET', '/status', 'public')
    def status(request, who, data):
        return {**service.status(), 'enabled': True, 'access': 'invited_only'}

    @add('GET', '/receipt-key', 'public')
    def receipt_key(request, who, data):
        return {'keys': [public_jwk(service.signer.public)], 'profile': 'ai-ad-coin-receipt-v1'}

    # ---- agents: signed sponsor offer feed ----
    @add('GET', '/offer-feed', 'public')
    def offer_feed(request, who, data):
        operator = operator_of(request)
        if not operator.startswith('web:'):
            return {'profile': 'ai-ad-coin-offer-feed-v1', 'offers': [], 'reason': 'web_bot_auth_required',
                    'message': 'Sign this request with Web Bot Auth to receive sponsored offers.'}
        return service.offer_feed(operator, request.query_params.get('category'))

    @add('POST', '/offer-feed/ack', 'public')
    def offer_ack(request, who, data):
        # The token is an HMAC bound to the verified operator that fetched the feed.
        operator = data.get('operator_ref') if isinstance(data.get('operator_ref'), str) else ''
        if not operator.startswith('web:'):
            raise AdCoinError('web_bot_auth_required', status=403)
        return service.acknowledge_offer(operator, data.get('offer_id', ''), data.get('offer_token'))

    # ---- invited people (through their agent) ----
    @add('POST', '/quotes', 'person', tx='none')     # reads outside the writer lock, reserves inside it
    def quote(request, who, data):
        return service.quote(user_ref=who, agent_ref=agent_of(request), operator_ref=operator_of(request),
                             selection=data.get('selection'), task=data.get('task'))

    @add('POST', '/upgrade-check', 'person', tx='none')     # catalog reads only
    def upgrade(request, who, data):
        from .upgrade import bundle_check, check_definition, upgrade_check, workflow_check
        if store is None:
            raise AdCoinError('catalog_unavailable', status=503)
        try:
            if 'private_workflow' in data:
                from .private_workflows import PrivateWorkflowDenied
                if private_flow_reader is None:
                    raise AdCoinError('private_workflows_closed', 'Customer workspaces are not open here.', 503)
                spec = data.get('private_workflow') if isinstance(data.get('private_workflow'), dict) else {}
                try:
                    flow = private_flow_reader(request, spec.get('workspace_id'), spec.get('flow_id'))
                except PrivateWorkflowDenied as exc:
                    status = 401 if str(exc) == 'sign_in_required' else 403
                    raise AdCoinError('private_workflow_' + str(exc),
                                      'Sign in to your workspace and choose one of your own workflows.', status) from None
                return check_definition(flow, store.resource, spec.get('runs', 1), 'private_workflow',
                                        spec.get('flow_id'))
            if 'test_product' in data:
                spec = data.get('test_product') if isinstance(data.get('test_product'), dict) else {}
                return check_definition(products.get(spec.get('id')), store.resource, spec.get('runs', 1),
                                        'test_product', spec.get('id'))
            if 'workflow' in data:
                if workflow_reader is None:
                    raise AdCoinError('workflows_unavailable', status=503)
                spec = data.get('workflow') if isinstance(data.get('workflow'), dict) else {}
                return workflow_check(workflow_reader, store.resource, spec.get('template_id'), spec.get('runs', 1))
            if 'bundle' in data:
                return bundle_check(store.resource, data.get('bundle'))
            return upgrade_check(store.resource, data.get('recommendation_ids'))
        except AdCoinError:
            raise
        except ValueError as exc:
            raise AdCoinError('invalid_recommendation_ids', str(exc)) from None

    @add('GET', '/test-products', 'person')
    def test_products(request, who, data):
        return {'test_products': [p for p in products.list() if p['status'] == 'active'],
                'note': 'Closed-test products built from real catalog agents. Runs are simulated.'}

    @add('POST', '/consents', 'person')
    def consent(request, who, data):
        return service.consent(user_ref=who, reservation_id=str(data.get('reservation_id', '')))

    @add('POST', '/declines', 'person')
    def decline(request, who, data):
        return service.decline(user_ref=who, reservation_id=str(data.get('reservation_id', '')))

    @add('POST', '/exposures', 'person')
    def exposure(request, who, data):
        return service.exposure(user_ref=who, reservation_id=str(data.get('reservation_id', '')),
                                consent_id=str(data.get('consent_id', '')), displayed_ms=data.get('displayed_ms'),
                                answer=data.get('answer'), foreground=data.get('foreground') is True)

    @add('GET', '/wallets', 'person')
    def wallets(request, who, data):
        return service.wallets(who)

    @add('POST', '/transfers', 'person')
    def transfer(request, who, data):
        return service.transfer(user_ref=who, from_account=str(data.get('from', '')), to_account=str(data.get('to', '')),
                                coins_amount=data.get('coins'), idem=str(data.get('idempotency_key', ''))[:64] or 'none',
                                step_up=False, memo=str(data.get('memo', ''))[:200])

    @add('POST', '/agents/revoke', 'person')
    def revoke_agent(request, who, data):
        agent = str(data.get('agent', ''))
        customer = acting(request).get('customer_id')
        revoked = people.revoke_keys(customer, agent) if customer else 0
        try:
            swept = service.sweep_agent(user_ref=who, agent_ref=agent, reason='revoked')
        except AdCoinError as exc:
            if exc.code != 'unknown_wallet':
                raise
            swept = {'status': 'no_wallet', 'coins': 0, 'receipt': None}
        return {**swept, 'agent_keys_revoked': revoked}

    @add('GET', '/account', 'public')
    def account(request, who, data):
        customer = customer_session(identity(), request, False)
        if not customer:
            return {'signed_in': False, 'invited': False,
                    'message': 'Sign in to your workspace account to use AI AD Coin.'}
        invited = people.invited(customer)
        return {'signed_in': True, 'invited': invited, 'account_id': customer,
                'message': None if invited else 'Ask the operator to invite this account id.'}

    @add('GET', '/agent-keys', 'customer')
    def agent_keys(request, who, data):
        return {'agent_keys': people.keys(acting(request)['customer_id'])}

    @add('POST', '/agent-keys', 'customer')
    def create_agent_key(request, who, data):
        try:
            created = people.create_key(acting(request)['customer_id'], data.get('agent'))
        except PeopleError as exc:
            raise AdCoinError('invalid_agent_key', str(exc)) from None
        service._ensure_wallet(who, created['agent'])
        return created

    @add('GET', '/mandates', 'person')
    def mandates(request, who, data):
        return {'mandates': service.mandates(who)}

    @add('POST', '/mandates', 'person')
    def create_mandate(request, who, data):
        return service.create_mandate(user_ref=who, agent_ref=str(data.get('agent', '')),
                                      total_coins=data.get('total_coins'), per_task_coins=data.get('per_task_coins'),
                                      providers=data.get('providers'), days=data.get('days'))

    @add('POST', '/mandates/revoke', 'person')
    def revoke_mandate(request, who, data):
        return service.revoke_mandate(str(data.get('id', '')), who)

    @add('POST', '/spends', 'person')
    def spend(request, who, data):
        actor = 'agent' if data.get('mandate_id') else 'user'
        return service.spend(user_ref=who, wallet=str(data.get('wallet', '')), provider=data.get('provider'),
                             task_ref=data.get('task_ref'), price_coins=data.get('price_coins'),
                             idem=str(data.get('idempotency_key', ''))[:64] or 'none', actor=actor,
                             agent_ref=agent_of(request), mandate_id=data.get('mandate_id'),
                             memo=str(data.get('memo', ''))[:200], lines=data.get('lines'))

    def settle_from_runs(request, who, data, admin):
        from .run_results import RunMismatch, parse_task_ref, public_run, reconcile
        from .private_workflows import PrivateWorkflowDenied
        execution_id = str(data.get('execution_id', ''))
        row = service.db.one('SELECT task_ref FROM ad_coin_executions WHERE id=?', (execution_id,))
        target = parse_task_ref(row['task_ref']) if row else None
        try:
            if target and target['kind'] == 'workflow':
                if store is None or workflow_reader is None:
                    raise AdCoinError('workflows_unavailable', status=503)
                definition = workflow_reader(target['id'])
                if not definition:
                    raise AdCoinError('workflow_not_published', status=409)
                load = lambda run_id: public_run(store, run_id)  # noqa: E731
            elif target and target['kind'] == 'private_workflow':
                if admin or private_flow_reader is None or private_run_reader is None:
                    raise AdCoinError('private_workflows_closed',
                                      'Settle your own workflow runs from your signed-in session.', 403)
                ws = data.get('workspace_id')
                definition = private_flow_reader(request, ws, target['id'])
                load = lambda run_id: private_run_reader(request, ws, target['id'], run_id)  # noqa: E731
            else:
                definition, load = None, None
            return reconcile(service, execution_id=execution_id, user_ref=who, run_ids=data.get('run_ids'),
                             load_run=load or (lambda run_id: None), definition=definition, admin=admin)
        except PrivateWorkflowDenied as exc:
            raise AdCoinError('private_workflow_' + str(exc), 'Sign in to your workspace to read its runs.',
                              401 if str(exc) == 'sign_in_required' else 403) from None
        except RunMismatch as exc:
            raise AdCoinError(exc.code, str(exc), 409) from None

    @add('POST', '/executions/settle-from-runs', 'person')
    def settle_runs(request, who, data):
        return settle_from_runs(request, who, data, admin=False)

    @add('POST', '/vouchers/redeem', 'person')
    def redeem(request, who, data):
        return service.redeem_voucher(user_ref=who, voucher_id=str(data.get('voucher_id', '')))

    @add('GET', '/receipts', 'person')
    def receipts(request, who, data):
        return {'receipts': service.receipts(who)}

    # ---- admin (test campaigns, settings, settlement) ----
    @add('GET', '/admin/campaigns', 'admin')
    def campaigns(request, who, data):
        return {'campaigns': service.campaigns()}

    @add('POST', '/admin/campaigns', 'admin')
    def create_campaign(request, who, data):
        return service.create_campaign(advertiser=data.get('advertiser'), product=data.get('product'),
                                       title=data.get('title'), body=data.get('body'), question=data.get('question'),
                                       answer=data.get('answer'), public_url=data.get('public_url'),
                                       categories=data.get('categories'), bid_won=data.get('bid_won'))

    @add('POST', '/admin/campaigns/fund', 'admin')
    def fund(request, who, data):
        return service.fund_campaign(str(data.get('campaign_id', '')), data.get('amount_won'),
                                     str(data.get('idempotency_key', ''))[:64] or 'none')

    @add('POST', '/admin/campaigns/status', 'admin')
    def campaign_status(request, who, data):
        return service.set_campaign_status(str(data.get('campaign_id', '')), data.get('status'))

    @add('POST', '/admin/campaigns/refund', 'admin')
    def refund(request, who, data):
        return service.refund_campaign(str(data.get('campaign_id', '')), str(data.get('idempotency_key', ''))[:64] or 'none')

    @add('GET', '/admin/campaigns/report', 'admin')
    def report(request, who, data):
        return service.campaign_report(request.query_params.get('campaign_id', ''))

    @add('POST', '/admin/test-products', 'admin')
    def create_test_product(request, who, data):
        if store is None:
            raise AdCoinError('catalog_unavailable', status=503)
        try:
            return products.create(name=data.get('name'), description=data.get('description'),
                                   steps=data.get('steps'), read_resource=store.resource)
        except ProductError as exc:
            raise AdCoinError('invalid_test_product', str(exc)) from None

    @add('POST', '/admin/test-products/archive', 'admin')
    def archive_test_product(request, who, data):
        try:
            return products.archive(str(data.get('id', '')))
        except ProductError as exc:
            raise AdCoinError('unknown_test_product', str(exc), 404) from None

    @add('GET', '/admin/test-products', 'admin')
    def list_test_products(request, who, data):
        return {'test_products': products.list()}

    # ---- advertiser console (signed-in customers who belong to an advertiser) ----
    def adv_id(request, data):
        return str(data.get('advertiser_id') or request.query_params.get('advertiser_id') or '')

    @add('GET', '/advertisers', 'advertiser')
    def list_advertisers(request, who, data):
        return {'advertisers': console.advertisers(who)}

    @add('POST', '/advertisers', 'advertiser')
    def create_advertiser(request, who, data):
        return console.create_advertiser(who, name=data.get('name'), website=data.get('website'))

    @add('GET', '/advertiser', 'advertiser')
    def get_advertiser(request, who, data):
        aid = adv_id(request, data)
        return {'advertiser': console.advertiser(aid, who), 'members': console.members(aid, who),
                'notifications': console.notifications(aid, who)}

    @add('POST', '/advertiser/members', 'advertiser')
    def set_member(request, who, data):
        return {'members': console.set_member(adv_id(request, data), who, data.get('customer_id'), data.get('role'))}

    @add('GET', '/advertiser/campaigns', 'advertiser')
    def adv_campaigns(request, who, data):
        return {'campaigns': console.campaigns(adv_id(request, data), who)}

    @add('POST', '/advertiser/campaigns', 'advertiser')
    def adv_create_campaign(request, who, data):
        return console.create_campaign(adv_id(request, data), who, data)

    @add('POST', '/advertiser/campaigns/update', 'advertiser')
    def adv_update_campaign(request, who, data):
        return console.update_campaign(adv_id(request, data), who, str(data.get('campaign_id', '')),
                                       {k: v for k, v in data.items() if k not in ('advertiser_id', 'campaign_id')})

    @add('POST', '/advertiser/campaigns/fund', 'advertiser')
    def adv_fund(request, who, data):
        return console.fund(adv_id(request, data), who, str(data.get('campaign_id', '')), data.get('amount_won'),
                            str(data.get('idempotency_key', '')) or 'none')

    @add('POST', '/advertiser/creatives', 'advertiser')
    def adv_add_creative(request, who, data):
        return console.add_creative(adv_id(request, data), who, str(data.get('campaign_id', '')), data)

    @add('POST', '/advertiser/creatives/edit', 'advertiser')
    def adv_edit_creative(request, who, data):
        return console.edit_creative(adv_id(request, data), who, str(data.get('creative_id', '')), data)

    @add('POST', '/advertiser/appeals', 'advertiser')
    def adv_appeal(request, who, data):
        return console.appeal(adv_id(request, data), who, str(data.get('creative_id', '')), data.get('reason'))

    @add('GET', '/advertiser/report', 'advertiser')
    def adv_report(request, who, data):
        try:
            days = int(request.query_params.get('days', '30'))
        except ValueError:
            raise AdCoinError('invalid_days') from None
        return console.report(adv_id(request, data), who, campaign_id=request.query_params.get('campaign_id') or None,
                              days=days)

    @router.get(PREFIX + '/advertiser/report.csv', include_in_schema=False)
    async def adv_report_csv(request: Request):
        try:
            if is_admin(request):
                who = 'admin'
            else:
                await run_in_threadpool(person, request)
                state = acting(request)
                if state.get('source') != 'customer':
                    return _json({'error': 'customer_session_required'}, 403)
                who = state['customer_id']
            days = int(request.query_params.get('days', '30'))
            text = await run_in_threadpool(console.report_csv, adv_id(request, {}), who,
                                           campaign_id=request.query_params.get('campaign_id') or None, days=days)
        except AdCoinError as exc:
            return _error(exc)
        except ValueError:
            return _json({'error': 'invalid_days'}, 400)
        return Response(text, media_type='text/csv', headers={**NO_STORE,
                        'Content-Disposition': 'attachment; filename="ai-ad-coin-report.csv"'})

    @add('GET', '/advertiser/statement', 'advertiser')
    def adv_statement(request, who, data):
        return console.statement(adv_id(request, data), who)

    @add('GET', '/advertiser/history', 'advertiser')
    def adv_history(request, who, data):
        return {'history': console.history(adv_id(request, data), who)}

    # ---- operator review of advertisers ----
    @add('GET', '/admin/reviews', 'admin')
    def reviews(request, who, data):
        return {'queue': console.review_queue()}

    @add('POST', '/admin/reviews/decide', 'admin')
    def decide(request, who, data):
        return console.decide(str(data.get('creative_id', '')), data.get('decision'), data.get('note', ''))

    @add('POST', '/admin/advertisers/verification', 'admin')
    def verification(request, who, data):
        return console.set_verification(str(data.get('advertiser_id', '')), data.get('verification'))

    @add('POST', '/admin/advertisers/status', 'admin')
    def account_status(request, who, data):
        return console.set_account_status(str(data.get('advertiser_id', '')), data.get('status'))

    @add('POST', '/admin/platform-reserve', 'admin')
    def platform_reserve(request, who, data):
        return console.fund_platform_reserve(data.get('amount_won'), str(data.get('idempotency_key', '')) or 'none')

    @add('POST', '/admin/invalid-activity', 'admin')
    def invalid_activity(request, who, data):
        return console.mark_invalid(str(data.get('reservation_id', '')), data.get('reason', 'invalid'))

    @add('GET', '/admin/invites', 'admin')
    def invites(request, who, data):
        return {'invites': people.invites()}

    @add('POST', '/admin/invites', 'admin')
    def invite(request, who, data):
        try:
            return people.invite(data.get('customer_id'), data.get('note', ''))
        except PeopleError as exc:
            raise AdCoinError('invalid_invite', str(exc)) from None

    @add('POST', '/admin/invites/revoke', 'admin')
    def revoke_invite(request, who, data):
        try:
            return people.revoke_invite(str(data.get('customer_id', '')))
        except PeopleError as exc:
            raise AdCoinError('unknown_invite', str(exc), 404) from None

    @add('POST', '/admin/audits', 'admin')
    def record_audit(request, who, data):
        return service.record_audit(data.get('report'))

    @add('GET', '/admin/audits', 'admin')
    def audits(request, who, data):
        return {'audits': service.audits()}

    @add('GET', '/admin/settings', 'admin')
    def get_settings(request, who, data):
        return {'split_bps': service.split()}

    @add('PUT', '/admin/settings', 'admin')
    def put_settings(request, who, data):
        return {'split_bps': service.set_split(data.get('split_bps'))}

    @add('GET', '/admin/invariant', 'admin')
    def invariant(request, who, data):
        return service.ledger.invariant()

    @add('POST', '/admin/full-check', 'admin')
    def full_check(request, who, data):
        return service.full_check()

    @add('POST', '/admin/circuit', 'admin')
    def circuit(request, who, data):
        if data.get('open') is True:
            return service.open_circuit(str(data.get('reason', 'manual'))[:200])
        return service.close_circuit()

    @add('POST', '/admin/executions/complete', 'admin')
    def complete(request, who, data):
        return service.complete(execution_id=str(data.get('execution_id', '')), ok=data.get('ok') is True,
                                result_digest=data.get('result_digest'), line_results=data.get('line_results'))

    @add('POST', '/admin/executions/settle-from-runs', 'admin')
    def admin_settle_runs(request, who, data):
        return settle_from_runs(request, who, data, admin=True)

    @add('POST', '/admin/settle', 'admin')
    def settle(request, who, data):
        return service.settle_provider(data.get('provider'), str(data.get('idempotency_key', ''))[:64] or 'none')

    @add('POST', '/admin/sweep-dormant', 'admin')
    def sweep(request, who, data):
        return service.sweep_dormant()

    csp = ("default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; "
           "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    site_csp = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    @router.get('/ad-coin', include_in_schema=False)
    async def page():
        from .page import PAGE
        return HTMLResponse(PAGE, headers={**NO_STORE, 'Content-Security-Policy': site_csp})

    @router.get('/ad-coin/admin', include_in_schema=False)
    async def admin_page():
        from .admin_page import PAGE as ADMIN_PAGE
        return HTMLResponse(ADMIN_PAGE, headers={**NO_STORE, 'Content-Security-Policy': site_csp})

    @router.get('/ad-coin/admin.js', include_in_schema=False)
    async def admin_script():
        from .admin_page import SCRIPT as ADMIN_SCRIPT
        return Response(ADMIN_SCRIPT, media_type='text/javascript', headers={**NO_STORE, 'Content-Security-Policy': csp})

    @router.get('/ad-coin/advertiser', include_in_schema=False)
    async def advertiser_page():
        from .advertiser_page import PAGE as ADV_PAGE
        # The console uses the site's shared design system files (same origin), not page-local styles.
        return HTMLResponse(ADV_PAGE, headers={**NO_STORE, 'Content-Security-Policy': site_csp})

    @router.get('/ad-coin/advertiser.js', include_in_schema=False)
    async def advertiser_script():
        from .advertiser_page import SCRIPT as ADV_SCRIPT
        return Response(ADV_SCRIPT, media_type='text/javascript', headers={**NO_STORE, 'Content-Security-Policy': csp})

    @router.get('/ad-coin/app.js', include_in_schema=False)
    async def script():
        from .page import SCRIPT
        return Response(SCRIPT, media_type='text/javascript',
                        headers={**NO_STORE, 'Content-Security-Policy': csp})

    router.ad_coin_service = service
    router.ad_coin_console = console
    return router
