"""Renewed administrator console (P1): pearl shell, v2 read APIs and server read cache.

Runs beside the existing `/admin/ui`. Every v2 route requires an individual
administrator session; the shared machine token and the unauthenticated
localhost fallback are refused here. Responses carry `captured_at` so the page
can show how fresh each figure is. Reviewed mutations delegate to existing
domain services and their audit rules.
"""
import hashlib
import json
import math
import re
import threading
import time
import unicodedata
from pathlib import Path

from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

ASSETS = Path(__file__).resolve().parent / 'gateway' / 'admin_next'
_TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml'}
_ASSET = re.compile(r'(?:core|areas)/[a-z][a-z0-9-]{0,40}\.js|[a-z][a-z0-9-]{0,40}\.(?:css|svg)')
HOURS = (1, 6, 24, 168)
STATUSES = ('healthy', 'reachable', 'failing', 'down', 'retired', 'unknown', 'quarantined')
KINDS = ('a2a', 'mcp', 'x402')
# Retention view: fixed table/time-column pairs, never request-supplied identifiers.
RETENTION = (('health_checks', 'at'), ('legacy_vector_jobs', 'created'), ('platform_operations', 'created'),
             ('security_events', 'at'), ('crawl_runs', 'at'), ('agent_messages', 'at'),
             ('workspace_admin_events', 'occurred'), ('admin_audit_logs', 'at'))
_CATALOG_COLUMNS = ('id, kind, source, name, url, category, active, health_status, health_ok_24h, health_n_24h, '
                    'probe_latency_ms, eval_grade, eval_score, last_check_at')
_FILTERS_PG = (" FROM resources WHERE active=1 AND (%s::text IS NULL OR kind=%s) AND (%s::text IS NULL OR health_status=%s)"
               " AND (%s::text IS NULL OR name ILIKE %s ESCAPE '\\' OR url ILIKE %s ESCAPE '\\')")
_FILTERS_SQLITE = (" FROM resources WHERE active=1 AND (? IS NULL OR kind=?) AND (? IS NULL OR health_status=?)"
                   " AND (? IS NULL OR name LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')")
_CATALOG_PG = 'SELECT ' + _CATALOG_COLUMNS + _FILTERS_PG + ' AND (%s::bigint IS NULL OR id < %s) ORDER BY id DESC LIMIT %s'
_CATALOG_COUNT_PG = 'SELECT COUNT(*) AS n' + _FILTERS_PG
_CATALOG_SQLITE = 'SELECT ' + _CATALOG_COLUMNS + _FILTERS_SQLITE + ' AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?'
_CATALOG_COUNT_SQLITE = 'SELECT COUNT(*) AS n' + _FILTERS_SQLITE
# Audit action -> cache tags refreshed in open consoles (design 11.5).
_REVIEW_ID = re.compile(r'arc_[a-f0-9]{32}')
TAGS = (('ADMIN_AGENT_NOTE', ('catalog:agents',)), ('CASE_ASSIGN', ('customers',)), ('AGENT_', ('catalog:agents', 'home')), ('COLLECTOR_', ('home', 'catalog:agents')), ('SCAVENGE', ('home', 'catalog:agents')),
        ('ERC8004', ('home',)), ('execution_controls', ('gateway:controls', 'home')), ('fallback_control', ('gateway:controls', 'home')),
        ('REGISTER', ('catalog:agents', 'home')), ('PUBLIC_OPERATION_', ('public', 'security', 'reviews', 'home')), ('REVIEWED_', ('reviews', 'gateway:controls', 'public', 'security', 'home')),
        ('INQUIRY_', ('requests',)), ('PRIVACY_', ('requests',)))


def reason_text(value):
    """A short reviewed reason: printable, 4-300 characters."""
    if type(value) is not str:
        raise HTTPException(400, '변경 사유를 입력하세요.')
    text = ' '.join(''.join(ch for ch in value if unicodedata.category(ch)[0] != 'C').split())
    if not 4 <= len(text) <= 300:
        raise HTTPException(400, '변경 사유는 4~300자로 입력하세요.')
    return text


def tags_for(action, target):
    found = ['home']
    for prefix, tags in TAGS:
        if str(action).startswith(prefix):
            found = list(tags)
            break
    if isinstance(target, str) and target.startswith('agent:') and target[6:].isdigit():
        found.append('catalog:agent:' + target[6:])
    return found


def etag_of(value):
    # The capture time and cache state change on every read; only the content decides the tag.
    payload = {k: v for k, v in value.items() if k not in ('cache', 'captured_at')} if isinstance(value, dict) else value
    return 'W/"' + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()[:24] + '"'

# Fixed PostgreSQL statistics read inside a read-only transaction; no request text enters SQL.
_STORAGE_PG = '''SELECT relname AS name, n_live_tup AS rows, pg_total_relation_size(relid) AS bytes
    FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 40'''
_DATABASE_PG = 'SELECT pg_database_size(current_database()) AS bytes, (SELECT COUNT(*) FROM pg_stat_user_tables) AS tables'
_ACTIVITY_PG = '''SELECT COUNT(*) FILTER (WHERE wait_event_type='Lock') AS lock_waits,
    COUNT(*) FILTER (WHERE state='active' AND now()-query_start > interval '3 seconds') AS slow_queries,
    COUNT(*) FILTER (WHERE state<>'idle') AS busy
    FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()'''
# Live database activity (design 6.2): the global writer lock and the slowest statements, read only.
_WRITER_PG = '''SELECT l.pid, l.granted, a.application_name AS app,
    EXTRACT(EPOCH FROM now()-a.xact_start) AS xact_seconds, EXTRACT(EPOCH FROM now()-a.query_start) AS seconds
    FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid
    WHERE l.locktype='advisory' AND l.classid=%s AND l.objid=%s AND l.objsubid=1 ORDER BY l.granted DESC, a.query_start'''
_SLOW_PG = '''SELECT pid, state, wait_event_type AS wait_type, wait_event AS wait, application_name AS app,
    EXTRACT(EPOCH FROM now()-query_start) AS seconds, cardinality(pg_blocking_pids(pid)) AS blocked_by, left(query, 600) AS query
    FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND state<>'idle' AND query_start IS NOT NULL
    ORDER BY query_start LIMIT 5'''
