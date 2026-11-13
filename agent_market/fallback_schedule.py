"""jobs scheduler steps for the AgentValCon fallback agents (PM 11-14, agent team request).

- FallbackWatchStep: the agents' hourly watch (fallback_agents.watch.FallbackWatch) at :25, outside the measurement
  windows. It reads the agents' own usage lines and snapshot ages and asks GitHub's free /rate_limit once.
- AirportIndexRefresh: the OurAirports index for the airport fallback once a day in :15-:50 (never 03:50-05:10), in a
  background thread so the scheduler never waits for the 12 MB download. Without an index file (not built yet) it
  does nothing: the first build is a deliberate step, like the NVD snapshot (nvd_snapshot_schedule).
Both log and swallow their own failures; a failing step never stops the scheduler.
"""
import logging
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)


class FallbackWatchStep:
    def __init__(self, watch=None):
        self._watch = watch

    def watch(self):
        if self._watch is None:
            from .fallback_agents.watch import FallbackWatch
            self._watch = FallbackWatch()
        return self._watch

    def run_due(self, force=False):
        try:
            watch = self.watch()
            if not force and not watch.due():
                return None
            result = watch.run()
        except Exception as exc:
            log.warning('fallback watch failed: %s', type(exc).__name__)
            return {'fallback_watch': 'failed'}
        if result.get('alerts') or result.get('failing'):
            log.info('fallback watch: %s', result)
        return {'fallback_watch': result}


def airport_window(now):
    local = datetime.fromtimestamp(now)
    hm = local.hour * 100 + local.minute
    return 15 <= local.minute <= 50 and not 350 <= hm <= 510


class AirportIndexRefresh:
    EVERY = 86400

    def __init__(self, clock=time.time, sync=None, path=None):
        self.clock, self._sync, self.path = clock, sync, path
        self.next_run = 0.0
        self.thread = None
        self.last = None

    def _path(self):
        if self.path is not None:
            return self.path
        from .fallback_agents.airports import default_path
        return default_path()

    def _work(self):
        started = time.monotonic()
        try:
            if self._sync is not None:
                report = self._sync()
            else:
                from .fallback_agents.airports import sync
                report = sync(self._path())
            self.last = {'ok': True, 'seconds': round(time.monotonic() - started, 1)}
            log.info('airport index refresh: %s in %.1f s', report, time.monotonic() - started)
        except Exception as exc:
            self.last = {'ok': False, 'error': type(exc).__name__}
            log.warning('airport index refresh failed: %s', type(exc).__name__)

    def run_due(self, force=False):
        now = self.clock()
        if self.thread is not None and self.thread.is_alive():
            return None
        if not force and (now < self.next_run or not airport_window(now)):
            return None
        self.next_run = now + self.EVERY
        if self._sync is None and not self._path().exists():
            return {'airport_index': 'no_index'}
        self.thread = threading.Thread(target=self._work, name='airport-index-refresh', daemon=True)
        self.thread.start()
        return {'airport_index': 'started'}
