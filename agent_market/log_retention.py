"""Calendar-day retention for application log files, using Asia/Seoul."""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
import re
import threading
from zoneinfo import ZoneInfo

LOG_TIMEZONE = ZoneInfo('Asia/Seoul')
DATED_LOG = re.compile(r'^.+_(\d{4}-\d{2}-\d{2})\.log(?:\.\d+)?$')
RUNTIME_LOG = re.compile(r'^.+\.log(?:\.\d+|\.startup)?$')
ARCHIVE_LOG = re.compile(r'^.+_(\d{4})-(\d{2})\.tar\.gz$')


def log_now():
    return dt.datetime.now(LOG_TIMEZONE)


def expired_log_files(log_dir, *, days=1, now=None, protected=()):
    """Select only regular runtime logs below the configured, non-symlink root."""
    if days < 1:
        raise ValueError('Log retention days must be positive.')
    root = Path(log_dir).absolute()
    if root.is_symlink() or not root.is_dir():
        return []
    now = now or log_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=LOG_TIMEZONE)
    cutoff = now.astimezone(LOG_TIMEZONE).date() - dt.timedelta(days=days-1)
    excluded = {Path(p).absolute() for p in protected}
    expired = []
    for file in root.rglob('*'):
        if file in excluded or file.is_symlink() or not file.is_file():
            continue
        if any(p.is_symlink() for p in file.parents if p != root.parent):
            continue
        match = DATED_LOG.fullmatch(file.name)
        archive = ARCHIVE_LOG.fullmatch(file.name)
        try:
            if match:
                date = dt.date.fromisoformat(match[1])
            elif archive:
                year, month = int(archive[1]), int(archive[2])
                if not 1 <= month <= 12:
                    continue
                next_month = dt.date(year+int(month==12), month%12+1, 1)
                date = next_month-dt.timedelta(days=1)
            elif RUNTIME_LOG.fullmatch(file.name):
                date = dt.datetime.fromtimestamp(file.stat().st_mtime, LOG_TIMEZONE).date()
            else:
                continue
        except (ValueError, OSError):
            continue
        if date < cutoff:
            expired.append(file)
    return sorted(expired)


class LogRetentionScheduler(threading.Thread):
    """Delete expired logs after closing the managed daily handles for those dates."""
    def __init__(self, log_dir, *, days=1, protected=(), close_expired=None, interval=300):
        super().__init__(daemon=True, name='log-retention')
        self.log_dir = log_dir
        self.days = days
        self.protected = tuple(protected)
        self.close_expired = close_expired
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def cleanup(self, now=None):
        now = now or log_now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=LOG_TIMEZONE)
        cutoff = now.astimezone(LOG_TIMEZONE).date()-dt.timedelta(days=self.days-1)
        if self.close_expired:
            self.close_expired(cutoff)
        removed = []
        for file in expired_log_files(self.log_dir, days=self.days, now=now, protected=self.protected):
            try:
                file.unlink()
                removed.append(file)
            except FileNotFoundError:
                pass
        return removed

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.cleanup()
            except OSError as exc:
                logging.getLogger(__name__).error('Log retention cleanup failed (%s); will retry.',type(exc).__name__)
            self._stop_event.wait(self.interval)
