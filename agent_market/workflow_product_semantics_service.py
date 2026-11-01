"""Private bounded offline product-semantic inspection, without live effects."""
import math
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .gateway.admin_security import AdminRoute
from .workflow_product_semantics import ProductSemantics, PROFILE
from .workflow_publication_service import read_object, same_origin, no_store

MAX_BYTES = 131072
MAX_DEPTH = 12
MAX_NODES = 3000


def bounded_tree(body):
    pending = [(body, 0)]
    count = 0
    while pending:
        value, depth = pending.pop(); count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ValueError('Use a bounded JSON sample.')
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value): raise ValueError('Use JSON field names.')
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif type(value) is float:
            if not math.isfinite(value): raise ValueError('Use finite JSON numbers.')
        elif value is not None and type(value) not in (str, int, bool):
            raise ValueError('Use JSON sample values.')
    return body


async def read_request(request):
    return bounded_tree(await read_object(request, MAX_BYTES))


class ProductSemanticsService:
    def __init__(self, store):
        self.store = store
        self.core = ProductSemantics()

    def current_actor(self, actor):
        # The legacy dashboard token's role label is not a current database role.
        if type(actor) is not int or not 1 <= actor <= 9999999999:
            raise PermissionError('Current highest-administrator access is required.')
        rows = self.store.query('SELECT role,active FROM admin_users WHERE id=?', (actor,))
        if len(rows) != 1 or rows[0]['role'] != 'superadmin' or not rows[0]['active']:
            raise PermissionError('Current highest-administrator access changed.')
        return True

    def catalog(self):
        # Stored approval rows are diagnostic metadata, not fresh eligibility or
        # permission to use this offline sample as callable/quality evidence.
        counts = {'products.compare.v1': None, 'products.compare.v2': None}
        available = False
        try:
            rows = self.store.query('''SELECT contract_id,COUNT(*) AS n FROM capability_approvals
                WHERE contract_id IN (?,?) GROUP BY contract_id''', tuple(counts))
            counts = dict.fromkeys(counts, 0)
            for row in rows: counts[row['contract_id']] = row['n']
            available = True
        except sqlite3.DatabaseError:
            available = False
        return {'available': available, 'recorded_approval_rows': counts,
                'eligible_provider_count': None, 'readiness': 'not-evaluated',
                'live_execution_integration_enabled': False}

    def admin(self, method, actor, body=None):
        self.current_actor(actor)
        if method == 'schema': value = self.core.schema()
        elif method == 'options': value = {**self.core.options(), 'catalog': self.catalog()}
        elif method == 'validate': value = self.core.validate(bounded_tree(body))
        else: raise ValueError('Choose an offline product-semantic action.')
        self.current_actor(actor)
        return value


class ProductSemanticsRoute(AdminRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def secured(request):
            try: return await handler(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **no_store()}
                raise
        return secured


class ProductV2AdminRoute(AdminRoute):
    """Apply cache/error boundaries only to existing version-two live routes."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def secured(request):
            path = request.url.path
            scoped = (path.startswith('/admin/api/connections/') and
                      (path.endswith('/contracts/products.compare.v2') or path.endswith('/contracts/products.compare.v2/test')))
            try: return await handler(request)
            except HTTPException as exc:
                if scoped: exc.headers = {**(exc.headers or {}), **no_store()}
                raise
            except RequestValidationError:
                if not scoped: raise
                return JSONResponse({'detail': 'Provide a valid private product-contract request.'}, status_code=422, headers=no_store())
            except Exception:
                if not scoped: raise
                return JSONResponse({'detail': 'The private product-contract request is temporarily unavailable.'}, status_code=500, headers=no_store())
        return secured


def router_for(store, require_sadmin):
    service = ProductSemanticsService(store)
    router = APIRouter(prefix='/admin/api/workflow-product-semantics', route_class=ProductSemanticsRoute,
                       dependencies=[Depends(require_sadmin)])

    def result(method, actor, body=None):
        try: return service.admin(method, actor, body)
        except PermissionError:
            raise HTTPException(403, 'Current highest-administrator access is required.', headers=no_store()) from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, sqlite3.DatabaseError):
            raise HTTPException(409, 'The offline product sample could not be validated. Review its exact typed fields.', headers=no_store()) from None
        except Exception:
            raise HTTPException(500, 'Offline product inspection is temporarily unavailable.', headers=no_store()) from None

    @router.get('/schema')
    def schema(request: Request):
        return JSONResponse(result('schema', request.state.admin_user['user_id']), headers=no_store())

    @router.get('/options')
    def options(request: Request):
        return JSONResponse(result('options', request.state.admin_user['user_id']), headers=no_store())

    @router.post('/validate')
    async def validate(request: Request):
        if not same_origin(request):
            raise HTTPException(403, 'Use this administrator action from its original service page.', headers=no_store())
        try: body = await read_request(request)
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded offline product sample.', headers=no_store()) from None
        value = await run_in_threadpool(result, 'validate', request.state.admin_user['user_id'], body)
        return JSONResponse(value, headers=no_store())

    return router
