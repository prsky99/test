"""One-click "Worked / Didn't work" feedback from public pages and Explore (11-10 user request).

POST /api/feedback takes {resource_id, worked, source} as JSON or as a plain HTML form (the agent pages
use a form, so it works without scripts) and stores one row in the existing feedback table with the
registered INSERT text (recovery.report_outcome uses the same statement). Nothing about the sender is
stored: no IP address, user agent or account. Abuse is limited in memory per process with a daily random
salt: each client may send 20 reports an hour and one per agent a day, and each agent takes at most 300
reports a day. The MCP `report` tool goes through the same limiter with MCP_PER_HOUR and no once-per-agent
rule, because an agent may report a success and later a failure (which returns alternatives).

Daily aggregation (jobs, with the task snapshot) reads the registered per-resource statistics for the
agents with evidence and writes public-pages/feedback-stats.json for the agent pages and for ranking work.
"""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

SOURCES = ('explore', 'agent_page', 'task_page', 'chat', 'api')
REASONS = ('matched_task', 'connection_failed', 'unrelated_result', 'authorization_required', 'incomplete_result', 'other')
PER_CLIENT_HOUR = 20
PER_RESOURCE_DAY = 300
MCP_PER_HOUR = 120
STATS_NAME = 'feedback-stats.json'
INSERT = 'INSERT INTO feedback (need_id,resource_id,success,rating,created) VALUES (?,?,?,?,?)'  # registered text


class Limiter:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.day = None
        self.salt = b''
        self.recent = {}      # client digest -> deque of timestamps
        self.pairs = set()    # (client digest, resource id) today
        self.per_resource = {}

    def _client(self, ip):
        return hmac.new(self.salt, str(ip or '').encode(), hashlib.sha256).hexdigest()[:16]

    def allow(self, ip, resource_id, per_hour=PER_CLIENT_HOUR, once_per_agent=True):
        now = self.clock()
        day = int(now // 86400)
        with self.lock:
            if day != self.day:
                self.day, self.salt = day, secrets.token_bytes(16)
                self.recent, self.pairs, self.per_resource = {}, set(), {}
            client = self._client(ip)
            window = self.recent.setdefault(client, deque())
            while window and now - window[0] > 3600:
                window.popleft()
            if len(window) >= per_hour or once_per_agent and (client, resource_id) in self.pairs \
                    or self.per_resource.get(resource_id, 0) >= PER_RESOURCE_DAY:
                return False
            window.append(now)
            self.pairs.add((client, resource_id))
            self.per_resource[resource_id] = self.per_resource.get(resource_id, 0) + 1
            if len(self.recent) > 50000:  # bounded memory under a flood
                self.recent.clear()
            return True


LIMITER = Limiter()


def parse(body):
    """(resource_id, worked, source, reason) or ValueError."""
    if not isinstance(body, dict):
        raise ValueError('Send resource_id and worked.')
    try:
        rid = int(str(body.get('resource_id', '')).strip())
    except ValueError:
        raise ValueError('resource_id must be a positive integer.') from None
    if not 0 < rid < 2**31:
        raise ValueError('resource_id must be a positive integer.')
    worked = body.get('worked')
    if isinstance(worked, str):
        worked = {'1': True, 'true': True, 'yes': True, '0': False, 'false': False, 'no': False}.get(worked.strip().lower())
    if type(worked) is not bool:
        raise ValueError('worked must be true or false.')
    source = body.get('source') or 'api'
    if source not in SOURCES:
        raise ValueError('Choose a documented source.')
    reason = body.get('reason') or None
    if reason is not None and reason not in REASONS:
        raise ValueError('Choose a documented reason.')
    return rid, worked, source, reason


def record(store, rid, worked, source):
    with store.tx() as db:
        db.execute(INSERT, ('web_' + source + '_' + uuid.uuid4().hex[:8], rid, int(worked), 5 if worked else 1, time.time()))


# ---------------------------------------------------------------- daily aggregation (jobs)
def aggregate(store, resource_ids, batch=256):
    """{resource_id: {'reports': n, 'worked': s}} for resources with at least one report."""
    out = {}
    ids = sorted({int(r) for r in resource_ids})
    for start in range(0, len(ids), batch):
        for rid, (n, s, _rating) in store.feedback_stats_many(ids[start:start + batch]).items():
            out[int(rid)] = {'reports': int(n), 'worked': int(s)}
    return out


def write_stats(folder, stats, clock=time.time):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    total = sum(v['reports'] for v in stats.values())
    worked = sum(v['worked'] for v in stats.values())
    value = {'version': 1, 'generated_at': clock(), 'totals': {'reports': total, 'worked': worked, 'agents': len(stats)},
             'resources': {str(k): v for k, v in sorted(stats.items())}}
    handle, temporary = tempfile.mkstemp(dir=folder, prefix='.feedback-stats.')
    with os.fdopen(handle, 'w', encoding='utf-8') as out:
        json.dump(value, out, separators=(',', ':'))
    os.chmod(temporary, 0o644)
    os.replace(temporary, folder / STATS_NAME)
    return value


_stats_cache = {'key': None, 'value': None}
_stats_lock = threading.Lock()


def read_stats(folder):
    """The published aggregate, re-read only when the file changes."""
    if folder is None:
        return None
    path = Path(folder) / STATS_NAME
    try:
        key = path.stat().st_mtime
    except OSError:
        return None
    with _stats_lock:
        if _stats_cache['key'] == key:
            return _stats_cache['value']
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('resources'), dict):
            value = None
    except (OSError, ValueError):
        value = None
    with _stats_lock:
        _stats_cache.update(key=key, value=value)
    return value


