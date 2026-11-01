"""Scoped admin-export deployments; public template downloads retain their own API."""
from copy import deepcopy
import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .concierge.recommendation_security import secret_name, usable_endpoint
from .workflows import WorkflowError, canonical, public_outcome, public_template

SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflow_apps (
 id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL,key_hash TEXT NOT NULL,
 definition_hash TEXT NOT NULL,origins TEXT NOT NULL,fields TEXT NOT NULL,
 minute_limit INTEGER NOT NULL,day_limit INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_app_runs (
 run_id TEXT PRIMARY KEY,app_id TEXT NOT NULL,key_hash TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_app_usage (
 app_id TEXT NOT NULL,bucket INTEGER NOT NULL,identity TEXT NOT NULL,operation TEXT NOT NULL,n INTEGER NOT NULL,
 PRIMARY KEY(app_id,bucket,identity,operation));
'''


def normalize_origins(values):
    if not isinstance(values, list) or len(values) > 20:
        raise WorkflowError('Use at most 20 HTTP(S) origins.')
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 250 or re.search(r'[\s\\%]', value):
            raise WorkflowError('Use an exact HTTP(S) origin without a path.')
        try:
            parts = urlsplit(value)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.path not in ('', '/') or parts.query or parts.fragment:
                raise ValueError()
            host = parts.hostname.encode('idna').decode().lower()
            if ':' in host: host = '[' + host + ']'
            port = parts.port
            if port is not None and not 0 < port < 65536: raise ValueError()
            normalized = parts.scheme + '://' + host + (':' + str(port) if port and port != (443 if parts.scheme == 'https' else 80) else '')
        except (ValueError, UnicodeError):
            raise WorkflowError('Use an exact HTTP(S) origin without a path.') from None
        if normalized not in result: result.append(normalized)
    return result


class WorkflowApps:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime
        with store._lock: store._db.executescript(SCHEMA)

    def published(self, identity):
        workflow = self.store.get_workflow(identity)
        projected = public_template(workflow) if workflow else None
        if projected is None: raise WorkflowError('Publish a safe active template before exporting.')
        return projected

    def candidates(self, workflow):
        fields = []
        for node in workflow['nodes']:
            data = node.get('data', {})
            if node.get('type') != 'agent' or not isinstance(data.get('input'), dict): continue
            resource = self.store.resource(node.get('resource_id') or data.get('resource_id'))
            tools = (resource or {}).get('usage_tools') or []
            if isinstance(tools, str):
                try: tools = json.loads(tools)
                except ValueError: tools = []
            if not isinstance(tools, list): tools = []
            tool = next((t for t in tools if isinstance(t, dict) and t.get('name') == (data.get('action') or data.get('tool'))), {})
            for argument, default in data['input'].items():
                if secret_name(argument) or re.search(r'(?i)token|password|credential|authorization|wallet|payment|header', argument): continue
                if type(default) not in (str, int, float, bool) or isinstance(default, str) and '{{$' in default: continue
                field_type = 'boolean' if type(default) is bool else 'integer' if type(default) is int else 'number' if type(default) is float else 'string'
                params = tool.get('params')
                spec = params.get(argument, {}) if isinstance(params, dict) else {}
                if not isinstance(spec, dict): spec = {}
                if spec.get('type') and spec['type'] != field_type and not (spec['type'] == 'number' and field_type == 'integer'): continue
                key = 'field_' + hashlib.sha256((node['id'] + '\0' + argument).encode()).hexdigest()[:16]
                label = (node['name'] + ' / ' + argument)[:100]
                if re.search(r'[^\x20-\x7e]', label): label = 'Input ' + str(len(fields) + 1)
                fields.append({'id':key, 'label':label, 'type':field_type, 'node_id':node['id'], 'argument':argument})
        return fields[:40]

    def create(self, identity, options):
        workflow = self.published(identity)
        selected = options.get('input_fields', [])
        if not isinstance(selected, list) or len(selected) > 10 or len(set(str(v) for v in selected)) != len(selected):
            raise WorkflowError('Choose at most 10 distinct input fields.')
        candidates = {f['id']:f for f in self.candidates(workflow)}
        if any(not isinstance(v, str) or v not in candidates for v in selected): raise WorkflowError('An input binding is no longer available.')
        origins = normalize_origins(options.get('allowed_origins', []))
        minute, day = options.get('minute_limit', 10), options.get('day_limit', 500)
        if type(minute) is not int or not 1 <= minute <= 30 or type(day) is not int or not 1 <= day <= 5000:
            raise WorkflowError('Use 1–30 starts per minute and 1–5000 starts per day.')
        app_id, key = 'app_' + secrets.token_hex(16), 'wfpk_' + secrets.token_urlsafe(32)
        fields = [candidates[f] for f in selected]
        with self.store.tx() as db:
            db.execute('INSERT INTO workflow_apps VALUES (?,?,?,?,?,?,?,?,1,?)',
                       (app_id, identity, hashlib.sha256(key.encode()).hexdigest(), workflow['definition_hash'], canonical(origins), canonical(fields), minute, day, time.time()))
        return {'app_id':app_id, 'publish_key':key, 'workflow_id':identity, 'allowed_origins':origins,
                'input_fields':[{k:f[k] for k in ('id', 'label', 'type')} for f in fields],
                'minute_limit':minute, 'day_limit':day, 'sdk_version':'1.1.0'}

    def list(self, identity):
        return [{**dict(r), 'origins':json.loads(r['origins'])} for r in self.store.query('SELECT id,workflow_id,origins,minute_limit,day_limit,active,created FROM workflow_apps WHERE workflow_id=? ORDER BY created DESC LIMIT 50', (identity,))]

    def revoke(self, identity, app_id):
        with self.store.tx() as db:
            changed = db.execute('UPDATE workflow_apps SET active=0 WHERE id=? AND workflow_id=?', (app_id, identity)).rowcount
        if not changed: raise WorkflowError('Deployment not found.')
        for row in self.store.query("SELECT r.id FROM workflow_runs r JOIN workflow_app_runs a ON a.run_id=r.id WHERE a.app_id=? AND r.status IN ('queued','running')", (app_id,)):
            self.runtime.cancel(row['id'])

    def authorize(self, app_id, key, origin, *, read=False):
        if not re.fullmatch(r'app_[a-f0-9]{32}', app_id) or not isinstance(key, str) or not re.fullmatch(r'wfpk_[A-Za-z0-9_-]{43}', key):
            raise WorkflowError('Deployment unavailable.')
        rows = self.store.query('SELECT * FROM workflow_apps WHERE id=? AND active=1', (app_id,))
        if not rows or not hmac.compare_digest(rows[0]['key_hash'], hashlib.sha256(key.encode()).hexdigest()): raise WorkflowError('Deployment unavailable.')
        app = dict(rows[0]); allowed = json.loads(app['origins'])
        if allowed and (not origin or origin == 'null' or normalize_origins([origin])[0] not in allowed): raise WorkflowError('Deployment unavailable.')
        consent=self.runtime.deployment_consent
        if consent.is_v12(app_id):
            try:(consent.read_access if read else consent.current)(app_id,origin=origin)
            except (ValueError,TypeError,KeyError):raise WorkflowError('Deployment unavailable.') from None
        return app

    def quota(self, app, ip, operation):
        # Public keys and Origin checks are deployment controls, not user authentication.
        identity = hmac.new(self.runtime.key, str(ip).encode(), hashlib.sha256).hexdigest()
        minute, day = int(time.time() // 60), int(time.time() // 86400) * 1440
        counters = [(minute, 'app', operation, app['minute_limit'] if operation == 'start' else 1200),
                    (minute, identity, operation, min(5, app['minute_limit']) if operation == 'start' else 180)]
        if operation == 'start': counters.append((day, 'app', 'daily', app['day_limit']))
        with self.store.tx() as db:
            for bucket, who, op, limit in counters:
                row = db.execute('SELECT n FROM workflow_app_usage WHERE app_id=? AND bucket=? AND identity=? AND operation=?', (app['id'], bucket, who, op)).fetchone()
                if row and row[0] >= limit: raise WorkflowError('Deployment rate limit reached.')
            for bucket, who, op, _ in counters:
                db.execute('INSERT INTO workflow_app_usage VALUES (?,?,?,?,1) ON CONFLICT(app_id,bucket,identity,operation) DO UPDATE SET n=n+1', (app['id'], bucket, who, op))
            db.execute('DELETE FROM workflow_app_usage WHERE app_id=? AND bucket<?', (app['id'], day - 1440))

    def start(self, app, body):
        if self.runtime.deployment_consent.is_v12(app['id']):
            raise WorkflowError('Use the separately reviewed SDK 1.2 execution protocol.')
        if set(body) - {'input'}: raise WorkflowError('Only declared application inputs may be submitted.')
        user_input = body.get('input', {})
        if not isinstance(user_input, dict) or len(canonical(user_input).encode()) > 12000: raise WorkflowError('Use a bounded input object.')
        fields = {f['id']:f for f in json.loads(app['fields'])}
        if set(user_input) - set(fields): raise WorkflowError('Unknown application input.')
        workflow = self.published(app['workflow_id'])
        if workflow['definition_hash'] != app['definition_hash']: raise WorkflowError('The published definition changed. Export a new deployment.')
        nodes = {n['id']:n for n in workflow['nodes']}
        for key, value in user_input.items():
            field = fields[key]; kind = field['type']
            if kind == 'string': valid = type(value) is str and len(value) <= 4096 and '{{$' not in value
            elif kind == 'boolean': valid = type(value) is bool
            elif kind == 'integer': valid = type(value) is int and abs(value) <= 10**6
            else: valid = type(value) in (int, float) and math.isfinite(value) and abs(value) <= 10**6
            if not valid: raise WorkflowError('An application input has an invalid type or value.')
            if isinstance(value, str) and (re.search(r'(?i)url|uri|endpoint', field['argument']) or re.match(r'(?i)^(?:[a-z][a-z0-9+.-]*://|https?:)', value.strip())) and not usable_endpoint(value):
                raise WorkflowError('Use a public HTTP(S) URL without credentials.')
            nodes[field['node_id']]['data']['input'][field['argument']] = value
        key = secrets.token_urlsafe(32)
        # Do not create a legacy public API capability for deployment runs.
        job = self.runtime.submit(deepcopy(workflow), actor='webapp:' + app['id'], source='webapp',
            principal=self.runtime.principal('deployment',app['id'],workflow['id']))
        with self.store.tx() as db:
            db.execute('INSERT INTO workflow_app_runs VALUES (?,?,?,?)', (job['run_id'], app['id'], hashlib.sha256(key.encode()).hexdigest(), time.time() + 3600))
        return {**job, 'run_key':key}

    def check_run(self, app, run_id, key):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', key): raise WorkflowError('Run not found.')
        rows = self.store.query('SELECT * FROM workflow_app_runs WHERE run_id=? AND app_id=? AND expires>?', (run_id, app['id'], time.time()))
        if not rows or not hmac.compare_digest(rows[0]['key_hash'], hashlib.sha256(key.encode()).hexdigest()): raise WorkflowError('Run not found.')


def service_for(store, runtime):
    with store._lock:
        if not hasattr(store, '_workflow_apps'): store._workflow_apps = WorkflowApps(store, runtime)
        return store._workflow_apps


def workflow_apps_router(front):
    router = APIRouter(prefix='/api/workflow-apps')
    service = service_for(front.store, front.workflows)
    def cors():
        return {'Access-Control-Allow-Origin':'*', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'}
    @router.options('/{app_id}/runs')
    @router.options('/{app_id}/runs/{run_id}')
    @router.options('/{app_id}/runs/{run_id}/cancel')
    def options(app_id: str, run_id: str = ''):
        return Response(status_code=204, headers={**cors(), 'Access-Control-Allow-Methods':'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers':'Content-Type, X-Publish-Key, X-Workflow-Key',
            'Access-Control-Expose-Headers':'Retry-After', 'Access-Control-Max-Age':'600'})
    async def dispatch(app_id, req, run_id=None, cancel=False):
        try:
            app = service.authorize(app_id, req.headers.get('x-publish-key'), req.headers.get('origin'),read=run_id is not None)
            if run_id:
                service.check_run(app, run_id, req.headers.get('x-workflow-key'))
            service.quota(app, front.security.resolve_ip(req), 'poll' if run_id and not cancel else 'cancel' if cancel else 'start')
        except WorkflowError as exc:
            limited = 'rate limit' in str(exc)
            return JSONResponse({'error':'Deployment rate limit reached.' if limited else 'Deployment or run unavailable.'}, status_code=429 if limited else 404,
                                headers={**cors(), **({'Retry-After':'60', 'Access-Control-Expose-Headers':'Retry-After'} if limited else {})})
        if not run_id:
            try:
                raw = bytearray()
                async with asyncio.timeout(10):
                    async for chunk in req.stream():
                        raw.extend(chunk)
                        if len(raw) > 16000: raise WorkflowError('Input size limit reached.')
                body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(body, dict): raise ValueError()
                result = await run_in_threadpool(service.start, app, body)
            except (WorkflowError, ValueError, UnicodeError, RecursionError, TimeoutError):
                return JSONResponse({'error':'Use the published application inputs. The deployment may need to be exported again.'}, status_code=400, headers=cors())
            return JSONResponse(result, status_code=202, headers=cors())
        if cancel:
            await run_in_threadpool(service.runtime.cancel, run_id)
            return JSONResponse({'ok':True, 'cancel_requested':True}, headers=cors())
        result = await run_in_threadpool(service.runtime.get, run_id)
        return JSONResponse(public_outcome(result), headers=cors())
    @router.post('/{app_id}/runs')
    async def start(app_id: str, req: Request): return await dispatch(app_id, req)
    @router.get('/{app_id}/runs/{run_id}')
    async def status(app_id: str, run_id: str, req: Request): return await dispatch(app_id, req, run_id)
    @router.post('/{app_id}/runs/{run_id}/cancel')
    async def cancel(app_id: str, run_id: str, req: Request): return await dispatch(app_id, req, run_id, True)
    from .workflow_apps_v12 import router_for
    combined=APIRouter()
    combined.include_router(router)
    combined.include_router(router_for(front))
    from .workflow_publication_service import public_router_for
    combined.include_router(public_router_for(front))
    from .workflow_connection_deployment_service import public_router_for as connected_apps_router_for
    combined.include_router(connected_apps_router_for(front))
    return combined
