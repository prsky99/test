"""jobs scheduler step: the daily graph-cap refresh (PM 11-15: in the scheduler, not a hand-made schedule).

After the graph cap (scripts/embeddings_graph_cap.py migrate) new a2a and x402 vectors enter their kind's graph at once
(column default true); a crowded host can then hold more than CAP rows until `refresh` trims it again. This step runs
that refresh once a day, from 05:30 (after the 03:50-05:10 real-task window, outside :55-:10), on a background thread
with one short-lived connection of its own. Before the column exists it does nothing ("no_column"). Each run appends one
line to logs/ops/graph-cap/refresh-<day>.jsonl; a failure is logged and swallowed, never stopping the scheduler.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

FROM_HHMM = 530


def refresh_window(now):
    t = time.localtime(now)
    hhmm = t.tm_hour * 100 + t.tm_min
    return hhmm >= FROM_HHMM and not (t.tm_min >= 55 or t.tm_min < 10)


def project_root():
    return Path(os.environ.get('AGENTCON_PROJECT_ROOT') or Path(__file__).resolve().parents[1])


class GraphCapRefresh:
    def __init__(self, clock=time.time, refresh=None, root=None):
        self.clock, self._refresh, self.root = clock, refresh, root
        self.done_day = None
        self.thread = None
        self.last = None

    def _root(self):
        return Path(self.root) if self.root is not None else project_root()

    def _run_refresh(self):
        if self._refresh is not None:
            return self._refresh()
        from scripts import embeddings_graph_cap as cap
        with cap._connect(str(self._root() / 'gateway-data/postgres18/application.dsn')) as connection:
            return cap.refresh(connection)

    def _work(self, day):
        started = time.monotonic()
        try:
            result = self._run_refresh()
            self.last = {'ok': True, **(result or {})}
        except Exception as exc:
            self.last = {'ok': False, 'error': type(exc).__name__}
            log.warning('graph cap refresh failed: %s', type(exc).__name__)
        self.last['seconds'] = round(time.monotonic() - started, 1)
        try:
            out = self._root() / 'logs/ops/graph-cap'
            out.mkdir(parents=True, exist_ok=True)
            with (out / f'refresh-{day}.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **self.last}) + '\n')
        except OSError:
            pass

    def run_due(self, force=False):
        now = self.clock()
        day = time.strftime('%Y-%m-%d', time.localtime(now))
        if self.thread is not None and self.thread.is_alive():
            return None
        if not force and (self.done_day == day or not refresh_window(now)):
            return None
        self.done_day = day
        self.thread = threading.Thread(target=self._work, args=(day,), name='graph-cap-refresh', daemon=True)
        self.thread.start()
        return {'graph_cap_refresh': 'started'}