def resource_stats(folder, rid):
    value = read_stats(folder)
    entry = (value or {}).get('resources', {}).get(str(rid))
    return entry if isinstance(entry, dict) and isinstance(entry.get('reports'), int) else None


# ---------------------------------------------------------------- HTTP
def feedback_router(front):
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse, RedirectResponse
    from starlette.concurrency import run_in_threadpool
    router = APIRouter()

    @router.post('/api/feedback', include_in_schema=False)
    async def submit(request: Request):
        origin = request.headers.get('origin')
        if origin is not None and urlsplit(origin).netloc != request.headers.get('host', ''):
            return JSONResponse({'error': 'Cross-site reports are not accepted.', 'recorded': False}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        media = request.headers.get('content-type', '')
        form = 'application/x-www-form-urlencoded' in media
        try:
            if form:
                raw = await request.body()
                if len(raw) > 2048:
                    raise ValueError('Report is too large.')
                from urllib.parse import parse_qsl
                body = dict(parse_qsl(raw.decode('utf-8', 'replace'), keep_blank_values=False))
            else:
                raw = await request.body()
                if len(raw) > 2048:
                    raise ValueError('Report is too large.')
                body = json.loads(raw or b'{}')
            rid, worked, source, _reason = parse(body)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({'error': 'Send resource_id and worked (true or false).', 'recorded': False}, status_code=400,
                                headers={'Cache-Control': 'no-store'})
        if await run_in_threadpool(front.store.resource, rid) is None:
            return JSONResponse({'error': 'Agent not found.', 'recorded': False}, status_code=404, headers={'Cache-Control': 'no-store'})
        allowed = LIMITER.allow(front.security.resolve_ip(request), rid)
        if allowed:
            await run_in_threadpool(record, front.store, rid, worked, source)
        if form:
            return RedirectResponse('/agent/%d/reported?r=%s' % (rid, 'recorded' if allowed else 'limited'), status_code=303,
                                    headers={'Cache-Control': 'no-store'})
        if not allowed:
            return JSONResponse({'error': 'Too many reports from this client. Try again later.', 'recorded': False}, status_code=429,
                                headers={'Cache-Control': 'no-store', 'Retry-After': '3600'})
        return JSONResponse({'recorded': True, 'resource_id': rid, 'worked': worked,
                             'note': 'Thanks. Reports count toward ranking signals; they are not proof that an agent works.'},
                            headers={'Cache-Control': 'no-store'})

    return router
