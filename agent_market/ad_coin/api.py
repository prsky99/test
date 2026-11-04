"""HTTP routes for AI AD Coin, mounted only when AD_COIN_ENABLED is on.

Hidden by default: with the flag off the router has no routes, so every path
returns 404. With it on, people need an invited visitor token and campaign
management needs the admin token. Test mode only; payments stay closed.
"""
import hashlib
import hmac
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .db import Database
from .receipts import Signer, load_or_create_key, public_jwk
from .service import AdCoinError, AdCoinService

PREFIX = '/api/ad-coin/v1'
MAX_BODY = 32768
AGENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
NO_STORE = {'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex'}


def build_service(settings):
    database = Database(settings.db_path)
    signer = Signer(load_or_create_key(settings.receipt_key_path), settings.issuer, test_mode=True)
    return AdCoinService(database, signer, test_mode=True)


def _json(value, status=200):
    return JSONResponse(value, status_code=status, headers=NO_STORE)


def _error(exc):
    return _json({'error': exc.code, 'message': str(exc)}, exc.status)


def user_ref_of(token):
    return 'u_' + hashlib.sha256(token.encode()).hexdigest()[:24]


def router_for(settings=None, service=None, store=None, workflow_reader=None, private_flow_reader=None):
    """`store` is the catalog store, read only for the upgrade check.
    `workflow_reader(template_id)` returns a published workflow definition."""
    settings = settings or Settings.from_environment()
    router = APIRouter()
    if not settings.enabled:
        return router
    service = service or build_service(settings)
    from .test_products import ProductError, TestProducts
    products = TestProducts(service.db)

    def is_admin(request):
        header = request.headers.get('authorization', '')
        token = header[7:] if header.lower().startswith('bearer ') else ''
        return bool(settings.admin_token) and bool(token) and hmac.compare_digest(token, settings.admin_token)

    def person(request):
        """Invited people only. The ref is a hash; the token itself is never stored."""
        token = request.headers.get('x-visitor-token', '')
        if is_admin(request):
            return 'u_admin'
        if 8 <= len(token) <= 200 and hashlib.sha256(token.encode()).hexdigest() in settings.invited:
            return user_ref_of(token)
        return None

    def agent_of(request):
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

    def guarded(kind):
        def wrap(handler):
            async def endpoint(request: Request):
                try:
                    if kind == 'admin' and not is_admin(request):
                        return _json({'error': 'admin_required'}, 403)
                    who = person(request) if kind == 'person' else None
                    if kind == 'person' and not who:
                        return _json({'error': 'invitation_required',
                                      'message': 'AI AD Coin is in a closed test. An invitation is required.'}, 403)
                    data = await body(request) if request.method == 'POST' or request.method == 'PUT' else {}
                    return _json(await run_in_threadpool(handler, request, who, data))
                except AdCoinError as exc:
                    return _error(exc)
            endpoint.__name__ = 'ad_coin_' + handler.__name__
            return endpoint
        return wrap

    def add(method, path, kind):
        def deco(handler):
            router.add_api_route(PREFIX + path, guarded(kind)(handler), methods=[method], include_in_schema=False)
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
    @add('POST', '/quotes', 'person')
    def quote(request, who, data):
        return service.quote(user_ref=who, agent_ref=agent_of(request), operator_ref=operator_of(request),
                             selection=data.get('selection'), task=data.get('task'))

    @add('POST', '/upgrade-check', 'person')
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
        return service.sweep_agent(user_ref=who, agent_ref=str(data.get('agent', '')), reason='revoked')

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

    @add('GET', '/admin/settings', 'admin')
    def get_settings(request, who, data):
        return {'split_bps': service.split()}

    @add('PUT', '/admin/settings', 'admin')
    def put_settings(request, who, data):
        return {'split_bps': service.set_split(data.get('split_bps'))}

    @add('GET', '/admin/invariant', 'admin')
    def invariant(request, who, data):
        return service.ledger.invariant()

    @add('POST', '/admin/circuit', 'admin')
    def circuit(request, who, data):
        if data.get('open') is True:
            return service.open_circuit(str(data.get('reason', 'manual'))[:200])
        return service.close_circuit()

    @add('POST', '/admin/executions/complete', 'admin')
    def complete(request, who, data):
        return service.complete(execution_id=str(data.get('execution_id', '')), ok=data.get('ok') is True,
                                result_digest=data.get('result_digest'), line_results=data.get('line_results'))

    @add('POST', '/admin/settle', 'admin')
    def settle(request, who, data):
        return service.settle_provider(data.get('provider'), str(data.get('idempotency_key', ''))[:64] or 'none')

    @add('POST', '/admin/sweep-dormant', 'admin')
    def sweep(request, who, data):
        return service.sweep_dormant()

    csp = ("default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; "
           "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    @router.get('/ad-coin', include_in_schema=False)
    async def page():
        from .page import PAGE
        return HTMLResponse(PAGE, headers={**NO_STORE, 'Content-Security-Policy': csp})

    @router.get('/ad-coin/admin', include_in_schema=False)
    async def admin_page():
        from .admin_page import PAGE as ADMIN_PAGE
        return HTMLResponse(ADMIN_PAGE, headers={**NO_STORE, 'Content-Security-Policy': csp})

    @router.get('/ad-coin/admin.js', include_in_schema=False)
    async def admin_script():
        from .admin_page import SCRIPT as ADMIN_SCRIPT
        return Response(ADMIN_SCRIPT, media_type='text/javascript', headers={**NO_STORE, 'Content-Security-Policy': csp})

    @router.get('/ad-coin/app.js', include_in_schema=False)
    async def script():
        from .page import SCRIPT
        return Response(SCRIPT, media_type='text/javascript',
                        headers={**NO_STORE, 'Content-Security-Policy': csp})

    router.ad_coin_service = service
    return router
