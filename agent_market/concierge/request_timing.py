"""Server-Timing stages for public recommendation requests (2026-11-10).

The user target is measured from outside (scripts/user_slo.py), so a slow answer must be split into
network and server time, and server time into its stages. This turns on the opt-in retrieval
measurements for /mcp, /a2a, /chat, /agents/best and /api/explore and adds them to the Server-Timing header.
Nothing about the task, the visitor or the result is recorded.
"""
import time

from starlette.datastructures import MutableHeaders

from .retrieval_metrics import capture

PATHS = ('/mcp', '/a2a', '/chat', '/agents/best', '/api/explore')


def timed_path(path):
    return any(path == prefix or path.startswith(prefix + '/') for prefix in PATHS)


class RequestTiming:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not timed_path(scope.get('path') or ''):
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        with capture() as values:
            async def deliver(message):
                if message['type'] == 'http.response.start':
                    stages = [('server', (time.perf_counter() - started) * 1000)]
                    stages += sorted(values['stages_ms'].items(), key=lambda item: -item[1])[:8]
                    headers = MutableHeaders(scope=message)
                    timing = ', '.join(f'{name};dur={value:.0f}' for name, value in stages)
                    headers['Server-Timing'] = (headers['Server-Timing'] + ', ' + timing) if 'server-timing' in headers else timing
                await send(message)
            await self.app(scope, receive, deliver)