_LITERALS = re.compile(r"'(?:[^']|'')*'|\b\d+(?:\.\d+)?\b")


def statement_shape(text):
    """Statement text without literal values: strings and numbers become ?."""
    return ' '.join(_LITERALS.sub('?', text or '').split())[:160]


_GATEWAY = {
    'operations': '''SELECT source, protocol, status, error_code, COUNT(*) AS n
        FROM platform_operations WHERE created>? GROUP BY source, protocol, status, error_code''',
    'attempts': '''SELECT a.resource_id, a.status, a.error_code, a.elapsed_ms, a.finished
        FROM platform_attempts a WHERE a.created>? ORDER BY a.created DESC LIMIT 5000''',
    'names': 'SELECT id, name, kind FROM resources WHERE id IN ({})',
}
_GATEWAY_PG = {
    'operations': _GATEWAY['operations'].replace('?', '%s'),
    'attempts': _GATEWAY['attempts'].replace('?', '%s'),
    'names': 'SELECT id, name, kind FROM resources WHERE id = ANY(%s::bigint[])',
}


class TimedCache:
    """Bounded single-flight reads; invalidation fences older refresh results.

    With `persist`, a cold process answers from the last saved projection and refreshes it in the
    background (design 5.3: screens do not wait on source aggregation after a restart).
    """

    def __init__(self, fresh, stale, clock=time.monotonic, persist=None):
        self.fresh, self.stale, self.clock, self.persist = fresh, stale, clock, persist
        self.values, self.busy = {}, set()
        self.lock = threading.Condition(threading.RLock())
        self.revision = 0
        self.invalidated = False  # a saved projection predates a local write until the next save

    def invalidate(self):
        with self.lock:
            self.revision += 1
            self.values.clear()
            self.invalidated = True
            self.lock.notify_all()

    def _seed(self, key):
        """Load a saved projection into memory as stale; never blocks the read on failure."""
        if self.persist is None or self.invalidated or key in self.values:
            return
        saved = self.persist.load(key)
        if saved is None:
            return
        age, value = saved
        with self.lock:
            if key not in self.values and not self.invalidated:
                # Saved values sit inside the stale window: served once, refreshed in the background.
                self.values[key] = (self.clock() - min(max(age, self.fresh + 0.001), (self.fresh + self.stale) / 2), value)

    def get(self, key, loader, *, force=False):
        stop = time.monotonic() + 25
        if not force:
            self._seed(key)
        with self.lock:
            while True:
                hit = None if force else self.values.get(key)
                if hit and self.clock() - hit[0] <= self.fresh:
                    return {**hit[1], 'cache': 'hit'}
                stale = hit and self.clock() - hit[0] <= self.stale
                if stale:
                    if key not in self.busy:
                        self.busy.add(key)
                        threading.Thread(target=self._load, args=(key, loader, self.revision),
                                         daemon=True, name='admin-next-refresh').start()
                    return {**hit[1], 'cache': 'stale'}
                if key not in self.busy:
                    self.busy.add(key)
                    revision = self.revision
                    break
                remaining = stop - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Administrator projection read is busy')
                self.lock.wait(remaining)
                force = False
        return {**self._load(key, loader, revision, raise_errors=True), 'cache': 'miss'}

    def _load(self, key, loader, revision, raise_errors=False):
        try:
            value = loader()
            with self.lock:
                if revision == self.revision:
                    self.values[key] = (self.clock(), value)
                    while len(self.values) > 128:
                        del self.values[next(iter(self.values))]
                    current = True
                else:
                    current = False
            if current and self.persist is not None and self.persist.save(key, value):
                with self.lock:
                    if revision == self.revision:
                        self.invalidated = False
            return value
        except Exception:
            if raise_errors:
                raise
            return None
        finally:
            with self.lock:
                self.busy.discard(key)
                self.lock.notify_all()



class SnapshotStore:
    """Last-known console projections kept in the migrated workspace_admin_state table.

    Aggregates only (no customer records). Writes are throttled per key so the global writer
    lock is touched at most once per `every` seconds; failures fall back to live reads.
    """
    PREFIX = 'admin_next.snapshot:'

    def __init__(self, store, every=60, oldest=86400, clock=time.time):
        self.store, self.every, self.oldest, self.clock = store, every, oldest, clock
        self.saved = {}

    def ready(self):
        return bool(getattr(self.store, '_workspace_admin_events_enabled', False))

    def load(self, key):
        if not self.ready():
            return None
        from .workspace_admin_events import rows, transaction
        try:
            with transaction(self.store, True) as db:
                found = rows(db, 'state', (self.PREFIX + str(key),))
            if not found:
                return None
            value = json.loads(found[0]['value'])
            age = self.clock() - float(value['captured'])
            return (age, value['value']) if 0 <= age <= self.oldest and isinstance(value['value'], dict) else None
        except Exception:
            return None

    def save(self, key, value):
        now = self.clock()
        if not self.ready() or now - self.saved.get(key, 0) < self.every:
            return False
        from .workspace_admin_events import execute, transaction
        try:
            text = json.dumps({'captured': now, 'value': value}, separators=(',', ':'), default=str, allow_nan=False)
            if len(text) > 512 * 1024:
                return False
            with transaction(self.store) as db:
                execute(db, 'put_state', (self.PREFIX + str(key), text))
            self.saved[key] = now
            return True
        except Exception:
            return False


