"""Refresh the nvd-cve fallback's local NVD snapshot from the jobs scheduler (PM 11-14, agent team request).

Every two hours, between :15 and :50 (never in the hourly public measurement, :55-:10), the "modified" NVD feed is
read through nvd_store.Snapshot.sync('update'): one meta request when nothing changed, the feed when it did. The
fallback answers fail as stale after six hours (freshness max_age), so a stop of this step shows within the day.

It runs in a background thread of the jobs process (release code, not the working tree), one at a time; the
scheduler loop never waits for it. The snapshot lives under FALLBACK_AGENTS_DATA (default
gateway-data/fallback-agents, relative to the jobs working folder, the repository root). Without a snapshot file
(not built yet) it does nothing: the first full build is a separate, deliberate step.
"""
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
EVERY = 2 * 3600


def in_window(now):
    minute = datetime.fromtimestamp(now).minute
    return 15 <= minute <= 50


class NvdSnapshotRefresh:
    def __init__(self, clock=time.time, sync=None, data_dir=None):
        self.clock, self._sync, self.data_dir = clock, sync, data_dir
        self.next_run = 0.0
        self.thread = None
        self.last = None

    def _path(self):
        root = Path(self.data_dir or os.environ.get('FALLBACK_AGENTS_DATA', 'gateway-data/fallback-agents'))
        return root / 'nvd-cve.sqlite3'

    def _work(self):
        started = time.monotonic()
        try:
            if self._sync is not None:
                report = self._sync()
            else:
                from .fallback_agents.nvd_store import Snapshot
                report = Snapshot(self._path()).sync('update', log=lambda *a, **k: None)
            self.last = {'ok': True, 'seconds': round(time.monotonic() - started, 1)}
            log.info('nvd snapshot refresh: %s in %.1f s', {k: v for k, v in (report or {}).items() if k != 'feeds'},
                     time.monotonic() - started)
        except Exception as exc:  # the step never stops the scheduler; the next window tries again
            self.last = {'ok': False, 'error': type(exc).__name__}
            log.warning('nvd snapshot refresh failed: %s', type(exc).__name__)

    def run_due(self, force=False):
        now = self.clock()
        if self.thread is not None and self.thread.is_alive():
            return None
        if not force and (now < self.next_run or not in_window(now)):
            return None
        if self._sync is None and not self._path().exists():
            self.next_run = now + EVERY
            return {'nvd_snapshot': 'no_snapshot'}
        self.next_run = now + EVERY
        self.thread = threading.Thread(target=self._work, name='nvd-snapshot-refresh', daemon=True)
        self.thread.start()
        return {'nvd_snapshot': 'started'}
