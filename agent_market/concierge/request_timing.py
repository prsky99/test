"""Server-Timing stages for public recommendation requests (2026-11-10).

The user target is measured from outside (scripts/user_slo.py), so a slow answer must be split into
network and server time, and server time into its stages. This turns on the opt-in retrieval
measurements for /mcp, /a2a, /chat, /agents/best, /api/explore, /api/agents and /api/feed and adds them to the Server-Timing header.
Nothing about the task, the visitor or the result is recorded.
"""
import asyncio
import collections
import json
import os
import queue
import threading
import time
from pathlib import Path

from starlette.datastructures import MutableHeaders

from .retrieval_metrics import capture, gc_stages, gc_total_ms, request_memo

# /api/agents and /api/feed (11-12 PM): the 13:04 full check saw 18.9 s and 11.4 s there with no server stages.
# /api/agent/v1/discover (11-14 PM 16:2x): 2.77 s in the full check with no server stages (F07).
PATHS = ('/mcp', '/a2a', '/chat', '/agents/best', '/api/explore', '/api/agents', '/api/feed', '/api/agent/v1/discover')


def timed_path(path):
    return any(path == prefix or path.startswith(prefix + '/') for prefix in PATHS)


LAG_TICK = 0.1         # seconds the loop-lag watch sleeps between wake-ups
LAG_WINDOW = 60.0      # seconds of wake-up delays it keeps
_lag = {'task': None, 'samples': collections.deque()}


async def _watch_loop_lag():
    """How late the event loop wakes a 0.1 s sleep: a blocking call in the loop shows here (PM 11-16 15:46)."""
    samples = _lag['samples']
    while True:
        began = time.perf_counter()
        await asyncio.sleep(LAG_TICK)
        now = time.perf_counter()
        samples.append((now, max(0.0, (now - began - LAG_TICK) * 1000)))
        while samples and now - samples[0][0] > LAG_WINDOW:
            samples.popleft()


def loop_lag_ms():
    """The worst wake-up delay of the last minute in milliseconds, starting the watch on first use."""
    task = _lag['task']
    if task is None or task.done():
        try:
            _lag['task'] = asyncio.get_running_loop().create_task(_watch_loop_lag())
        except RuntimeError:
            return None
    return max((lag for _, lag in _lag['samples']), default=None)


def queued_ms(scope, now_epoch=None):
    """Milliseconds since the proxy stamped X-Request-Start (t=<unix ms>), or None without the stamp."""
    for name, value in scope.get('headers') or ():
        if name == b'x-request-start':
            try:
                stamp = float(value.decode('latin-1').strip().removeprefix('t='))
            except ValueError:
                return None
            waited = (time.time() if now_epoch is None else now_epoch) * 1000 - stamp
            return waited if 0 <= waited < 60000 else None
    return None


# One line per timed request (운영·SRE, PM 11-16): kind of path, status, server time, every stage, loop_lag and queue,
# a QA mark; never the query, address or user agent. The request only puts the line on a bounded queue; a background
# thread appends it to <logs>/ops/request-timing/YYYY-MM-DD.jsonl. Without LOG_DIR (tests, ad-hoc runs) nothing is kept.
_LINES = queue.Queue(maxsize=5000)
_writer = {'thread': None}


def log_directory():
    value = os.environ.get('LOG_DIR')
    return Path(value).parent / 'ops' / 'request-timing' if value else None


def path_kind(path):
    for prefix in PATHS:
        if path == prefix or path.startswith(prefix + '/'):
            return prefix.strip('/').replace('/', '_')
    return 'other'


def _write_lines(folder):
    while True:
        line = _LINES.get()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            day = time.strftime('%Y-%m-%d', time.localtime(line['at']))
            with open(folder / f'{day}.jsonl', 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(line, separators=(',', ':')) + '\n')
        except OSError:
            pass                                  # a full disk never slows or fails a request


def record_line(line):
    folder = log_directory()
    if folder is None:
        return False
    if _writer['thread'] is None or not _writer['thread'].is_alive():
        _writer['thread'] = threading.Thread(target=_write_lines, args=(folder,), name='request-timing-log', daemon=True)
        _writer['thread'].start()
    try:
        _LINES.put_nowait(line)
        return True
    except queue.Full:
        return False


class RequestTiming:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not timed_path(scope.get('path') or ''):
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        gc_since = gc_total_ms()
        before = {'queue': queued_ms(scope), 'loop_lag': loop_lag_ms()}
        with capture() as values, request_memo():
            values['started'] = started
            async def deliver(message):
                if message['type'] == 'http.response.start':
                    now = time.perf_counter()
                    stages = [('server', (now - started) * 1000)]
                    steps = {}
                    marks = values.get('marks') or []
                    for (name, at), following in zip(marks, marks[1:] + [(None, now)]):
                        steps['step_' + name] = steps.get('step_' + name, 0) + (following[1] - at) * 1000
                    measured = sorted({**values['stages_ms'], **steps, **gc_stages(values, gc_since)}.items(),
                                      key=lambda item: -item[1])
                    stages += measured[:24]
                    stages += [(name, value) for name, value in before.items() if value is not None]
                    qa = any(name == b'x-agentcon-qa' for name, _ in scope.get('headers') or ())
                    record_line({'at': round(time.time(), 3), 'path': path_kind(scope.get('path') or ''),
                                 'status': message.get('status'), 'server_ms': round(stages[0][1], 1), 'qa': qa,
                                 'stages': {name: round(value, 1) for name, value in
                                            [*measured, *[(n, v) for n, v in before.items() if v is not None]]}})
                    headers = MutableHeaders(scope=message)
                    timing = ', '.join(f'{name};dur={value:.0f}' for name, value in stages)
                    headers['Server-Timing'] = (headers['Server-Timing'] + ', ' + timing) if 'server-timing' in headers else timing
                await send(message)
            await self.app(scope, receive, deliver)