def percentile(values, share):
    ordered = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def summarize_gateway(operations, attempts, names, hours, now):
    total = sum(row['n'] for row in operations)
    ok = sum(row['n'] for row in operations if row['status'] in ('succeeded', 'matched'))
    by_source, by_code = {}, {}
    for row in operations:
        source = row['source'] or 'unknown'
        entry = by_source.setdefault(source, {'source': source, 'total': 0, 'succeeded': 0})
        entry['total'] += row['n']
        entry['succeeded'] += row['n'] if row['status'] in ('succeeded', 'matched') else 0
        if row['error_code']:
            by_code[row['error_code']] = by_code.get(row['error_code'], 0) + row['n']
    agents = {}
    for row in attempts:
        rid = row['resource_id']
        if rid is None:
            continue
        entry = agents.setdefault(rid, {'id': rid, 'calls': 0, 'succeeded': 0, 'latencies': [], 'last_error': None})
        entry['calls'] += 1
        entry['succeeded'] += row['status'] == 'succeeded'
        entry['latencies'].append(row['elapsed_ms'])
        if row['error_code'] and entry['last_error'] is None:
            entry['last_error'] = row['error_code']
    top = sorted(agents.values(), key=lambda item: (-item['calls'], item['id']))[:20]
    for entry in top:
        meta = names.get(entry['id'], {})
        entry.update(name=meta.get('name') or 'Agent %d' % entry['id'], kind=meta.get('kind'),
                     success_rate=round(entry['succeeded'] / entry['calls'], 3) if entry['calls'] else None,
                     p95_ms=percentile(entry.pop('latencies'), .95))
    latencies = [row['elapsed_ms'] for row in attempts]
    timeline = [{'id': row['resource_id'], 'status': row['status'], 'code': row['error_code'], 'at': row['finished']}
                for row in attempts[:60]]
    return {'available': True, 'attempt_sample_limit': 5000, 'attempt_sample_size': len(attempts),
            'latency_scope': 'latest_at_most_5000_attempts', 'hours': hours, 'operations': total, 'succeeded': ok,
            'success_rate': round(ok / total, 3) if total else None,
            'p50_ms': percentile(latencies, .5), 'p95_ms': percentile(latencies, .95),
            'by_source': sorted(by_source.values(), key=lambda item: -item['total']),
            'error_codes': sorted(({'code': code, 'n': n} for code, n in by_code.items()), key=lambda item: -item['n']),
            'agents': top, 'timeline': timeline, 'captured_at': now}


