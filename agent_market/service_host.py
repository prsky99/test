"""One independently managed web or background service per process."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
import fcntl
import hashlib
import hmac
import logging
import os
from pathlib import Path
import signal
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import GatewayConfig
from .gateway.server import create_app
from .service_runtime import ServiceControl

log = logging.getLogger(__name__)
KEEP_WARM_SECONDS = 240  # well inside any idle unload window of the embedding or generation server


def warm_models(front):
    """Touch the query embedding and task models so a visitor never pays a cold start."""
    rag, model = front.rag_engine, getattr(front, 'language_model', None)
    embedding = rag.warm_discovery_embedding() if rag is not None and rag.embeddings_enabled is True else None
    generation = model.ping() if model is not None and callable(getattr(model, 'ping', None)) else None
    return embedding, generation


def keep_explore_warm(front, stop, pause=8.0, serving=None):
    """Keep public Explore chip searches computed; one query at a time with a pause between.

    A retained standby slot receives no visitors, so it skips rounds while SERVING says
    so; its searches only added database load and kept pooled sessions busy (11-02)."""
    from .concierge.front import warm_explore
    from .concierge.report_snapshot import _serving

    class RoundStop:
        """Ends a round early once the slot stops serving; a round of 24 chip searches
        otherwise ran about four minutes into standby (11-02)."""
        def is_set(self):
            # An unreadable deployment state counts as serving, as for the report snapshot.
            return stop.is_set() or not _serving(serving)

        def wait(self, seconds):
            return stop.wait(seconds)

    round_stop = RoundStop()
    while not stop.is_set():
        try:
            if not round_stop.is_set():
                warm_explore(front, stop=round_stop, pause=pause)
        except Exception:
            log.warning('Explore keep-warm round failed', exc_info=False)
        stop.wait(pause)


def serving_slot(role, release):
    """Whether this process's release is the active slot of ROLE in the deployment state.

    Without a readable state (tests, a direct start) every process counts as serving."""
    import json
    directory = os.environ.get('AGENTCON_SERVICE_STATE_DIR')
    if not directory:
        return True
    state = json.loads((Path(directory) / 'state.json').read_text())
    service = (state.get('services') or {}).get(role) or {}
    slots, active = service.get('slots') or {}, service.get('active')
    return active not in slots or slots[active] == release


def keep_models_warm(front, stop, interval=KEEP_WARM_SECONDS):
    while not stop.wait(interval):
        try:
            warm_models(front)
        except Exception:
            log.warning('Model keep-warm round failed', exc_info=False)
ROLES = ('frontend', 'admin', 'jobs', 'execution')


def execute_typed(platform, identity, ws, flow):
    """Run an admitted typed flow under the authority that admitted it.

    The web roles admit customer workspace and customer app runs too; the staff
    adapter rejects their opaque customer identity, so each run returns to the
    engine that admitted it (see typed_engine_for)."""
    from .workspace_platform import typed_engine_for
    return typed_engine_for(platform, identity, ws, flow).execute_admitted(identity, ws, flow)

class ActiveRequests:
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        counted = scope['type'] in ('http', 'websocket') and not scope.get('path', '').startswith('/internal/service/')
        if counted:
            self.state.active_requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if counted:
                self.state.active_requests -= 1


def probe_token(key):
    return hmac.new(key, b'private-service-probe-v1', hashlib.sha256).hexdigest()


def create_service_app(config, role, *, store=None, control=None, release='test', warm=True):
    """Construct isolated roles without starting workers from either web app."""
    if role not in ROLES:
        raise ValueError('invalid_service_role')
    gateway = create_app(config, store=store, service_role=role)
    front = gateway.state.front
    front.store._service_role = role
    front.store._service_control = control
    if role == 'frontend':
        from .concierge.front import create_front_app
        app = create_front_app(front, workspace_access_enabled=config.customer_workspace_access,
                               workspace_link_enabled=config.customer_workspace_link,
                               owned_data_agents_enabled=True, manage_book_lifecycle=False,
                               check_owned_sources=False)
        # Public gateway contracts belong to the public process, never admin.
        existing = {getattr(route, 'path', '') for route in app.routes}
        for route in gateway.routes:
            path = getattr(route, 'path', '')
            if path not in existing and not path.startswith(('/admin', '/docs', '/redoc', '/openapi', '/health')):
                app.router.routes.append(route)
        original_front_lifespan = app.router.lifespan_context
    else:
        app = gateway
        if role == 'admin':
            # FastAPI may retain included routers lazily, without a path
            # attribute. The included dashboard contains only staff routes.
            app.router.routes[:] = [r for r in app.routes if not hasattr(r, 'path') or r.path.startswith('/admin')]
    original_gateway_lifespan = gateway.router.lifespan_context
    app.state.front = front
    app.state.service_role = role
    app.state.ready = False
    app.state.release = release
    app.state.active_requests = 0
    app.state.embedding_warmup = None
    app.state.generation_warmup = None
    app.state.gateway = gateway
    app.add_middleware(ActiveRequests, state=app.state)

    @asynccontextmanager
    async def lifecycle(application):
        async with original_gateway_lifespan(gateway):
            @asynccontextmanager
            async def no_front(_):
                yield
            front_context = original_front_lifespan if role == 'frontend' else no_front
            async with front_context(app):
                if control is not None and not control.ready():
                    raise RuntimeError('service_schema_not_installed')
                if warm and role == 'frontend':
                    await run_in_threadpool(front.bootstrap_snapshot)
                    await run_in_threadpool(front.bootstrap_snapshot_json)
                    await run_in_threadpool(front.live_counts)
                    app.state.embedding_warmup, app.state.generation_warmup = await run_in_threadpool(warm_models, front)
                    if app.state.embedding_warmup is False:
                        log.warning('Embedding startup warmup was not confirmed')
                    if app.state.generation_warmup is False:
                        log.warning('Task model startup warmup was not confirmed')
                stop = threading.Event()
                if warm and role == 'frontend':
                    threading.Thread(target=keep_models_warm, args=(front, stop), name='model-keep-warm', daemon=True).start()
                    threading.Thread(target=keep_explore_warm, args=(front, stop), name='explore-keep-warm', daemon=True,
                                     kwargs={'serving': lambda: serving_slot(role, release)}).start()
                    if getattr(front.store, 'backend', None) == 'postgresql':
                        from .concierge.report_snapshot import keep_fresh
                        threading.Thread(target=keep_fresh, args=(front.store, stop), name='report-snapshot', daemon=True,
                                         kwargs={'serving': lambda: serving_slot(role, release)}).start()
                app.state.ready = True
                try:
                    yield
                finally:
                    app.state.ready = False
                    stop.set()
    app.router.lifespan_context = lifecycle

    def report_snapshot_state():
        if role != 'frontend' or getattr(front.store, 'backend', None) != 'postgresql':
            return None
        from .concierge.report_snapshot import state
        return state(front.store)

    @app.get('/internal/service/ready', include_in_schema=False)
    async def readiness(request: Request):
        key = control.key if control is not None else getattr(front.store, 'workflow_key', None)
        supplied = request.headers.get('x-service-probe', '')
        if not key or not hmac.compare_digest(supplied, probe_token(key)):
            return JSONResponse({'detail': 'Not Found'}, status_code=404)
        try:
            await run_in_threadpool(front.store.get_meta, 'service_readiness')
            ready = bool(app.state.ready)
        except Exception:
            ready = False
        return JSONResponse({'ready': ready, 'role': role, 'release': release,
                             'active_requests': app.state.active_requests,
                             'embedding_warmup': app.state.embedding_warmup,
                             'generation_warmup': app.state.generation_warmup,
                             'report_snapshot': report_snapshot_state()},
                            status_code=200 if ready else 503, headers={'Cache-Control': 'no-store'})
    return app


@contextmanager
def local_owner(directory, role):
    """The host lock survives DB disconnects until the process has drained."""
    path = Path(directory)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path / (role + '.owner.lock'), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class BackgroundLoop:
    def __init__(self, app, control, role, stop):
        self.app, self.control, self.role, self.stop = app, control, role, stop
        self.pending = set()
        self.pool = ThreadPoolExecutor(max_workers=4 if role == 'execution' else 1,
                                       thread_name_prefix='service-' + role)
        self.maintenance_pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='service-maintenance') if role=='jobs' else None
        self.maintenance_pending = None
        self.heartbeat_thread = None
        self.reconcile_rejected = set()
        self.ownership_lost = False

    def heartbeat(self):
        collector = self.app.state.gateway.state.collector
        while not self.stop.is_set():
            try:
                status = {'started_at': collector.started_at, 'paused': collector.paused.is_set(),
                          'threads': collector.thread_status()} if self.role == 'jobs' else {'running': True}
                if self.role == 'jobs':
                    vector_status = getattr(collector, 'rag_status', None)
                    if isinstance(vector_status, dict):
                        status['vector_index'] = dict(vector_status)
                self.control.heartbeat(self.role, status)
            except Exception:
                log.error('Service heartbeat failed; stopping ownership')
                self.ownership_lost = True
                self.stop.set()
                break
            self.stop.wait(2)

    def command(self, item):
        gateway = self.app.state.gateway
        collector = gateway.state.collector
        try:
            calls = {'pause': collector.pause, 'resume': collector.resume,
                     'crawl': lambda: collector.crawler.crawl_all(force_full=item['payload']['force_full']),
                     'rescan': gateway.state.service.rescan,
                     'scavenge': lambda: collector.checker.scavenge_retired(limit=50),
                     'rag_index': lambda: gateway.state.rag_pipeline.step(self.app.state.front.store)}
            calls[item['kind']]()
            self.control.finish(item['id'], True)
        except Exception:
            log.exception('Service command failed')
            self.control.finish(item['id'], False)

    def reverify(self, reverifier):
        try:
            report = reverifier.run()
            if report['checked']:
                log.info('Model contract re-verification: %s', report)
        except Exception:
            log.exception('Model contract re-verification round failed')

    def refresh_capability_text(self, refresher):
        try:
            refresher.run()
        except Exception as exc:
            # A failed round only leaves rows on the full-text path; retry after a pause.
            refresher.rest_until = refresher.clock() + 300
            if getattr(exc, 'code', None) == 'statement_failed':
                # A statement timeout under load (11-10 17:50) is expected and retried: no traceback.
                log.warning('Capability text refresh round skipped: statement_failed; retry in 300 s')
            else:
                log.exception('Capability text refresh round failed')

    def run(self):
        from .workspace_platform import platform_for, typed_engine_for
        front = self.app.state.front
        platform = platform_for(front)
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, name='service-heartbeat', daemon=True)
        self.heartbeat_thread.start()
        from .model_contract_reverify import ContractReverifier
        reverify = ContractReverifier(front.store, front.proxy) if self.role == 'jobs' else None
        from .postgres_capability_text import Refresher
        capability_text = Refresher(front.store) if self.role == 'jobs' else None
        from .explore_documents import Refresher as SearchDocumentRefresher
        search_documents = SearchDocumentRefresher(front.store) if self.role == 'jobs' else None
        from .public_availability import AvailabilityMonitor, ConversationRetention
        availability=AvailabilityMonitor(front) if self.role=='jobs' else None
        retention=ConversationRetention(front.book) if self.role=='jobs' else None
        from .concierge.task_pages_job import TaskPagesRefresher
        task_pages=TaskPagesRefresher(front) if self.role=='jobs' else None
        next_due = 0
        while not self.stop.is_set():
            for future in tuple(self.pending):
                if future.done():
                    self.pending.remove(future)
                    try:
                        future.result()
                    except Exception:
                        log.exception('Admitted execution ended without a confirmed result')
            if self.role == 'jobs':
                # Maintenance has one bounded slot so a long crawl cannot delay retention.
                if self.maintenance_pending is not None and self.maintenance_pending.done():
                    try:self.maintenance_pending.result()
                    except Exception:log.exception('Public maintenance round failed')
                    self.maintenance_pending=None
                if self.maintenance_pending is None:
                    if retention.due():self.maintenance_pending=self.maintenance_pool.submit(retention.run)
                    elif availability.due():self.maintenance_pending=self.maintenance_pool.submit(availability.run)
                    elif search_documents.due():self.maintenance_pending=self.maintenance_pool.submit(self.refresh_capability_text, search_documents)
                    elif task_pages.due():self.maintenance_pending=self.maintenance_pool.submit(task_pages.run)
                if not self.pending:
                    item = self.control.claim()
                    if item:
                        self.pending.add(self.pool.submit(self.command, item))
                    elif reverify.due() and not self.app.state.gateway.state.collector.paused.is_set():
                        self.pending.add(self.pool.submit(self.reverify, reverify))
                    elif capability_text.due() and not self.app.state.gateway.state.collector.paused.is_set():
                        self.pending.add(self.pool.submit(self.refresh_capability_text, capability_text))
            else:
                if time.monotonic() >= next_due:
                    from .application_store_postgres import ApplicationStoreError
                    try:
                        front.workflows.run_due()
                    except ApplicationStoreError as exc:
                        # A lock or statement timeout defers this round only; ownership is unaffected.
                        log.warning('Due workflow round deferred after a storage error: %s', getattr(exc, 'code', None) or exc)
                        next_due = time.monotonic() + 2
                        self.stop.wait(.2)
                        continue
                    typed, private = self.control.expired_runs()
                    for kind, rows in (('typed', typed), ('private', private)):
                        for item in rows:
                            if item[0] in self.reconcile_rejected:
                                continue
                            try:
                                if kind == 'typed':
                                    typed_engine_for(platform, *item).reconcile_interrupted(*item)
                                else:
                                    platform.execution._finish(*item, 'unknown', 'INTERRUPTED')
                            except Exception:
                                self.reconcile_rejected.add(item[0])
                                log.error('Interrupted execution reconciliation rejected; manual review required')
                    next_due = time.monotonic() + 2
                if len(self.pending) < 4:
                    item = self.control.claim_private()
                    if item:
                        self.pending.add(self.pool.submit(platform.execution.execute_admitted, *item))
                    elif (item := self.control.claim_typed()) is not None:
                        self.pending.add(self.pool.submit(execute_typed, platform, *item))
            self.stop.wait(.2)

    def close(self):
        self.stop.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(10)
        self.pool.shutdown(wait=True, cancel_futures=False)
        if self.maintenance_pool is not None:self.maintenance_pool.shutdown(wait=True,cancel_futures=False)
        if self.role == 'execution':
            from .workspace_execution import _pool
            _pool.shutdown(wait=True, cancel_futures=False)
        self.control.heartbeat(self.role, {'running': False, 'paused': True})


async def serve_background(app, control, role):
    stop = threading.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with app.router.lifespan_context(app):
        runner = BackgroundLoop(app, control, role, stop)
        try:
            await run_in_threadpool(runner.run)
        finally:
            try:
                await run_in_threadpool(runner.close)
            except Exception:
                if not runner.ownership_lost:
                    raise
    if runner.ownership_lost:
        # Exit non-zero so launchd (KeepAlive SuccessfulExit=false) restarts and re-acquires ownership.
        raise SystemExit('Service ownership was lost; exiting for a supervised restart.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=ROLES, required=True)
    parser.add_argument('--port', type=int)
    parser.add_argument('--release', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--project-root', required=True)
    args = parser.parse_args()
    from scripts.agentcon_config import read_settings, read_local_model_settings, read_local_model_fallback_settings, read_edge_gateway_settings, read_admin_evidence_settings, read_embedding_settings, read_web_bot_settings, read_web_bot_signer_settings
    settings = read_settings(args.settings)
    root = Path(args.project_root).resolve()
    settings.update(read_local_model_settings(str(root / 'gateway-data/local-model.env')))
    settings.update(read_local_model_fallback_settings(root / 'gateway-data/local-model-fallback.env'))
    from scripts.agentcon_config import read_local_model_slot_settings  # 11-11: its own file
    settings.update(read_local_model_slot_settings(root / 'gateway-data/local-model-slots.env'))
    settings.update(read_edge_gateway_settings(str(root / 'gateway-data/edge-gateway.env')))
    settings.update(read_admin_evidence_settings(root / 'gateway-data/admin-evidence.env'))
    settings.update(read_embedding_settings(root / 'gateway-data/embedding.env'))
    settings.update(read_web_bot_settings(root / 'gateway-data/web-bot-auth.env'))
    settings.update(read_web_bot_signer_settings(root / 'gateway-data/web-bot-signer.env'))
    from scripts.agentcon_config import read_sponsored_settings  # 11-11: its own file, unknown to retained releases
    settings.update(read_sponsored_settings(root / 'gateway-data/sponsored.env'))
    from scripts.agentcon_config import read_owner_proof_settings  # 11-11: its own file, like sponsored.env
    settings.update(read_owner_proof_settings(root / 'gateway-data/owner-proof.env'))
    for key in ('GATEWAY_DB', 'APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE',
                'AGENT_EDGE_GATEWAY_CONFIG', 'AGENT_EDGE_CLOUDFLARE_TOKEN_FILE',
                'AGENTCON_ADMIN_BACKUP_ROOT', 'AGENTCON_ADMIN_SQLITE_ARCHIVE', 'WEB_BOT_TRUST_FILE',
                'WEB_BOT_AUTH_KEY_FILE', 'AD_COIN_PAID_PAY_TO_FILE', 'AD_COIN_OFAC_LIST'):
        if settings.get(key) and not Path(settings[key]).is_absolute():
            settings[key] = str(root / settings[key])
    os.environ.update(settings)
    os.environ["AGENTCON_PROJECT_ROOT"] = str(root)
    os.environ['AGENTCON_SERVICE_STATE_DIR'] = str(Path(args.state_dir).resolve())
    os.environ['LOG_DIR'] = str(root / 'logs' / ('service-' + args.role))
    os.environ['LOG_ARCHIVE_DIR'] = str(root / 'logs' / 'archive' / args.role)
    config = GatewayConfig.from_env()
    from .logger import setup_logging, shutdown_logging
    setup_logging(log_dir=config.log_dir, archive_dir=config.log_archive_dir,
                  default_level=config.log_level, compress_months=config.log_compress_months,
                  log_to_console=config.log_to_console)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    control = ServiceControl.open(reconnect=args.role not in ('jobs', 'execution'))
    if not control.ready():
        raise SystemExit('Install the private service schema before starting services.')
    try:
        if args.role in ('jobs', 'execution'):
            with local_owner(args.state_dir, args.role):
                control.acquire_owner(args.role)
                app = create_service_app(config, args.role, control=control, release=args.release)
                asyncio.run(serve_background(app, control, args.role))
        else:
            if args.port is None or not 1024 <= args.port <= 65535:
                raise SystemExit('An explicit unprivileged service port is required.')
            from .gateway.deployment_security import TrustedIngressMiddleware, trusted_proxy_options, validate_production_runtime
            from .gateway.startup import reserve_listeners
            import uvicorn
            with reserve_listeners([(args.role, '127.0.0.1', args.port)]) as sockets:
                app = create_service_app(config, args.role, control=control, release=args.release)
                validate_production_runtime(config, app.state.front.store)
                server = uvicorn.Server(uvicorn.Config(TrustedIngressMiddleware(app), host='127.0.0.1',
                    port=args.port, timeout_keep_alive=15, timeout_graceful_shutdown=90,
                    log_config=None, **trusted_proxy_options()))
                asyncio.run(server.serve(sockets=sockets))
    finally:
        control.close()
        shutdown_logging()


if __name__ == '__main__':
    main()
