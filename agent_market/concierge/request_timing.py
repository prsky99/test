"""Server-Timing stages for public recommendation requests (2026-11-10).

The user target is measured from outside (scripts/user_slo.py), so a slow answer must be split into
network and server time, and server time into its stages. This turns on the opt-in retrieval
measurements for /mcp, /a2a, /chat, /agents/best, /api/explore, /api/agents and /api/feed and adds them to the Server-Timing header.
Nothing about the task, the visitor or the result is recorded.
"""
import time

from starlette.datastructures import MutableHeaders

from .retrieval_metrics import capture, gc_stages, gc_total_ms

# /api/agents and /api/feed (11-12 PM): the 13:04 full check saw 18.9 s and 11.4 s there with no server stages.
# /api/agent/v1/discover (11-14 PM 16:2x): 2.77 s in the full check with no server stages (F07).
# Always sent whatever their size (PM 11-18): the slowest 24 stages leave out 0 ms markers and small counts, so the
# recommendation head start outcome and the contract read counts could not be seen in public samples.
ALWAYS_STAGES = ('prefetch_hit', 'prefetch_miss', 'prefetch_skip', 'prefetch_unused', 'prefetch_run')
ALWAYS_COUNTS = ('resource_read_calls', 'resource_read_rows')
PATHS = ('/mcp', '/a2a', '/chat', '/agents/best', '/api/explore', '/api/agents', '/api/feed', '/api/agent/v1/discover')


def timed_path(path):
    return any(path == prefix or path.startswith(prefix + '/') for prefix in PATHS)


class RequestTiming:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not timed_path(scope.get('path') or ''):
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        gc_since = gc_total_ms()
        with capture() as values:
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
                    kept = {name for name, _ in stages}
                    stages += [(name, values['stages_ms'][name]) for name in ALWAYS_STAGES
                               if name in values['stages_ms'] and name not in kept]
                    stages += [(name, values['counts'][name]) for name in ALWAYS_COUNTS if name in values['counts']]
                    headers = MutableHeaders(scope=message)
                    timing = ', '.join(f'{name};dur={value:.0f}' for name, value in stages)
                    headers['Server-Timing'] = (headers['Server-Timing'] + ', ' + timing) if 'server-timing' in headers else timing
                await send(message)
            await self.app(scope, receive, deliver)