def install(router, *, store, authorize, admin_token, overview, reader, rows, log_op=None, agent_actions=None,
            collector_actions=None, controls=None, audit=None, public_summary=None, reviews=None, summaries=None,
            retention=None, finance=None):
    """Attach the renewed console to the existing administrator router."""
    snapshots = SnapshotStore(store)
    cache = {'home': TimedCache(5, 30, persist=snapshots), 'gateway': TimedCache(10, 60, persist=snapshots), 'storage': TimedCache(300, 3600),
             'retention': TimedCache(3600, 21600), 'public': TimedCache(10, 60),
             'activity': TimedCache(3, 10)}
    agent_actions, collector_actions, controls = agent_actions or {}, collector_actions or {}, controls or {}

    def staff(request: Request, authorization: str | None = Header(default=None),
              x_dashboard: str | None = Header(default=None)):
        # Console routes require individual sessions even in development mode.
        token = (authorization or '')[7:].strip() if (authorization or '').startswith('Bearer ') else ''
        if not token or (admin_token and token == admin_token):
            raise HTTPException(401, '개인 관리자 계정으로 로그인하세요.')
        user = authorize(request, authorization, x_dashboard)
        if not user.get('is_authenticated_session') or user.get('role') not in ('superadmin', 'admin', 'operator', 'viewer'):
            raise HTTPException(403, '이 화면을 볼 권한이 없습니다.')
        request.state.admin_user = user
        return user

    def respond(value, request=None):
        # Conditional reads: an unchanged body answers 304 so revalidation costs no transfer.
        tag = etag_of(value)
        headers = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization, X-Dashboard', 'ETag': tag}
        if request is not None and request.headers.get('if-none-match') == tag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(value, headers=headers)

    def require(user, *roles):
        if user.get('role') not in roles:
            raise HTTPException(403, '이 작업을 할 권한이 없습니다.')

    async def body_of(request, limit=4096):
        raw = await request.body()
        if len(raw) > limit:
            raise HTTPException(413, '요청이 너무 큽니다.')
        try:
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError('Duplicate field')
                    value[key] = item
                return value
            def invalid_constant(value):
                raise ValueError('Non-finite JSON constant')
            value = json.loads(raw or b'{}', object_pairs_hook=unique, parse_constant=invalid_constant)
        except ValueError:
            raise HTTPException(400, '요청 형식이 올바르지 않습니다.') from None
        if not isinstance(value, dict):
            raise HTTPException(400, '요청 형식이 올바르지 않습니다.')
        return value

    def native(sql, params=()):
        pool = getattr(store, '_admin_read_pool', None)
        if pool is None:
            with store.tx(readonly=True):
                return [dict(row) for row in store._execute(sql, params).fetchall()]
        with pool.lease_store() as session:
            with session.tx(readonly=True):
                return [dict(row) for row in session._execute(sql, params).fetchall()]

    def postgres():
        return getattr(store, 'backend', None) == 'postgresql'

    def gateway_data(hours):
        now = time.time(); since = now - hours * 3600
        if postgres():
            operations = native(_GATEWAY_PG['operations'], (since,))
            attempts = native(_GATEWAY_PG['attempts'], (since,))
            ids = sorted({row['resource_id'] for row in attempts if row['resource_id'] is not None})[:200]
            names = {row['id']: row for row in native(_GATEWAY_PG['names'], ('{' + ','.join(map(str, ids)) + '}',))} if ids else {}
        else:
            with reader() as db:
                operations = rows(db.execute(_GATEWAY['operations'], (since,)))
                attempts = rows(db.execute(_GATEWAY['attempts'], (since,)))
                ids = sorted({row['resource_id'] for row in attempts if row['resource_id'] is not None})[:200]
                names = {row['id']: row for row in rows(db.execute(_GATEWAY['names'].format(','.join('?' * len(ids))), ids))} if ids else {}
        return summarize_gateway(operations, attempts, names, hours, now)

    def storage_data():
        now = time.time()
        if not postgres():
            return {'engine': 'sqlite', 'available': False, 'tables': [], 'captured_at': now}
        database = native(_DATABASE_PG)[0]
        return {'engine': 'postgresql', 'available': True, 'database_bytes': database['bytes'],
                'table_count': database['tables'], 'tables': native(_STORAGE_PG),
                'activity': native(_ACTIVITY_PG)[0], 'captured_at': now}

    def activity_data():
        from .application_store_postgres import WRITER_LOCK
        now = time.time()
        if not postgres():
            return {'available': False, 'captured_at': now}
        writer = native(_WRITER_PG, (WRITER_LOCK >> 32, WRITER_LOCK & 0xffffffff))
        holder = next((row for row in writer if row['granted']), None)
        number = lambda value: round(float(value), 2) if value is not None else None
        return {'available': True, 'captured_at': now,
                'writer': {'held': holder is not None, 'app': holder and holder['app'],
                           'held_seconds': number(holder and holder['xact_seconds']),
                           'waiting': sum(1 for row in writer if not row['granted']),
                           'longest_wait_seconds': number(max((row['seconds'] or 0 for row in writer if not row['granted']), default=None))},
                'slow': [{'pid': row['pid'], 'state': row['state'], 'wait': ' · '.join(filter(None, (row['wait_type'], row['wait']))) or None,
                          'app': row['app'], 'seconds': number(row['seconds']), 'blocked_by': row['blocked_by'],
                          'statement': statement_shape(row['query'])} for row in native(_SLOW_PG)]}

    def alerts(home, gateway):
        found = []
        if gateway.get('available') is False:
            found.append({'level': 'warning', 'area': 'gateway', 'text': '게이트웨이 관측을 확인할 수 없습니다.'})
        rate = gateway.get('success_rate')
        if rate is not None and gateway.get('operations', 0) >= 20 and rate < .9:
            found.append({'level': 'danger', 'area': 'gateway', 'text': '최근 %d시간 실행 성공률 %.0f%%' % (gateway['hours'], rate * 100)})
        backlog = (home.get('health') or home.get('backlog') or {}) if isinstance(home, dict) else {}
        overdue = backlog.get('overdue_6h') or 0
        if overdue > 1000:
            found.append({'level': 'warning', 'area': 'catalog', 'text': '예정 시각보다 6시간 넘게 밀린 상태 확인 %s건' % format(overdue, ',')})
        for item in gateway.get('error_codes', [])[:1]:
            if item['n'] >= 10:
                found.append({'level': 'warning', 'area': 'gateway', 'text': '%s 오류 %d건' % (item['code'], item['n'])})
        return found

    @router.get('/admin/next', response_class=HTMLResponse, include_in_schema=False)
    def next_page():
        from .gateway.admin_policy import development_banner
        html = development_banner((ASSETS / 'index.html').read_text(encoding='utf-8'))
        return HTMLResponse(html, headers={
            'cache-control': 'no-store', 'x-frame-options': 'DENY', 'referrer-policy': 'no-referrer',
            'x-content-type-options': 'nosniff', 'permissions-policy': 'camera=(), microphone=(), geolocation=()',
            'content-security-policy': ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                        "connect-src 'self' https://agentconcierge.biz; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")})

    @router.get('/admin/next/assets/{path:path}', include_in_schema=False)
    def next_asset(path: str):
        target = (ASSETS / path).resolve()
        if not _ASSET.fullmatch(path) or ASSETS not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target, media_type=_TYPES[target.suffix], headers={
            'cache-control': 'no-cache', 'x-content-type-options': 'nosniff'})

    @router.get('/admin/api/v2/home/bootstrap')
    def bootstrap(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        force = request.headers.get('x-admin-refresh') == '1'
        home = cache['home'].get('overview', lambda: {**overview(), 'captured_at': time.time()}, force=force)
        try:
            gateway = cache['gateway'].get(24, lambda: gateway_data(24), force=force)
        except Exception:
            gateway = {'available': False, 'hours': 24, 'captured_at': time.time()}
        if user['role'] == 'viewer':
            from .gateway.admin_policy import aggregate_overview
            home = aggregate_overview(home)
            gateway = {**gateway, 'agents': []}
        return respond({'me': {key: user.get(key) for key in ('username', 'role', 'name')},
                        'overview': home, 'gateway': gateway, 'alerts': alerts(home, gateway),
                        'legacy': '/admin/ui', 'captured_at': time.time()}, request)

    @router.get('/admin/api/v2/gateway/summary')
    def gateway_summary(request: Request, hours: int = 24):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if hours not in HOURS:
            raise HTTPException(400, 'hours는 1, 6, 24, 168 중 하나입니다.')
        try:
            value = cache['gateway'].get(hours, lambda: gateway_data(hours), force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '게이트웨이 지표를 지금 읽을 수 없습니다.', headers={'Retry-After': '5'}) from None
        if user['role'] == 'viewer':
            value = {**value, 'agents': []}
        return respond(value, request)

    @router.get('/admin/api/v2/public/search-quality')
    def search_quality(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        from .search_quality import dashboard
        return respond(dashboard(store), request)

    @router.get('/admin/api/v2/system/storage')
    def system_storage(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        try:
            value = cache['storage'].get('storage', storage_data, force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '저장소 통계를 지금 읽을 수 없습니다.', headers={'Retry-After': '5'}) from None
        return respond(value, request)

    @router.get('/admin/api/v2/catalog/agents/{rid}/daily')
    def agent_daily(rid: int, request: Request, days: int = 30):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if not 0 < rid < 2 ** 62 or days not in (7, 30, 90):
            raise HTTPException(400, '조회 조건을 확인하세요.')
        if summaries is None or not summaries.ready():
            return respond({'available': False, 'days': [], 'captured_at': time.time()}, request)
        return respond({'available': True, 'days': summaries.agent(rid, days), 'captured_at': time.time()}, request)

    @router.get('/admin/api/v2/system/summaries')
    def summary_span(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if summaries is None or not summaries.ready():
            return respond({'available': False, 'captured_at': time.time()}, request)
        return respond({'available': True, 'health_daily': summaries.span(), 'captured_at': time.time()}, request)

    @router.get('/admin/api/v2/system/retention/policy')
    def retention_policy(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        if retention is None or not retention.ready():
            return respond({'available': False, 'captured_at': time.time()}, request)
        return respond({'available': True, **retention.status(), 'captured_at': time.time()}, request)

    @router.post('/admin/api/v2/system/retention/policy')
    async def retention_policy_request(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin')
        if retention is None or log_op is None:
            raise HTTPException(404)
        body = await body_of(request)
        request.state.audit_reason = reason_text(body.get('reason'))
        payload = {key: body.get(key) for key in ('table', 'days', 'backup_confirmed')}
        from .workspace_admin_retention import validate
        try:
            validate(payload)
        except ValueError as exc:
            raise HTTPException(400, '보존 대상·기간(최소값 이상)·백업 확인을 확인하세요.') from exc
        if payload['days'] is not None and retention.ready() and not retention.indexed(payload['table']):
            raise HTTPException(409, '이 테이블은 시간 인덱스가 먼저 필요합니다. 운영자가 scripts.admin_console_indexes --apply를 실행하세요.')
        # Changing retention, including deletion, is always a reviewed command (design 4.3).
        review = open_review(user, 'retention_policy', payload['table'], payload, request.state.audit_reason)
        log_op(request, 'REVIEWED_REQUEST', '보존 기간 변경 요청', target=review['id'],
               details={'kind': 'retention_policy', 'table': payload['table'], 'days': payload['days']})
        return JSONResponse({'review': review, 'invalidate': ['reviews']}, status_code=202)

    # Customer requests from the public footer (design 13.3 item 4): inquiries, privacy and cancellations.
    # Bodies are customer content, so operators and viewers stay out (design 4.2).
    REQUEST_LISTS = {'inquiries': 'list_customer_inquiries', 'privacy': 'list_privacy_requests',
                     'cancellations': 'list_cancellation_requests'}
    REQUEST_STATUSES = {'inquiries': ('pending', 'in_progress', 'resolved', 'archived'),
                        'privacy': ('received', 'pending_verification', 'processing', 'completed', 'declined')}

    @router.get('/admin/api/v2/requests/summary')
    def requests_summary(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        return respond({**store.get_customer_requests_summary(), 'captured_at': time.time()}, request)

    @router.get('/admin/api/v2/requests/{kind}')
    def requests_list(kind: str, request: Request, status: str = '', q: str = '', offset: int = 0, cursor: str | None = None, limit: int = 50):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        if kind not in REQUEST_LISTS or len(q) > 120 or not 0 <= offset <= 100000 or not 1 <= limit <= 200 or (offset and cursor) \
                or (status and status not in REQUEST_STATUSES.get(kind, (status,))):
            raise HTTPException(400, '조회 조건을 확인하세요.')
        if offset:
            found, total = getattr(store, REQUEST_LISTS[kind])(status=status or None, search=' '.join(q.split()) or None, limit=limit, offset=offset)
            next_cursor = None  # Compatibility only; new clients use the stable keyset cursor.
        else:
            from .admin_completion import request_page
            found,total,next_cursor=request_page(reader,kind,status,' '.join(q.split()),cursor,limit)
        hidden = ('ip', 'user_agent', 'visitor_token', 'visitor_token_hash')  # network identifiers stay out of the console
        items = [{k: v for k, v in row.items() if k not in hidden} for row in found]
        return respond({'items': items, 'total': total, 'next_cursor':next_cursor,'offset': offset, 'captured_at': time.time()}, request)

    @router.post('/admin/api/v2/requests/{kind}/{identity}')
    async def requests_update(kind: str, identity: str, request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        if kind not in REQUEST_STATUSES or log_op is None or not re.fullmatch(r'[A-Za-z0-9_-]{4,120}', identity):
            raise HTTPException(404)
        body = await body_of(request, limit=12000)
        request.state.audit_reason = reason_text(body.get('reason'))
        status = body.get('status')
        if status not in REQUEST_STATUSES[kind]:
            raise HTTPException(400, '처리 상태를 확인하세요.')
        if kind == 'inquiries':
            if set(body) - {'status', 'response', 'reason'}:
                raise HTTPException(400, '요청 형식을 확인하세요.')
            response = body.get('response')
            if response is not None and (not isinstance(response, str) or not 1 <= len(response.strip()) <= 4000):
                raise HTTPException(400, '답변은 1~4000자입니다.')
            if not store.update_customer_inquiry(identity, status=status, admin_response=response, resolved_by=user['username']):
                raise HTTPException(404, '문의를 찾을 수 없습니다.')
            log_op(request, 'INQUIRY_UPDATE', '고객 문의 처리', target=identity, details={'status': status, 'responded': response is not None})
        else:
            if set(body) - {'status', 'notes', 'proof_hash', 'reason'}:
                raise HTTPException(400, '요청 형식을 확인하세요.')
            try:
                found = store.update_privacy_request(identity, status=status, notes=body.get('notes'), proof_hash=body.get('proof_hash'))
            except ValueError as exc:
                raise HTTPException(400, '완료 처리에는 10자 이상의 검토 메모와 근거 SHA-256이 필요합니다. 완료된 요청은 되돌릴 수 없습니다.') from exc
            if not found:
                raise HTTPException(404, '개인정보 요청을 찾을 수 없습니다.')
            log_op(request, 'PRIVACY_UPDATE', '개인정보 요청 처리', target=identity, details={'status': status, 'proof': bool(body.get('proof_hash'))})
        return respond({'ok': True, 'status': status, 'invalidate': ['requests']})

    @router.get('/admin/api/v2/system/activity')
    def system_activity(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin')  # statement shapes stay with the highest role
        try:
            value = cache['activity'].get('activity', activity_data, force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '데이터베이스 활동을 지금 읽을 수 없습니다.', headers={'Retry-After': '5'}) from None
        return respond(value, request)

    def retention_data():
        now = time.time()
        if not postgres():
            return {'available': False, 'tables': [], 'captured_at': now}
        found = []
        for table, column in RETENTION:
            try:
                row = native('SELECT MIN(%s) AS oldest, MAX(%s) AS newest, COUNT(*) FILTER (WHERE %s > %%s) AS last_24h FROM %s'
                             % (column, column, column, table), (now - 86400,))[0]
            except Exception:
                row = {'oldest': None, 'newest': None, 'last_24h': None}
            found.append({'table': table, **row})
        return {'available': True, 'tables': found, 'captured_at': now}

    @router.get('/admin/api/v2/system/retention')
    def system_retention(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        try:
            value = cache['retention'].get('retention', retention_data, force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '보존 현황을 지금 읽을 수 없습니다.', headers={'Retry-After': '5'}) from None
        return respond(value, request)

    @router.get('/admin/api/v2/public/summary')
    def public_service_summary(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if public_summary is None:
            raise HTTPException(503, '공개 서비스 집계를 준비하지 못했습니다.')
        try:
            value = cache['public'].get('summary', public_summary,
                                       force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '공개 서비스 집계를 지금 읽을 수 없습니다.') from None
        return respond(value, request)

    @router.get('/admin/api/v2/catalog/agents')
    def catalog_agents(request: Request, q: str = '', kind: str = '', status: str = '', cursor: int | None = None, limit: int = 50, format: str = 'json'):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if format not in ('json','csv'):
            raise HTTPException(400,'지원하지 않는 내보내기 형식입니다.')
        if format == 'csv':
            require(user,'superadmin','admin')
        if (kind and kind not in KINDS) or (status and status not in STATUSES) or not 1 <= limit <= 200 or len(q) > 120 \
                or (cursor is not None and not 0 < cursor < 2 ** 62):
            raise HTTPException(400, '검색 조건을 확인하세요.')
        q = ' '.join(q.split())
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' if q else None
        filters = (kind or None, kind or None, status or None, status or None, q or None, pattern, pattern)
        if postgres():
            items = native(_CATALOG_PG, (*filters, cursor, cursor, limit + 1))
            total = native(_CATALOG_COUNT_PG, filters)[0]['n'] if cursor is None else None
        else:
            with reader() as db:
                items = rows(db.execute(_CATALOG_SQLITE, (*filters, cursor, cursor, limit + 1)))
                total = rows(db.execute(_CATALOG_COUNT_SQLITE, filters))[0]['n'] if cursor is None else None
        more = len(items) > limit
        items = items[:limit]
        if format == 'csv':
            from .admin_completion import csv_bytes
            log_op(request,'CATALOG_EXPORT','현재 카탈로그 페이지 내보내기',details={'rows':len(items)})
            return Response(csv_bytes(items),media_type='text/csv; charset=utf-8',headers={
                'Content-Disposition':'attachment; filename="agent-catalog-page.csv"','Cache-Control':'no-store'})
        return respond({'items': items, 'next_cursor': items[-1]['id'] if more and items else None,
                        'total': total, 'captured_at': time.time()}, request)

    @router.post('/admin/api/v2/catalog/agents/{rid}/actions')
    async def agent_action(rid: int, request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin','operator')
        body = await body_of(request)
        action = body.get('action')
        if user['role']=='operator' and action!='check':
            raise HTTPException(403,'운영자는 단일 재검사만 요청할 수 있습니다.')
        if action not in ('activate', 'deactivate', 'check') or action not in agent_actions or not 0 < rid < 2 ** 62:
            raise HTTPException(400, '지원하지 않는 작업입니다.')
        reason = reason_text(body.get('reason'))
        if action != 'check':
            if type(body.get('expected_active')) is not bool:
                raise HTTPException(400, '현재 상태를 함께 보내야 합니다.')
            current = store.resource(rid)
            if current is None:
                raise HTTPException(404, '없는 에이전트입니다.')
            if bool(current.get('active')) != body['expected_active']:
                raise HTTPException(409, '다른 관리자가 이미 상태를 바꿨습니다. 새로 읽은 뒤 다시 확인하세요.')
        request.state.audit_reason = reason
        log_op(request,'AGENT_ACTION_INTENT','에이전트 운영 작업 의도',target='agent:'+str(rid),status='REQUESTED',details={'action':action})
        result = agent_actions[action](rid, request)
        for name in ('home', 'gateway'):
            cache[name].invalidate()
        return respond({'result': result, 'invalidate': ['catalog:agents', 'catalog:agent:%d' % rid, 'home']})

    @router.post('/admin/api/v2/catalog/collector/actions')
    async def collector_action(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin','operator')
        body = await body_of(request)
        action = body.get('action')
        if action not in ('pause','resume') or action not in collector_actions:
            raise HTTPException(400, '지원하지 않는 작업입니다.')
        request.state.audit_reason = reason_text(body.get('reason'))
        log_op(request,'COLLECTOR_ACTION_INTENT','수집기 운영 작업 의도',status='REQUESTED',details={'action':action})
        result = collector_actions[action](request)
        cache['home'].invalidate()
        return respond({'result': result, 'invalidate': ['home']})

    @router.get('/admin/api/v2/home/changes')
    def changes(request: Request, since: int = 0):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if audit is None:
            return respond({'version': since, 'tags': [], 'captured_at': time.time()})
        with reader() as db:
            recent = audit(db, 100)
        version = max((row['id'] for row in recent), default=since)
        # since=0 also returns tags so a first audit event cannot be missed.
        tags = sorted({tag for row in recent if row['id'] > since for tag in tags_for(row['action'], row.get('target'))})
        if since and recent and since < min(row['id'] for row in recent) - 1:
            tags = sorted(set(tags) | {'home', 'catalog:agents', 'gateway:controls', 'customers', 'security', 'system:storage'})
        return respond({'version': version, 'tags': tags, 'captured_at': time.time()})

    @router.get('/admin/api/v2/gateway/controls')
    def gateway_controls(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin')
        if not controls:
            raise HTTPException(404)
        execution, fallback = controls['execution'](), controls['fallback']()
        keys = ('invoke_enabled', 'workflow_enabled', 'delivery_enabled', 'revision', 'updated')
        return respond({'execution': {k: execution[k] for k in keys if k in execution}, 'fallback': fallback,
                        'captured_at': time.time()}, request)

    @router.post('/admin/api/v2/gateway/controls')
    async def gateway_controls_save(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin')
        if not controls or log_op is None:
            raise HTTPException(404)
        body = await body_of(request)
        target, state = body.get('target'), body.get('state')
        request.state.audit_reason = reason_text(body.get('reason'))
        keys = ('invoke_enabled', 'workflow_enabled', 'delivery_enabled')
        try:
            if target == 'execution':
                if not isinstance(state, dict) or set(state) != {*keys, 'revision'}:
                    raise HTTPException(400, '실행 제어 값을 모두 보내야 합니다.')
                current = controls['execution']()
                if any(state[k] and not current.get(k) for k in keys):
                    # Releasing a kill switch is a reviewed command (design 4.3); stopping stays immediate.
                    review = open_review(user, 'execution_release', 'execution', state, request.state.audit_reason)
                    log_op(request, 'REVIEWED_REQUEST', '실행 킬스위치 해제 요청', target=review['id'],
                           details={'kind': 'execution_release', 'expires': review['expires']})
                    return JSONResponse({'review': review, 'invalidate': ['reviews']}, status_code=202)
                result = controls['save_execution'](state, user['user_id'])
                log_op(request, 'execution_controls', '실행·전달 제어 변경', details={k: result[k] for k in (*keys, 'revision')})
            elif target == 'fallback':
                result = controls['save_fallback'](state, user['user_id'])
                log_op(request, 'fallback_control', 'Informational fallback control updated',
                       details={'revision': result['revision'], 'enabled': result['enabled']})
            else:
                raise HTTPException(400, '지원하지 않는 제어입니다.')
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        cache['home'].invalidate()
        return respond({'result': result, 'invalidate': ['gateway:controls', 'home']})

    # Reviewed commands (design 4.3): request, then a different superadmin applies within 15 minutes.
    from .admin_risk import REVIEW_TTL
    from .workspace_admin_reviewed import ReviewConflict, ReviewDenied, ReviewUnavailable

    def review_call(method, *args):
        if reviews is None:
            raise HTTPException(404)
        try:
            return method(*args)
        except ReviewUnavailable:
            raise HTTPException(409, '위험 작업 승인 저장소가 준비되지 않았습니다. 운영자가 승인 저장소 마이그레이션을 먼저 실행해야 합니다.') from None
        except ReviewDenied:
            raise HTTPException(403, '이 요청을 검토할 수 없습니다. 요청자와 다른 최고관리자가 적용해야 합니다.') from None
        except ReviewConflict:
            raise HTTPException(409, '이미 처리됐거나 만료됐거나 같은 요청이 진행 중입니다. 목록을 새로 확인하세요.') from None

    def open_review(user, kind, target, payload, reason):
        return review_call(reviews.request, user['user_id'], kind, target, payload, reason)

    def session_ref(request):
        from .gateway.admin_auth import session_reference
        return session_reference((request.headers.get('authorization') or '')[7:].strip())

    @router.get('/admin/api/v2/reviews')
    def review_list(request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        if reviews is None:
            raise HTTPException(404)
        available = reviews.ready()  # a missing migration is a state to show, not a failed read
        items = review_call(reviews.list, 50) if available else []
        if user['role'] != 'superadmin':
            items = [item for item in items if item['kind'] != 'finance_change']
        return respond({'available': available, 'items': items, 'me': user['user_id'], 'review_ttl': REVIEW_TTL,
                        'can_approve': user['role'] == 'superadmin', 'captured_at': time.time()}, request)

    @router.get('/admin/api/v2/reviews/{identity}')
    def review_detail(identity: str, request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin', 'admin')
        if not _REVIEW_ID.fullmatch(identity):
            raise HTTPException(404)
        item = review_call(reviews.get, identity)
        if item['kind'] == 'finance_change':
            require(user, 'superadmin')
        return respond({'item': item, 'captured_at': time.time()}, request)

    @router.post('/admin/api/v2/reviews/{identity}/{action}')
    async def review_action(identity: str, action: str, request: Request):
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        if not _REVIEW_ID.fullmatch(identity) or action not in ('approve', 'cancel') or log_op is None:
            raise HTTPException(404)
        body = await body_of(request)
        revision, acknowledged = body.get('revision'), body.get('acknowledge', False)
        if type(revision) is not int or type(acknowledged) is not bool or set(body) - {'revision', 'reason', 'acknowledge'}:
            raise HTTPException(400, '요청 형식을 확인하세요.')
        request.state.audit_reason = reason_text(body.get('reason'))
        if review_call(reviews.get, identity)['kind'] == 'finance_change':
            require(user, 'superadmin')
        if action == 'approve':
            require(user, 'superadmin')
            from starlette.concurrency import run_in_threadpool
            item = await run_in_threadpool(review_call, reviews.approve, user['user_id'], session_ref(request), identity, revision,
                                           request.state.audit_reason, acknowledged)
            log_op(request, {'applied':'REVIEWED_APPLY','unknown':'REVIEWED_UNKNOWN'}.get(item['status'],'REVIEWED_FAILED'),
                   {'applied':'승인 명령 적용','unknown':'승인 명령 결과 확인 필요'}.get(item['status'],'승인 명령 적용 실패'), target=identity,
                   details={'kind': item['kind'], 'outcome':item['status'], 'single_approver': item['same_person_review']})
        else:
            require(user, 'superadmin', 'admin')
            item = review_call(reviews.cancel, user['user_id'], user['role'], identity, revision, request.state.audit_reason)
            log_op(request, 'REVIEWED_CANCEL', '승인 명령 철회', target=identity, details={'kind': item['kind']})
        cache['home'].invalidate()
        if item['kind']=='public_service_change':
            cache['public'].invalidate()
        return respond({'item': item, 'invalidate': ['reviews', 'gateway:controls', 'public', 'security', 'home']})

    # Finance remains in one workbench; sensitive reads never enter the shared cache.
    from .workspace_admin_events import signature as finance_sign
    import secrets as finance_secrets

    def finance_staff(request):
        from .workflow_publication_service import same_origin
        if not same_origin(request):
            raise HTTPException(403, '동일한 관리자 화면에서 요청하세요.')
        user = staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        require(user, 'superadmin')
        if finance is None:
            raise HTTPException(404)
        return user

    @router.get('/admin/api/v2/finance')
    def finance_read(request: Request, mode: str='transactions', status: str='', q: str='', offset: int=0,
                     since: float=0, until: float=0):
        user = finance_staff(request)
        if len(q)>120 or not 0<=offset<=100000 or not math.isfinite(since) or not math.isfinite(until) or min(since,until)<0 or (until and since>until):
            raise HTTPException(400, '조회 조건을 확인하세요.')
        try:
            data = finance.read(mode=mode,status=status,query=q,offset=offset,since=since,until=until)
        except ValueError as error:
            raise HTTPException(400,str(error)) from None
        available = reviews is not None and reviews.ready()
        # One bounded query, with integrity failures projected as blocked records.
        data['reviews'] = review_call(reviews.list_for,'finance_change',50) if available else []
        data.update(review_available=available,me=user['user_id'])
        return respond(data)

    @router.get('/admin/api/v2/finance/requests/{identity}/evidence')
    def finance_evidence(identity: str, request: Request):
        finance_staff(request)
        if not _REVIEW_ID.fullmatch(identity):
            raise HTTPException(404)
        item = review_call(reviews.get,identity)
        if item['kind'] != 'finance_change':
            raise HTTPException(404)
        return respond(finance.evidence(item['payload']))

    @router.post('/admin/api/v2/finance/quote')
    async def finance_quote(request: Request):
        finance_staff(request)
        body = await body_of(request)
        body['reason'] = reason_text(body.get('reason'))
        if reviews is None or not reviews.ready():
            raise HTTPException(409, '승인 저장소가 준비되지 않아 변경할 수 없습니다. 조회는 가능합니다.')
        from starlette.concurrency import run_in_threadpool
        try:
            quote = await run_in_threadpool(finance.quote,body)
        except ValueError as error:
            raise HTTPException(400,str(error)) from None
        return respond({'quote':quote,'signature':finance_sign(store._workspace_admin_event_key,quote)})

    @router.post('/admin/api/v2/finance/requests')
    async def finance_request(request: Request):
        user = finance_staff(request)
        body = await body_of(request,limit=24000)
        if set(body)!={'quote','signature'} or type(body['quote']) is not dict or type(body['signature']) is not str:
            raise HTTPException(400,'검토한 작업을 선택하세요.')
        if reviews is None or not reviews.ready():
            raise HTTPException(409,'승인 저장소가 준비되지 않았습니다.')
        quote = body['quote']
        try:
            valid = finance_secrets.compare_digest(finance_sign(store._workspace_admin_event_key,quote),body['signature'])
        except (ValueError,TypeError,OverflowError):
            valid = False
        if not valid or quote.get('expires',0)<time.time():
            raise HTTPException(409,'검토 내용이 변경되었거나 만료됐습니다. 다시 검토하세요.')
        request.state.audit_reason = reason_text(quote.get('reason'))
        # The same account/action may have only one open request. A failed transport
        # must be resolved by reading the request queue, never by replaying a write.
        target = 'finance:' + quote['action'] + ':' + (quote.get('account_id') or 'overdue-holds')
        item = review_call(reviews.request,user['user_id'],'finance_change',target,quote,request.state.audit_reason,quote['request_id'])
        if log_op:
            log_op(request,'REVIEWED_REQUEST','금융 장부 변경 검토 요청',target=item['id'],details={'kind':'finance_change'})
        return JSONResponse({'review':item},status_code=202,headers={'Cache-Control':'private, no-store'})

    # Retention preview (read only): rows that candidate retention periods would remove. Nothing is deleted.
    PREVIEW = (('health_checks', 'at', '', '상태 확인 원본'),
               ('legacy_vector_jobs', 'finished', " AND status IN ('indexed','failed','superseded')", '완료된 벡터 작업'),
               ('platform_observation_events', 'created', '', '실행 관측 이벤트'),
               ('security_events', 'at', '', '보안 이벤트'),
               ('crawl_runs', 'at', '', '수집 실행 기록'))
    DAYS = (3, 7, 14, 30)

    def preview_data():
        now = time.time()
        if not postgres():
            return {'available': False, 'tables': [], 'days': list(DAYS), 'captured_at': now}
        sizes = {row['name']: row for row in native(_STORAGE_PG)}
        found = []
        for table, column, extra, label in PREVIEW:
            counts = ', '.join('COUNT(*) FILTER (WHERE %s < %%s%s) AS d%d' % (column, extra, days) for days in DAYS)
            try:
                row = native('SELECT COUNT(*) AS total, %s FROM %s' % (counts, table), tuple(now - days * 86400 for days in DAYS))[0]
            except Exception:
                row = None
            if row is None:
                found.append({'table': table, 'label': label, 'available': False, 'rows': None,
                              'bytes': sizes.get(table, {}).get('bytes'),
                              'remove': {str(days): {'rows': None, 'bytes': None} for days in DAYS}})
                continue
            total = row.pop('total') or 0
            size = sizes.get(table, {}).get('bytes')
            found.append({'table': table, 'label': label, 'available': True, 'rows': total, 'bytes': size,
                          'remove': {str(days): {'rows': row['d%d' % days],
                                                 'bytes': round(size * row['d%d' % days] / total) if size and total else None} for days in DAYS}})
        return {'available': True, 'complete': all(row['available'] for row in found),
                'tables': found, 'days': list(DAYS), 'captured_at': now}

    @router.get('/admin/api/v2/system/retention/preview')
    def retention_preview(request: Request):
        staff(request, request.headers.get('authorization'), request.headers.get('x-dashboard'))
        try:
            value = cache['retention'].get('preview', preview_data, force=request.headers.get('x-admin-refresh') == '1')
        except Exception:
            raise HTTPException(503, '보존 미리보기를 지금 계산할 수 없습니다.', headers={'Retry-After': '5'}) from None
        return respond(value, request)
